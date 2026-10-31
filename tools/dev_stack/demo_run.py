"""The 3-minute demo run (M4-C17; the core's Q15): prepare the SCMTIPS core and SCMTips Field the same way, then
play the run's beats, each checked, and print what to show at each one. docs/DEMO_RUN.md is the operator's page.

    uv run python -m tools.dev_stack.demo_run --core <the SCMTIPS core checkout>
        [--scenario magnet-export-curbs] [--po PO-26-1002] [--web http://app.localhost:3100] [--wait 120]

Beats (each a command that already exists on its side; this file only orders them, checks them and times them):

0. preflight: the core's API and worker answer, its demo mode is on with a marked SAMPLE organisation
   (``scmtips-demo status``), Field's stack is up (field-api, erp-sim, field-worker) with FIELD_CORE_TARGET=core, and
   the core checkout holds the exports and the scenario pack;
1. core reset: ``uv run scmtips-demo reset`` and ``uv run scmtips-local-demo --with-team`` in the core (its planning
   samples come back); then the core's PO line (``--po``) is open again;
2. Field seed: ``stack seed-core-export <core>/samples/exports/erp-sim --reset`` (erp-sim's plants of the export back to
   exactly the export, the site pack's sites); then erp-sim holds an open ASN for the PO line;
3. ERP snapshot: ``stack smoke --erp-feed`` (the core's on-hand and open POs equal erp-sim's);
4. disruption: ``uv run scmtips-scenario inject <scenario> --wait`` in the core (SIMULATED signals workbook through
   the core's file mode; relevance gate, cascade, starvation clock, auto-drafted decision, the core's brief check);
5. approval: ``stack smoke --approver --decision <the decision of beat 4>`` (sign-in, exchange, spoken brief, the
   core's number check, "approve option two", read-back, confirm; the core commits);
6. receipt: ``stack smoke --core`` with FIELD_CORE_SMOKE_PO=<po> (GR 101 in erp-sim against the core's PO, two signed
   feed rows, the core's PO line received, on-hand = erp-sim, a new base plan run is required here);
7. what the judges see: URLs per beat (printed, nothing checked).

A beat fails loudly: its tool's exit code or a missing check stops the run with exit code 1 and the recovery for that
beat. Nothing here prints a result it did not check. ``scmtips-local-demo`` prints the kit's demo passwords, so its
output is never shown or logged (A-02). The transcript and a JSON summary go to var/demo-run/ (git-ignored).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tools.dev_stack import stack

ROOT = stack.ROOT
OUT = ROOT / "var" / "demo-run"
DEFAULT_SCENARIO = "magnet-export-curbs"
DEFAULT_PO = "PO-26-1002"  # CP-204 brushless motors from SUP-S02, the supplier the magnet export curbs hit (SAMPLE)
DEFAULT_WEB = "http://app.localhost:3100"  # the core kit's web (scmtips-local-demo prints app.localhost:3100)
NOISE = ("UV_NATIVE_TLS", "AuthlibDeprecationWarning", "from ._compat import httpx2", "core_snapshot_staged")
REPLAN = re.compile(r"re-plan: base plan run (\S+) -> (\S+);")


class BeatFailed(Exception):
    """A beat's tool failed or one of its checks did not hold."""


@dataclass(frozen=True)
class Beat:
    n: int
    title: str
    plan: str  # the hackathon plan's section-1 beat it serves
    show: str
    say: str
    fallback: str
    recover: str


@dataclass
class Outcome:
    n: int
    title: str
    ok: bool
    seconds: float
    commands: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    detail: str = ""


