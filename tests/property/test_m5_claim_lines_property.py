"""M5-X02 property: claim lines are a deterministic function of the look, and their totals equal the look's flagged
units and its pieces difference (docs/design/M5_CONTRACT.md sections 2 and 3; field_api/claims/lines.py).

The generator builds looks the way stream V's section 2 response describes them: numbered instances (damaged or
not, a read label with pieces per unit), a pack line with the mismatching packs and ``pieces_difference``
(sum of actual - expected pieces over the mismatches), an expiry line with the flagged boxes, counts and the
proposal (``flag`` = the distinct damaged or expiry-flagged instances).
"""

from __future__ import annotations

import random
from typing import Any

from field_api.briefs import numbers
from field_api.claims.lines import FLAG_REASONS, REASONS, claim_lines
from field_api.claims.text import template_text
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@st.composite
def looks(draw: st.DrawFn) -> dict[str, Any]:
    seen = draw(st.integers(min_value=0, max_value=30))
    expected = draw(st.integers(min_value=max(1, seen - 5), max_value=seen + 8))
    ns = list(range(1, seen + 1))
    damaged = set(draw(st.lists(st.sampled_from(ns), unique=True))) if ns else set()
    ppu = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=24)))
    mism: dict[int, int] = {}
    if ppu is not None and ns:
        for n in draw(st.lists(st.sampled_from(ns), unique=True)):
            got = draw(st.integers(min_value=0, max_value=ppu + 6).filter(lambda g, p=ppu: g != p))
            mism[n] = got
    flagged_exp = []
    if ns and draw(st.booleans()):
        for n in draw(st.lists(st.sampled_from(ns), unique=True)):
            flagged_exp.append({"n": n, "expiry": "2026-12", "reason": draw(st.sampled_from(["near", "expired"]))})
    flag_n = damaged | {f["n"] for f in flagged_exp}
    instances = [{"n": n, "box": [0, 0, 10, 10], "polygon": None, "score": 0.9, "damaged": n in damaged,
                  "damage_note": None, "label": {"read": True, "pieces_per_unit": mism.get(n, ppu), "batch": None,
                                                 "expiry": None, "raw": ""}} for n in ns]
    return {
        "look_id": "l", "source": "model", "image": {"capture_id": None, "width": 100, "height": 100},
        "instances": instances,
        "counts": {"expected": expected, "seen": seen, "damaged": len(damaged), "good": seen - len(flag_n)},
        "pack": None if ppu is None else {"expected_pieces_per_unit": ppu,
                                          "mismatches": [{"n": n, "pieces_per_unit": p} for n, p in mism.items()],
                                          "pieces_difference": sum(p - ppu for p in mism.values())},
        "expiry": {"window_days": 90, "flagged": flagged_exp, "batches": []} if flagged_exp else None,
        "proposal": {"receive": seen - len(flag_n), "flag": len(flag_n), "reasons": []},
        "say": "", "models": [], "reasons": [],
    }


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(looks(), st.randoms(use_true_random=False))
def test_m5_x02_claim_line_totals_property(look: dict[str, Any], rnd: random.Random) -> None:
    """M5-X02: totals of the claim lines equal the look's flagged units and pieces difference."""
    lines = claim_lines(look)
    by = {ln.reason: ln for ln in lines}
    # fixed order, one line per reason, nothing empty
    assert [ln.reason for ln in lines] == [r for r in REASONS if r in by]
    assert all(ln.units >= 1 and ln.pieces >= 0 for ln in lines)
    # flagged units: claimed whole, once each, = the proposal's flag
    assert sum(ln.units for ln in lines if ln.reason in FLAG_REASONS) == look["proposal"]["flag"]
    flagged_ns = [n for ln in lines if ln.reason in FLAG_REASONS for n in ln.n]
    assert len(flagged_ns) == len(set(flagged_ns))
    # pieces: the pack_size line is minus the pieces difference over the unflagged packs that hold fewer pieces
    pack = look["pack"]
    if pack is not None:
        ppu = pack["expected_pieces_per_unit"]
        unflagged_short = [m for m in pack["mismatches"] if m["n"] not in set(flagged_ns) and m["pieces_per_unit"] < ppu]
        expected_pieces = -sum(m["pieces_per_unit"] - ppu for m in unflagged_short)
        assert (by["pack_size"].pieces if "pack_size" in by else 0) == expected_pieces
        assert (by["pack_size"].units if "pack_size" in by else 0) == len(unflagged_short)
        if all(m["pieces_per_unit"] < ppu and m["n"] not in set(flagged_ns) for m in pack["mismatches"]):
            assert (by["pack_size"].pieces if "pack_size" in by else 0) == -pack["pieces_difference"]
        for ln in lines:
            if ln.reason != "pack_size":
                assert ln.pieces == ln.units * ppu
    else:
        assert "pack_size" not in by and all(ln.pieces == 0 for ln in lines)
    # the delivery shortfall
    short = look["counts"]["expected"] - look["counts"]["seen"]
    assert (by["short"].units if "short" in by else 0) == max(0, short)
    # deterministic: the order of instances, mismatches and expiry flags does not matter
    shuffled = {**look, "instances": rnd.sample(look["instances"], len(look["instances"]))}
    if pack is not None:
        shuffled["pack"] = {**pack, "mismatches": rnd.sample(pack["mismatches"], len(pack["mismatches"]))}
    if look["expiry"] is not None:
        shuffled["expiry"] = {**look["expiry"], "flagged": rnd.sample(look["expiry"]["flagged"],
                                                                      len(look["expiry"]["flagged"]))}
    assert claim_lines(shuffled) == lines


@settings(max_examples=200, deadline=None)
@given(looks(), st.integers(min_value=1, max_value=50))
def test_m5_x02_template_numbers_property(look: dict[str, Any], bump: int) -> None:
    """M5-X02: the template passes its own number check, and any changed number in a draft is refused."""
    lines = claim_lines(look)
    if not lines:
        return
    pack = look["pack"]
    text = template_text(lines, ppu=pack["expected_pieces_per_unit"] if pack else None, window=90)
    assert numbers.check(text, text) == []
    first = lines[0].units
    new = int(max(numbers.values(text))) + bump  # a number the template does not hold
    changed = text.replace(f": {first} ", f": {new} ", 1)
    assert changed != text
    assert f"local:number_not_in_template:{new}" in numbers.check(changed, text)
