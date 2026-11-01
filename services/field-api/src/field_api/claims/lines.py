"""Claim lines from a look (M5 contract section 3): deterministic, never a model's opinion.

Each instance of the look gets at most one reason, in this order of precedence:
  damaged (``instances[].damaged`` is true) > expired > near_expiry (``expiry.flagged[]`` by ``n``, reason
  "expired" / anything else = near) > pack_size (``pack.mismatches[]`` by ``n`` whose pieces per unit are below
  ``pack.expected_pieces_per_unit``).
Damaged, expired and near-expiry units are the look's *flagged* units (posted to quality, 101Q) and are claimed
whole; a pack that holds fewer pieces is received and claimed for the missing pieces only. A pack with more pieces
than expected is not claimed. ``short`` is the delivery shortfall: ``counts.expected - counts.seen`` when the look
saw fewer than expected (never when ``seen`` is unknown, i.e. a rules-only look).

``pieces`` of a whole-unit line (damaged, expired, near_expiry, short) is units x the expected pieces per unit when
the look has a pack line (case C1), else 0 (no pieces notion, case C2). ``pieces`` of a pack_size line is the sum of
the missing pieces. So, for every look: the units of the flagged lines add up to the number of distinct flagged
instances, and the pack_size pieces equal minus the pieces difference over the unflagged short packs (property
test tests/property/test_m5_claim_lines_property.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REASONS = ("damaged", "expired", "near_expiry", "short", "pack_size")
FLAG_REASONS = frozenset({"damaged", "expired", "near_expiry"})


@dataclass(frozen=True)
class ClaimLine:
    reason: str
    units: int
    pieces: int
    n: tuple[int, ...] = field(default=())  # the look's instance numbers on this line (none for "short")

    def api(self) -> dict[str, Any]:
        return {"reason": self.reason, "units": self.units, "pieces": self.pieces}

    def stored(self) -> dict[str, Any]:
        return {**self.api(), "n": list(self.n)}


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def _dicts(v: Any) -> list[dict[str, Any]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def expected_pieces_per_unit(look: dict[str, Any]) -> int | None:
    pack = look.get("pack")
    if not isinstance(pack, dict):
        return None
    ppu = _int(pack.get("expected_pieces_per_unit"))
    return ppu if ppu is not None and ppu > 0 else None


def flagged_instances(look: dict[str, Any]) -> dict[int, str]:
    """``n`` -> the flag reason (damaged, expired, near_expiry) for every flagged instance of the look."""
    out: dict[int, str] = {}
    for inst in _dicts(look.get("instances")):
        n = _int(inst.get("n"))
        if n is not None and n > 0 and inst.get("damaged") is True:
            out[n] = "damaged"
    expiry = look.get("expiry")
    flagged = _dicts(expiry.get("flagged")) if isinstance(expiry, dict) else []
    for kind in ("expired", "near_expiry"):
        for f in flagged:
            n = _int(f.get("n"))
            reason = "expired" if f.get("reason") == "expired" else "near_expiry"
            if n is not None and n > 0 and reason == kind and n not in out:
                out[n] = kind
    return out


def short_packs(look: dict[str, Any], flagged: dict[int, str] | None = None) -> dict[int, int]:
    """``n`` -> missing pieces, for every unflagged pack that holds fewer pieces than expected."""
    ppu = expected_pieces_per_unit(look)
    pack = look.get("pack")
    if ppu is None or not isinstance(pack, dict):
        return {}
    skip = flagged if flagged is not None else flagged_instances(look)
    out: dict[int, int] = {}
    for m in _dicts(pack.get("mismatches")):
        n, got = _int(m.get("n")), _int(m.get("pieces_per_unit"))
        if n is None or n <= 0 or got is None or got < 0 or n in skip or n in out:
            continue
        if got < ppu:
            out[n] = ppu - got
    return out


def claim_lines(look: dict[str, Any]) -> list[ClaimLine]:
    """The claim lines of a look, in the fixed order of REASONS; lines with nothing to claim are left out."""
    ppu = expected_pieces_per_unit(look) or 0
    flagged = flagged_instances(look)
    lines: list[ClaimLine] = []
    for reason in ("damaged", "expired", "near_expiry"):
        ns = tuple(sorted(n for n, r in flagged.items() if r == reason))
        if ns:
            lines.append(ClaimLine(reason, len(ns), len(ns) * ppu, ns))
    raw_counts = look.get("counts")
    counts: dict[str, Any] = raw_counts if isinstance(raw_counts, dict) else {}
    expected, seen = _int(counts.get("expected")), _int(counts.get("seen"))
    if expected is not None and seen is not None and 0 <= seen < expected:
        units = expected - seen
        lines.append(ClaimLine("short", units, units * ppu))
    packs = short_packs(look, flagged)
    if packs:
        lines.append(ClaimLine("pack_size", len(packs), sum(packs.values()), tuple(sorted(packs))))
    return lines


def lines_from_stored(raw: Any) -> list[ClaimLine]:
    out: list[ClaimLine] = []
    for d in _dicts(raw):
        reason, units, pieces = d.get("reason"), _int(d.get("units")), _int(d.get("pieces"))
        if reason in REASONS and units is not None and pieces is not None:
            ns = tuple(n for n in (_int(x) for x in (d.get("n") or [])) if n is not None)
            out.append(ClaimLine(str(reason), units, pieces, ns))
    return out


def window_days(look: dict[str, Any]) -> int | None:
    expiry = look.get("expiry")
    return _int(expiry.get("window_days")) if isinstance(expiry, dict) else None
