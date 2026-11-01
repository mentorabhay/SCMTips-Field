"""The deterministic check of a look (stage d, contract §1 and §2): counts, pack size, expiry, batches, proposal.

Models only say what they saw (instances) and what a label says (pieces per unit, batch, expiry, damage). Every
decision is made here, from those reads and the delivery line:

- counts: ``seen`` = instances; ``damaged`` = instances a model saw damaged; ``flagged`` = damaged, and on a
  pharmacy case also expired or expiring within the window; ``good`` = seen - flagged (what is received
  unrestricted). So good + flagged = seen, always.
- pack (when the line expects pieces per unit, case C1): among instances whose label was read with a pieces value,
  ``mismatches`` are those that differ from the expected value, and ``pieces_difference`` = sum of the read values
  - expected x (number of such reads). Unread labels count in neither; they are reported. Pack differences are
  not flagged: the packs are received and the pieces claimed.
- expiry (case C2): a month-only expiry ("2027-03") means the end of that month; it is ``expired`` before today and
  ``near`` within ``window_days`` of today. Batches: the distinct batch codes read; more than one is reported.
- proposal: receive = good, flag = flagged, with the reasons in words.

Without instances (no model answered) every count is null and nothing is proposed: the operator says the count.
"""

from __future__ import annotations

import calendar
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class Seen:
    n: int
    damaged: bool = False
    read: bool = False
    pieces_per_unit: int | None = None
    batch: str | None = None
    expiry: str | None = None


@dataclass(frozen=True)
class Expectation:
    case: str  # 'grocery' | 'pharmacy' | 'generic'
    object_noun: str
    expected_units: int | None = None
    expected_pieces_per_unit: int | None = None
    window_days: int = 90


@dataclass
class Check:
    counts: dict[str, int | None]
    pack: dict[str, Any] | None
    expiry: dict[str, Any] | None
    proposal: dict[str, Any]
    flagged: list[int] = field(default_factory=list)
    unread: int = 0
    units_difference: int | None = None
    pack_groups: list[tuple[int, int, int]] = field(default_factory=list)  # (count, pieces per unit, pieces diff)
    expired: int = 0
    near: int = 0


def plural(noun: str, k: int) -> str:
    if k == 1:
        return noun
    if noun.endswith(("s", "x", "ch", "sh")):
        return noun + "es"
    if noun.endswith("y") and len(noun) > 1 and noun[-2] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def expiry_date(expiry: str) -> date | None:
    """'YYYY-MM-DD' -> that day; 'YYYY-MM' -> the last day of that month; anything else -> None."""
    try:
        parts = [int(p) for p in expiry.split("-")]
        if len(parts) == 3:
            return date(parts[0], parts[1], parts[2])
        if len(parts) == 2:
            return date(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1])
    except (ValueError, TypeError):
        return None
    return None


def expiry_status(expiry: str | None, today: date, window_days: int) -> str | None:
    """'expired', 'near' or None (fine, or no readable expiry)."""
    d = expiry_date(expiry) if expiry else None
    if d is None:
        return None
    if d < today:
        return "expired"
    if d <= today + timedelta(days=window_days):
        return "near"
    return None


def reconcile(seen: Sequence[Seen] | None, exp: Expectation, today: date) -> Check:
    if seen is None:
        return Check(counts={"expected": exp.expected_units, "seen": None, "damaged": None, "good": None},
                     pack=None, expiry=None, proposal={"receive": None, "flag": None, "reasons": []})
    items = sorted(seen, key=lambda s: s.n)
    noun = exp.object_noun
    damaged = [s.n for s in items if s.damaged]
    reasons: list[str] = []
    units_diff = None if exp.expected_units is None else len(items) - exp.expected_units
    if units_diff:
        reasons.append(f"{abs(units_diff)} {plural(noun, abs(units_diff))} {'short' if units_diff < 0 else 'over'}")
    if damaged:
        reasons.append(f"{len(damaged)} damaged")
    pack: dict[str, Any] | None = None
    groups: list[tuple[int, int, int]] = []
    unread = sum(1 for s in items if not s.read)
    if exp.expected_pieces_per_unit is not None:
        e = exp.expected_pieces_per_unit
        reads = [s for s in items if s.read and s.pieces_per_unit is not None]
        mismatches = [{"n": s.n, "pieces_per_unit": s.pieces_per_unit} for s in reads if s.pieces_per_unit != e]
        difference = sum(int(s.pieces_per_unit or 0) for s in reads) - e * len(reads) if reads else None
        pack = {"expected_pieces_per_unit": e, "mismatches": mismatches, "pieces_difference": difference}
        by_value = Counter(int(s.pieces_per_unit or 0) for s in reads if s.pieces_per_unit != e)
        for value in sorted(by_value):
            k = by_value[value]
            diff = k * (value - e)
            groups.append((k, value, diff))
            reasons.append(f"{k} {plural(noun, k)} {'hold' if k != 1 else 'holds'} {value}, not {e}: "
                           f"{abs(diff)} {plural('piece', abs(diff))} {'short' if diff < 0 else 'over'}")
    expiry: dict[str, Any] | None = None
    expiry_flagged: list[int] = []
    expired = near = 0
    if exp.case == "pharmacy":
        flagged_list: list[dict[str, Any]] = []
        for s in items:
            status = expiry_status(s.expiry, today, exp.window_days) if s.read else None
            if status:
                flagged_list.append({"n": s.n, "expiry": s.expiry, "reason": status})
                expiry_flagged.append(s.n)
        expired = sum(1 for f in flagged_list if f["reason"] == "expired")
        near = len(flagged_list) - expired
        batches = sorted({s.batch for s in items if s.read and s.batch})
        expiry = {"window_days": exp.window_days, "flagged": flagged_list, "batches": batches}
        if expired:
            reasons.append(f"{expired} expired")
        if near:
            reasons.append(f"{near} {'expire' if near != 1 else 'expires'} within {exp.window_days} days")
        if len(batches) > 1:
            reasons.append(f"{len(batches)} batches: {', '.join(batches)}")
    if unread:
        reasons.append(f"{unread} {plural('label', unread)} not read")
    flagged = sorted(set(damaged) | set(expiry_flagged))
    good = len(items) - len(flagged)
    return Check(counts={"expected": exp.expected_units, "seen": len(items), "damaged": len(damaged), "good": good},
                 pack=pack, expiry=expiry, proposal={"receive": good, "flag": len(flagged), "reasons": reasons},
                 flagged=flagged, unread=unread, units_difference=units_diff, pack_groups=groups, expired=expired,
                 near=near)
