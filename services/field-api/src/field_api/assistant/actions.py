"""The only actions a turn may return to the phone (M3 contract §4), whoever proposed them.

Anything else is dropped: unknown types, unknown commands, extra keys, and anything that would confirm a post.
There is no ``confirm`` command; posting needs the operator's own "confirm", handled by the phone's grammar and
checked by the server (post-requests).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

COMMANDS = frozenset({"next", "repeat", "post", "cancel", "all_here", "count"})
LISTEN_MODES = frozenset({"command", "free"})
MAX_ACTIONS = 4
_CONFIRMISH = re.compile(r"confirm|approve|authori[sz]e|sign[_ -]?off|yes[_ -]?post", re.IGNORECASE)
_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _confirmish(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_CONFIRMISH.search(value))
    if isinstance(value, dict):
        return any(_confirmish(k) or _confirmish(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_confirmish(v) for v in value)
    return False


def _one(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or _confirmish(raw):
        return None
    kind = raw.get("type")
    if kind in ("open_task", "refresh_task"):
        tid = raw.get("task_id")
        if not isinstance(tid, str) or not _ID.match(tid):
            return None
        out: dict[str, Any] = {"type": kind, "task_id": tid.lower()}
        if kind == "refresh_task":
            focus = raw.get("focus_code")
            if isinstance(focus, str) and 0 < len(focus.strip()) <= 128:
                out["focus_code"] = focus.strip()
        return out
    if kind == "command":
        cmd = raw.get("command")
        if cmd not in COMMANDS:
            return None
        out = {"type": "command", "command": cmd}
        if cmd == "count":
            value = raw.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            if not math.isfinite(value) or value < 0 or value > 1_000_000:
                return None
            out["value"] = int(value) if float(value).is_integer() else float(value)
        return out
    if kind == "listen":
        mode = raw.get("mode", "command")
        return {"type": "listen", "mode": mode} if mode in LISTEN_MODES else None
    return None


def sanitize(actions: Iterable[Any] | Any, visible_task_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Allowed actions only, at most MAX_ACTIONS, duplicates dropped. With ``visible_task_ids``, open_task and
    refresh_task must name one of them (a model can invent ids)."""
    if not isinstance(actions, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for raw in actions:
        a = _one(raw)
        if a is None or a in out:
            continue
        if visible_task_ids is not None and "task_id" in a and a["task_id"] not in visible_task_ids:
            continue
        out.append(a)
        if len(out) >= MAX_ACTIONS:
            break
    return out


def task_ids(actions: Iterable[Any] | Any) -> set[str]:
    if not isinstance(actions, (list, tuple)):
        return set()
    return {str(a["task_id"]).lower() for a in actions if isinstance(a, dict) and isinstance(a.get("task_id"), str)}