BEATS: tuple[Beat, ...] = (
    Beat(0, "preflight", "-", "-", "-", "-",
         "start the core kit (API :8000, worker :8001) with demo mode on, then the Field stack (`stack up`), and set"
         " FIELD_CORE_TARGET=core in Field's .env.local"),
    Beat(1, "core reset (SAMPLE organisation)", "set-up",
         "{web}/home: the SAMPLE banner, the restored sample", "The SAMPLE drone OEM, reset to its seeded state.",
         "the nightly reset (LR_DEMO_NIGHTLY_RESET) or POST /v1/demo/reset on the web",
         "in the core: `uv run scmtips-demo status` (demo mode on, marked); `uv run scmtips-demo mark` once if not;"
         " the worker must run for the sample to load again"),
    Beat(2, "Field seed from the core's export", "set-up for 6",
         "http://127.0.0.1:8002/_sim/ui: erp-sim's stock and the open ASN of the PO",
         "The ERP holds the same SAMPLE world as the core.",
         "none needed: the same command without --reset loads the export again",
         "`stack up` first (erp-sim and field-api must run); the export folder is the core's samples/exports/erp-sim"),
    Beat(3, "ERP snapshot to the core", "6 (leg I9) and 7",
         "{web}/data/pipeline and {web}/data/systems: the ERP card, last sync, rows",
         "Stock and open purchase orders come from the ERP, signed.",
         "the ERP extract file through the core's file mode (POST /v1/exchange/messages/erp_extract/import-file)",
         "field-worker must run; the feed secrets in Field's .env.local must match the core's two feeds"),
    Beat(4, "disruption: scenario injected in the core", "1 and 2",
         "{web}/signals (the SIMULATED magnet-curbs signal), {web}/exposure (CP-204 -> SA-120 -> FG-100, FG-200;"
         " starvation clock)",
         "Only a signal that touches our suppliers and parts becomes a decision.",
         "the signals workbook file (`uv run scmtips-scenario file <name> -o x.csv`, upload on the web), labelled"
         " SIMULATED; the live market-intelligence pull is not part of this run",
         "the core: `uv run scmtips-scenario inject <name> --wait` alone shows what is unmet; reset (beat 1) if an"
         " older decision on the same signal is open"),
    Beat(5, "approval by voice through Field", "4",
         "glasses POV or the phone: the spoken brief, 'approve option two', the read-back, 'confirm';"
         " {web}/decisions/{decision}: EXECUTING, the audit entry",
         "The approver hears a short brief and approves by voice; the core checks every number first.",
         "the core's phone approval page ({web}/decisions/{decision}); the HUD simulator (F5) is not built",
         "`stack smoke --approver --decision <id>`; if another decision waits first, reset (beat 1)"),
    Beat(6, "goods receipt in Field -> the core re-plans", "6, the finale",
         "the phone's receive job (or erp-sim's documents at http://127.0.0.1:8002/_sim/ui), then {web}/data/open-supply"
         " ({po} received), {web}/data/inventory (CP-204 on-hand), {web}/exposure (the clock)",
         "The motors arrive, the ERP posts the receipt, and the core re-plans on that evidence.",
         "the goods-receipt file through the core's file mode (POST /v1/exchange/messages/goods_receipt/import-file)",
         "`stack seed-core-export <export> --reset` then `FIELD_CORE_SMOKE_PO=<po> stack smoke --core`; field-worker"
         " must run (it imports the ASN as a receive job and delivers the two rows)"),
    Beat(7, "what the judges see", "7",
         "{web}/data/systems: Connected systems (modes, last sync, failures); {web}/settings/audit: the audit chain",
         "Every system has a live and a file mode; switching one keeps the run going.",
         "-", "-"),
)


@dataclass
class Ctx:
    core: Path
    scenario: str
    po: str
    web: str
    wait: float
    core_env: dict[str, str]
    log: list[str] = field(default_factory=list)
    decision: str = ""
    tenant: str = ""  # the core's SAMPLE organisation (= the Field tenant), as `scmtips-demo status` reports it
    po_item: str = ""
    po_plant: str = ""
    run: Callable[..., tuple[int, str, str]] | None = None

    def say(self, line: str = "") -> None:
        print(line, flush=True)
        self.log.append(line)


def _clean(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not any(n in ln for n in NOISE)]


