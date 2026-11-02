"""Walk the installed Field app on an emulator with adb, keep a screenshot per named step and a screen
recording of the whole walk, and write steps.json (what was on screen after every step) — M5-K01.

Usage: python -m tools.app_screens.drive --out <dir> [--package com.scmtips.field.debug]
Needs adb on PATH and one running device with the app installed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

from tools.app_screens.steps import ADVANCE, WALK, Step
from tools.app_screens.uitree import Node, find, labels, parse

ACTIVITY = "com.scmtips.field.app.MainActivity"


def adb(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["adb", *args], capture_output=True, timeout=timeout, check=False)


def screen() -> tuple[str, list[Node]]:
    raw = adb("exec-out", "uiautomator", "dump", "/dev/tty").stdout.decode("utf-8", "replace")
    try:
        return raw, parse(raw)
    except Exception:  # an animation can make a dump fail; the caller tries again
        return raw, []


def wait_for(pattern: str, timeout: float) -> Node | None:
    """Look for `pattern`; after half the time, scroll the screen up once in case it is below the fold."""
    end = time.monotonic() + timeout
    scrolled = False
    while time.monotonic() < end:
        _, nodes = screen()
        if dismiss_anr(nodes):
            continue
        hit = find(nodes, pattern)
        if hit is not None:
            return hit
        if not scrolled and time.monotonic() > end - timeout / 2:
            adb("shell", "input", "swipe", "540", "1700", "540", "900", "400")
            scrolled = True
        time.sleep(1.0)
    return None


def dismiss_anr(nodes: list[Node]) -> bool:
    """A freshly booted emulator can show "System UI isn't responding"; answer Wait and carry on."""
    if find(nodes, r"isn.t responding") is None:
        return False
    wait = find(nodes, r"^Wait$")
    if wait is not None:
        tap(wait)
        time.sleep(2.0)
    return True


def in_front(package: str) -> bool:
    focus = adb("shell", "dumpsys", "window", "displays").stdout.decode("utf-8", "replace")
    return any(package in line for line in focus.splitlines() if "mCurrentFocus" in line or "mFocusedApp" in line)


def tap(node: Node) -> None:
    x, y = node.center
    adb("shell", "input", "tap", str(x), str(y))


class Recorder:
    """screenrecord stops at 3 minutes, so the walk is recorded in parts of 170 s."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self.parts: list[str] = []
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        n = 0
        while not self._stop.is_set():
            n += 1
            remote = f"/sdcard/walk-{n:02d}.mp4"
            self.parts.append(remote)
            adb("shell", "screenrecord", "--bit-rate", "8000000", "--time-limit", "170", remote, timeout=200)

    def start(self) -> None:
        self._thread.start()

    def stop(self, out: Path) -> list[str]:
        self._stop.set()
        adb("shell", "pkill", "-2", "screenrecord")
        self._thread.join(timeout=30)
        time.sleep(2)
        kept: list[str] = []
        for remote in self.parts:
            local = out / Path(remote).name
            adb("pull", remote, str(local), timeout=120)
            if local.exists() and local.stat().st_size > 0:
                kept.append(local.name)
        return kept


def run(out: Path, package: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    adb("shell", "am", "start", "-W", "-n", f"{package}/{ACTIVITY}")
    rec = Recorder()
    rec.start()
    report: list[dict[str, object]] = []
    shot_no = 0
    stopped = False
    for i, step in enumerate(WALK):
        ok, note = execute(step)
        if step.kind == "shot":
            dismiss_anr(screen()[1])
            shot_no += 1
            name = f"{shot_no:02d}-{step.name}.png"
            (out / name).write_bytes(adb("exec-out", "screencap", "-p").stdout)
            note = name
        if not in_front(package):  # a system Back on a root screen leaves the app: bring it back
            adb("shell", "am", "start", "-n", f"{package}/{ACTIVITY}")
            time.sleep(3)
            note = (note + "; " if note else "") + "the app was brought back to the front"
        raw, nodes = screen()
        report.append({"step": i, "kind": step.kind, "arg": step.arg, "name": step.name, "ok": ok, "note": note, "screen": labels(nodes)[:40]})
        if not ok:
            (out / f"fail-{i:03d}.xml").write_text(raw, encoding="utf-8")
            if step.required:
                stopped = True
                break
    videos = rec.stop(out)
    summary = {"package": package, "steps": len(report), "failed": sum(1 for r in report if not r["ok"]), "stopped": stopped, "videos": videos, "report": report}
    (out / "steps.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{len(report)} steps, {summary['failed']} not done, stopped={stopped}, videos={videos}")
    return 1 if stopped else 0


def execute(step: Step) -> tuple[bool, str]:
    if step.kind == "sleep":
        time.sleep(float(step.arg or "1"))
        return True, ""
    if step.kind == "back":
        _, nodes = screen()
        own = find(nodes, r"^(Back|Close|Cancel|Done|Back to the check)$")
        if own is not None:
            tap(own)
            time.sleep(1.5)
            return True, f"tapped {own.label!r}"
        adb("shell", "input", "keyevent", "4")
        time.sleep(1.5)
        return True, "system back"
    if step.kind == "shot":
        time.sleep(0.8)
        return True, ""
    if step.kind in ("tap", "maybe"):
        hit = wait_for(step.arg, 20 if step.kind == "tap" else 6)
        if hit is None:
            return step.kind == "maybe", f"not on screen: {step.arg}"
        tap(hit)
        time.sleep(1.5)
        return True, f"tapped {hit.label!r}"
    if step.kind == "hidekb":
        if "mInputShown=true" in adb("shell", "dumpsys", "input_method").stdout.decode("utf-8", "replace"):
            adb("shell", "input", "keyevent", "4")  # with the keyboard open, Back only closes the keyboard
            time.sleep(1.0)
        return True, ""
    if step.kind == "type":
        hit = wait_for(step.arg, 10)
        if hit is None:
            return False, f"no field {step.arg}"
        tap(hit)
        time.sleep(0.8)
        adb("shell", "input", "text", step.name)
        time.sleep(0.8)
        return True, f"typed into {hit.label!r}"
    if step.kind == "wait":
        return (wait_for(step.arg, 30) is not None), ""
    if step.kind == "advance":
        taps: list[str] = []
        for _ in range(12):
            _, nodes = screen()
            if find(nodes, step.arg) is not None:
                return True, "; ".join(taps)
            nxt = find(nodes, ADVANCE)
            if nxt is None:
                time.sleep(2)
                continue
            taps.append(nxt.label)
            tap(nxt)
            time.sleep(3)
        return False, "did not reach " + step.arg + " after " + "; ".join(taps)
    return False, f"unknown step kind {step.kind}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--package", default="com.scmtips.field.debug")
    args = ap.parse_args()
    return run(Path(args.out), args.package)


if __name__ == "__main__":
    raise SystemExit(main())
