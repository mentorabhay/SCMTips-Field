"""Task and line states as the M2 jobs contract shows them (docs/design/M2_JOBS_CONTRACT.md §2).

The database keeps the states the posting worker has always used (pending, posting, completed, ...);
clients see the contract's words. ``to_db_task_states`` maps a client filter back, and also accepts
the stored words so older clients keep working.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from types import MappingProxyType

TASK_TYPES = frozenset({"receive", "putaway", "pick", "count", "audit", "swap"})

TASK_STATE_OUT = MappingProxyType({
    "pending": "open",
    "in_progress": "in_progress",
    "posting": "awaiting_posting",
    "awaiting_approval": "awaiting_approval",
    "completed": "done",
    "failed": "failed",
    "cancelled": "cancelled",
})

LINE_STATE_OUT = MappingProxyType({
    "pending": "open",
    "in_progress": "open",
    "counted": "counted",
    "recount": "counted",  # never reveal that a variance exists (FR3.029)
    "posting": "counted",
    "confirmed": "confirmed",
    "flagged": "flagged",
    "posted": "done",
    "done": "done",
    "waived": "done",
    "cancelled": "done",
})

_TASK_STATE_IN: dict[str, str] = {v: k for k, v in TASK_STATE_OUT.items()}


def task_state_out(db_state: str) -> str:
    return TASK_STATE_OUT.get(db_state, db_state)


def line_state_out(db_state: str) -> str:
    return LINE_STATE_OUT.get(db_state, db_state)


def split_list(value: str | None) -> list[str]:
    """``"open,in_progress"`` -> ``["open", "in_progress"]`` (blank items dropped)."""
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def to_db_task_states(states: Iterable[str]) -> list[str] | None:
    """Contract (or stored) state names -> stored names; None if any name is unknown."""
    out: list[str] = []
    for s in states:
        if s in _TASK_STATE_IN:
            out.append(_TASK_STATE_IN[s])
        elif s in TASK_STATE_OUT:
            out.append(s)
        else:
            return None
    return out


def _plural(n: int | float, noun: str) -> str:
    n_txt = f"{n:g}" if isinstance(n, float) else str(n)
    return f"{n_txt} {noun}" if n == 1 else f"{n_txt} {noun}s"


def compose_subtitle(task_type: str, context: str | None, line_count: int, pieces: Decimal) -> str:
    """The second line of a task card: stored context (who/where) plus live line totals.

    Count tasks never show quantities (blind count, FR3.029).
    """
    parts = [context] if context else []
    if task_type == "count":
        parts += [_plural(line_count, "item"), "blind count"]
    elif task_type == "pick":
        parts += [_plural(line_count, "stop"), _plural(float(pieces), "piece")]
    elif task_type == "audit":
        parts += [_plural(line_count, "unit")]
    elif task_type == "swap":
        pass
    else:
        parts += [_plural(line_count, "item"), _plural(float(pieces), "piece")]
    return " · ".join(parts)


def hash_quantity_column(task_type: str) -> str:
    """Which line quantity the client's staged_hash covers (contract §4).

    pick: picked_qty (the list shows it as the line's counted_qty); every other type: counted_qty
    (0 for putaway / audit / swap lines, which are confirmed by scans, not counted). The phone hashes
    the counted_qty the task list reported, 0 if absent.
    """
    return "picked_qty" if task_type == "pick" else "counted_qty"