def run_cmd(cmd: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) of one command; a missing tool or a timeout is a failure, never a pass."""
    try:
        p = subprocess.run(list(cmd), cwd=cwd, env=dict(env), capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        return 127, "", f"{cmd[0]} not found: {e}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:.0f} s"
    return p.returncode, p.stdout, p.stderr


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise BeatFailed("uv is not on PATH (both repositories run their tools with `uv run`)")
    return uv


def field_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "tools.dev_stack.stack", *args]


def core_cmd(*args: str) -> list[str]:
    return [_uv(), "run", "--frozen", *args]


def _exec(ctx: Ctx, out: Outcome, cmd: list[str], cwd: Path, env: Mapping[str, str], *, show: bool = True,
          timeout: float = 900, stdout_on_failure: bool = False) -> tuple[str, str]:
    shown = " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))
    out.commands.append(shown)
    ctx.say(f"  $ {shown}")
    runner = ctx.run or run_cmd
    rc, so, se = runner(cmd, cwd, env, timeout)
    if show:
        for ln in _clean(so) + _clean(se):
            ctx.say(f"    {ln}")
    if rc != 0:
        if not show:  # output withheld (e.g. the kit's passwords): the error stream's tail, the report if harmless
            for ln in (_clean(so)[-40:] if stdout_on_failure else []) + _clean(se)[-15:]:
                ctx.say(f"    {ln}")
        raise BeatFailed(f"`{shown}` exited with code {rc}")
    return so, se


def _field_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(extra or {})
    return env


def _check(out: Outcome, ok: bool, what: str) -> None:
    if not ok:
        raise BeatFailed(f"check failed: {what}")
    out.checked.append(what)


def export_po(core: Path, po: str) -> tuple[str, str, str]:
    """(item, plant, status) of the PO line ``po`` in the core's erp-sim export."""
    path = core / "samples" / "exports" / "erp-sim" / "purchase_orders.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("ref") == po:
                return str(row["item_code"]), str(row["location_code"]), str(row.get("status") or "open")
    raise BeatFailed(f"{po} is not a PO line of the core's export ({path})")


# --- the beats -------------------------------------------------------------------------------------------------------

def beat_preflight(ctx: Ctx, out: Outcome) -> None:
    for rel in ("samples/exports/erp-sim/purchase_orders.csv", "samples/exports/field-site-pack/sites.csv",
                "samples/scenarios/scenarios.json"):
        _check(out, (ctx.core / rel).is_file(), f"the core checkout holds {rel}")
    ctx.po_item, ctx.po_plant, _ = export_po(ctx.core, ctx.po)
    _check(out, stack.core_target() == "core", "FIELD_CORE_TARGET=core in Field's .env.local")
    base = os.environ.get("FIELD_CORE_BASE_URL", "").rstrip("/")
    _check(out, _answers(f"{base}/v1/health"), f"the core's API answers ({base}/v1/health)")
    worker = os.environ.get("SCMTIPS_WORKER_HEALTH_URL", "http://127.0.0.1:8001/healthz")
    _check(out, _answers(worker), f"the core's worker answers ({worker})")
    for name, path in (("field-api", "/v1/health"), ("erp-sim", "/_sim/health")):
        _check(out, _answers(stack.local(name) + path), f"Field's {name} answers ({stack.local(name)})")
    pf = stack._pidfile("field-worker")
    _check(out, pf.exists() and stack._alive(int(pf.read_text())), "Field's field-worker runs (`stack up`)")
    so, _ = _exec(ctx, out, core_cmd("scmtips-demo", "status"), ctx.core, ctx.core_env)
    st = _json(so, "scmtips-demo status")
    _check(out, st.get("env") != "production" and st.get("demo_mode") is True and st.get("marked") is True,
           f"the core's demo mode is on and its organisation {st.get('organisation')!r} is marked")
    ctx.tenant = str(st.get("demo_tenant_id") or "")
    # The two feeds belong to the core's SAMPLE organisation. Without this setting the worker's snapshot reads the
    # drone plants for every Field tenant with a site on them (K5: tenants made by tests), and their older rows reached
    # the core after its reset.
    allowed = [t.strip() for t in os.environ.get("FIELD_CORE_SNAPSHOT_TENANTS", "").split(",") if t.strip()]
    _check(out, allowed == [ctx.tenant], f"FIELD_CORE_SNAPSHOT_TENANTS names exactly the core's SAMPLE organisation"
                                         f" {ctx.tenant} (now {allowed or 'empty'}; set it, then `stack down`, `stack up`)")
    others = sum(n for t, n in pending_deliveries().items() if t != ctx.tenant)
    _check(out, others == 0, f"no feed rows of other Field tenants wait for the core ({others} pending)")


def pending_deliveries() -> dict[str, int]:
    """Field feed rows not yet sent to the core, per Field tenant (field.core_feed_delivery, status pending)."""
    import psycopg

    with psycopg.connect(stack._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT tenant_id::text, count(*) FROM field.core_feed_delivery WHERE status = 'pending'"
                    " GROUP BY 1")
        return {str(t): int(n) for t, n in cur.fetchall()}


def beat_reset(ctx: Ctx, out: Outcome) -> None:
    from tools.dev_stack import core_smoke

    # a row staged before the reset and sent after it would put the old state back: let the worker send them first
    core_smoke.wait_until("Field's pending feed rows for the core sent", lambda: (
        lambda n: "drained" if n == 0 else None)(pending_deliveries().get(ctx.tenant, 0)), ctx.wait)
    out.checked.append("no Field feed row for the core waits (none can land after the reset)")
    so, _ = _exec(ctx, out, core_cmd("scmtips-demo", "reset"), ctx.core, ctx.core_env)
    _check(out, re.search(r"demo reset: \d+ rows deleted", so) is not None, "the core reset its demo organisation")
    ctx.say("  (scmtips-local-demo's output is not shown: it prints the kit's demo passwords)")
    so, _ = _exec(ctx, out, core_cmd("scmtips-local-demo", "--with-team"), ctx.core, ctx.core_env, show=False)
    _check(out, "Credentials file" in so, "the core's local demo re-created its planning samples and kept the team")
    web = core_smoke.CoreWeb(core_smoke.core_base(), "OPERATOR")
    try:
        line = core_smoke.wait_until(f"the core's {ctx.po} restored by the reset", lambda: (
            lambda x: x if x and x.get("status") != "received" else None)(
            core_smoke.core_line(web, ctx.po, ctx.po_item)), ctx.wait)
    finally:
        web.close()
    out.checked.append(f"the core's {ctx.po} ({ctx.po_item}) is {line['status']} again (wait_until read it)")
    ctx.say(f"  the core's {ctx.po} {ctx.po_item}@{line['location_code']} {line['status']} qty {line['qty']}")


def beat_seed(ctx: Ctx, out: Outcome) -> None:
    export = ctx.core / "samples" / "exports" / "erp-sim"
    so, _ = _exec(ctx, out, field_cmd("seed-core-export", str(export), "--reset"), ROOT, _field_env())
    _check(out, "loaded into erp-sim" in so and "site pack" in so, "erp-sim loaded from the export, site pack applied")
    from tools.dev_stack import core_smoke

    asn = core_smoke.open_asn(ctx.po, ctx.po_item, ctx.po_plant)
    _check(out, asn is not None, f"erp-sim holds an open ASN for {ctx.po} ({ctx.po_item} at {ctx.po_plant})")
    assert asn is not None
    ctx.say(f"  erp-sim: open ASN {asn[0]} for {ctx.po}, {ctx.po_item} {asn[1]:g}")


def beat_snapshot(ctx: Ctx, out: Outcome) -> None:
    so, _ = _exec(ctx, out, field_cmd("smoke", "--erp-feed", "--wait", f"{ctx.wait:g}"), ROOT, _field_env())
    _check(out, "core = erp-sim" in so, "the core's on-hand and open POs equal erp-sim's")


def beat_inject(ctx: Ctx, out: Outcome) -> None:
    so, _ = _exec(ctx, out, core_cmd("scmtips-scenario", "inject", ctx.scenario, "--wait"), ctx.core, ctx.core_env,
                  show=False, timeout=600, stdout_on_failure=True)  # its JSON report holds no credentials
    rep = _json(so, "scmtips-scenario inject")
    sig, exp, dec, brief = (rep.get(k) or {} for k in ("signal", "exposure", "decision", "brief"))
    ctx.say(f"    signal {sig.get('id')} {sig.get('band_label')} {sig.get('score')} ({sig.get('origin')}), suppliers"
            f" {sig.get('suppliers')}; SIMULATED ({rep.get('transport')})")
    ctx.say(f"    exposure: items {exp.get('affected_items')}, finished goods {exp.get('finished_goods_fed')}; clock "
            + ", ".join(f"{s['item']} {s['days_to_stockout']} d" for s in exp.get("starvation") or []))
    ctx.say(f"    decision {dec.get('id')} {dec.get('status')} auto_drafted={dec.get('auto_drafted')}: "
            + "; ".join(dec.get("options") or []))
    ctx.say(f"    the core's brief check: accepted={brief.get('accepted')}, a changed number refused="
            f"{brief.get('changed_number_refused')}")
    _check(out, not rep.get("unmet"), f"the scenario's expectations all met (unmet {rep.get('unmet')})")
    _check(out, bool(dec.get("id")) and dec.get("auto_drafted") is True, "the core auto-drafted a decision")
    _check(out, brief.get("accepted") is True and brief.get("changed_number_refused") is True,
           "the core accepts its brief and refuses a changed number")
    ctx.decision = str(dec["id"])


def beat_approve(ctx: Ctx, out: Outcome) -> None:
    so, _ = _exec(ctx, out, field_cmd("smoke", "--approver", "--decision", ctx.decision, "--wait", f"{ctx.wait:g}"),
                  ROOT, _field_env())
    _check(out, f"decision {ctx.decision}" in so and "approve option two" in so,
           f"the approver approved decision {ctx.decision} by voice through Field")


def beat_receipt(ctx: Ctx, out: Outcome) -> None:
    so, _ = _exec(ctx, out, field_cmd("smoke", "--core", "--wait", f"{ctx.wait:g}"), ROOT,
                  _field_env({"FIELD_CORE_SMOKE_PO": ctx.po}))
    _check(out, "export mode" in so, "the GR went against the core's own PO (export mode, no code map)")
    _check(out, f"{ctx.po} status received" in so, f"the core's {ctx.po} is received")
    m = REPLAN.search(so)
    _check(out, m is not None and m.group(1) != m.group(2), "the core re-planned after the receipt (new base plan run)")


def beat_screens(ctx: Ctx, out: Outcome) -> None:
    for b in BEATS[1:]:
        ctx.say(f"  beat {b.n} (plan beat {b.plan}): {_fmt(b.show, ctx)}")
        ctx.say(f"      say: {b.say}")
        if b.fallback != "-":
            ctx.say(f"      file / fallback: {_fmt(b.fallback, ctx)}")
    out.detail = "printed only, nothing checked"


STEPS: dict[int, Callable[[Ctx, Outcome], None]] = {
    0: beat_preflight, 1: beat_reset, 2: beat_seed, 3: beat_snapshot, 4: beat_inject, 5: beat_approve,
    6: beat_receipt, 7: beat_screens,
}


def _fmt(text: str, ctx: Ctx) -> str:
    return text.format(web=ctx.web, po=ctx.po, decision=ctx.decision or "<decision id>")


def _answers(url: str) -> bool:
    try:
        return httpx.get(url, timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def _json(text: str, what: str) -> dict[str, Any]:
    start = text.find("{")
    try:
        data = json.loads(text[start:]) if start >= 0 else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise BeatFailed(f"{what} printed no JSON report")
    return data


def _git_sha(repo: Path) -> str:
    rc, so, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"], repo, os.environ, 10)
    return so.strip() if rc == 0 else "unknown"


def core_env_from(env: Mapping[str, str]) -> dict[str, str]:
    """The environment for the core's commands: the caller's own (where the core's demo settings may be exported),
    without Field's virtual environment and without any FIELD_* value Field's .env.local put there."""
    return {k: v for k, v in env.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
            and not k.startswith("FIELD_")}


def play(ctx: Ctx, only: Sequence[int] | None = None) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for b in BEATS:
        if only is not None and b.n not in only:
            continue
        ctx.say("")
        ctx.say(f"=== beat {b.n}/7: {b.title}")
        out = Outcome(b.n, b.title, ok=False, seconds=0.0)
        t0 = time.monotonic()
        try:
            STEPS[b.n](ctx, out)
            out.ok = True
        except BeatFailed as e:
            out.detail = str(e)
        except Exception as e:  # noqa: BLE001 - a smoke helper's own failure is this beat's failure, shown as such
            out.detail = f"{type(e).__name__}: {e}"
        out.seconds = round(time.monotonic() - t0, 1)
        outcomes.append(out)
        for c in out.checked:
            ctx.say(f"  checked: {c}")
        if not out.ok:
            ctx.say(f"beat {b.n} FAILED after {out.seconds:g} s: {out.detail}")
            ctx.say(f"  recovery: {_fmt(b.recover, ctx)}")
            if b.fallback != "-":
                ctx.say(f"  file / fallback for the video: {_fmt(b.fallback, ctx)}")
            break
        if b.n == 7:
            ctx.say("beat 7 printed (nothing to check)")
        else:
            ctx.say(f"beat {b.n} ok in {out.seconds:g} s ({len(out.checked)} checked)")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_run", description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--core", default=os.environ.get("SCMTIPS_CORE_DIR", ""),
                    help=r"the SCMTIPS core checkout (e.g. <workspace>\ARO; default SCMTIPS_CORE_DIR)")
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--po", default=DEFAULT_PO, help="the core PO line received in beat 6 (default %(default)s)")
    ap.add_argument("--web", default=os.environ.get("SCMTIPS_WEB_URL", DEFAULT_WEB), help="the core's web, for beat 7")
    ap.add_argument("--wait", type=float, default=120.0, help="seconds per wait inside a beat")
    a = ap.parse_args(argv)
    if not a.core or not Path(a.core).is_dir():
        print("FAIL: --core <the SCMTIPS core checkout> (or SCMTIPS_CORE_DIR) is needed and must exist")
        return 1
    core_env = core_env_from(os.environ)
    stack.load_env()
    stack.apply_ports()
    ctx = Ctx(core=Path(a.core).resolve(), scenario=a.scenario, po=a.po, web=a.web.rstrip("/"), wait=a.wait,
              core_env=core_env)
    started = datetime.now(UTC)
    ctx.say(f"demo run {started:%Y-%m-%d %H:%M:%S}Z: core {ctx.core} ({_git_sha(ctx.core)}), Field {ROOT}"
            f" ({_git_sha(ROOT)}); scenario {a.scenario}, PO {a.po}. SAMPLE data; scenario files are SIMULATED.")
    t0 = time.monotonic()
    outcomes = play(ctx)
    total = round(time.monotonic() - t0, 1)
    checked = [o for o in outcomes if o.n not in (0, 7)]
    ok = len(outcomes) == len(BEATS) and all(o.ok for o in outcomes)
    ctx.say("")
    ctx.say(f"summary: {sum(o.ok for o in checked)} of {len(BEATS) - 2} beats ok, preflight"
            f" {'ok' if outcomes and outcomes[0].ok else 'FAILED'}, {total:g} s in all: " + ", ".join(
                f"{o.n} {'ok' if o.ok else 'FAILED'} {o.seconds:g} s" for o in outcomes if o.n != 7)
            + ("; screens printed" if ok else "; stopped, see the recovery above"))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = f"{started:%Y%m%dT%H%M%SZ}"
    (OUT / f"{stamp}.log").write_text("\n".join(ctx.log) + "\n", encoding="utf-8")
    (OUT / f"{stamp}.json").write_text(json.dumps({
        "started_at": started.isoformat(), "seconds": total, "ok": ok, "core_sha": _git_sha(ctx.core),
        "field_sha": _git_sha(ROOT), "scenario": a.scenario, "po": a.po, "decision": ctx.decision,
        "beats": [asdict(o) for o in outcomes]}, indent=2), encoding="utf-8")
    print(f"transcript var/demo-run/{stamp}.log, summary var/demo-run/{stamp}.json")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
