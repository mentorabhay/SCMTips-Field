"""The deterministic check of a look (vision.reconcile, M5-V04): Hypothesis properties and the say number check."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from field_api.briefs.numbers import values
from field_api.vision.reconcile import Expectation, Seen, expiry_date, expiry_status, reconcile
from field_api.vision.say import RULES_SAY, allowed_numbers, compose, say_for
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.property

TODAY = date(2026, 11, 1)
expiries = st.one_of(st.none(), st.dates(date(2025, 1, 1), date(2028, 12, 31)).map(lambda d: d.isoformat()),
                     st.dates(date(2025, 1, 1), date(2028, 12, 31)).map(lambda d: d.strftime("%Y-%m")))


@st.composite
def looks(draw: st.DrawFn) -> tuple[list[Seen], Expectation]:
    n = draw(st.integers(0, 40))
    seen = [Seen(i, damaged=draw(st.booleans()), read=draw(st.booleans()),
                 pieces_per_unit=draw(st.one_of(st.none(), st.integers(1, 48))),
                 batch=draw(st.sampled_from([None, "B1", "B2", "LOT-9"])), expiry=draw(expiries))
            for i in range(1, n + 1)]
    case = draw(st.sampled_from(["grocery", "pharmacy", "generic"]))
    exp = Expectation(case=case, object_noun=draw(st.sampled_from(["pack", "box", "item"])),
                      expected_units=draw(st.one_of(st.none(), st.integers(0, 40))),
                      expected_pieces_per_unit=draw(st.one_of(st.none(), st.integers(1, 48))),
                      window_days=draw(st.integers(0, 365)))
    return seen, exp


@settings(max_examples=300, deadline=None)
@given(looks())
def test_m5_v04_property_good_plus_flagged_is_seen_and_pieces_difference(case: tuple[list[Seen], Expectation]) -> None:
    """M5-V04: good + flagged = seen; pieces difference = sum of read pieces - expected x reads; flagged = damaged
    (plus expired/near on a pharmacy case); mismatches are exactly the reads that differ; say's numbers are the
    look's own."""
    seen, exp = case
    c = reconcile(seen, exp, TODAY)
    assert c.counts["seen"] == len(seen)
    assert c.proposal["receive"] + c.proposal["flag"] == len(seen)
    assert c.counts["good"] == c.proposal["receive"] and c.counts["good"] + len(c.flagged) == len(seen)
    damaged = {s.n for s in seen if s.damaged}
    assert damaged <= set(c.flagged)
    if exp.case == "pharmacy":
        dated = {s.n for s in seen if s.read and expiry_status(s.expiry, TODAY, exp.window_days)}
        assert set(c.flagged) == damaged | dated
        assert c.expiry is not None and c.expiry["batches"] == sorted({s.batch for s in seen if s.read and s.batch})
    else:
        assert set(c.flagged) == damaged and c.expiry is None
    if exp.expected_pieces_per_unit is None:
        assert c.pack is None
    else:
        reads = [s for s in seen if s.read and s.pieces_per_unit is not None]
        e = exp.expected_pieces_per_unit
        assert c.pack is not None
        assert c.pack["pieces_difference"] == (sum(s.pieces_per_unit or 0 for s in reads) - e * len(reads)
                                               if reads else None)
        assert [m["n"] for m in c.pack["mismatches"]] == [s.n for s in reads if s.pieces_per_unit != e]
        assert sum(diff for _k, _v, diff in c.pack_groups) == (c.pack["pieces_difference"] or 0)
    say = say_for(c, exp)
    assert values(say) <= allowed_numbers(c, exp)
    assert say == compose(c, exp)  # the full sentence always passes its own number check (no fallback needed)


@given(st.dates(date(2024, 1, 1), date(2030, 12, 31)), st.integers(0, 400))
def test_m5_v04_property_expiry_windows(d: date, window: int) -> None:
    """A day expiry is expired before today and near up to today + window; a month means its last day."""
    status = expiry_status(d.isoformat(), TODAY, window)
    assert status == ("expired" if d < TODAY else "near" if d <= TODAY + timedelta(days=window) else None)
    month_end = expiry_date(d.strftime("%Y-%m"))
    assert month_end is not None and month_end.month == d.month and month_end >= d
    assert (month_end + timedelta(days=1)).day == 1


def test_m5_v04_rules_mode_and_contract_example() -> None:
    """No instances -> nothing counted, nothing proposed; the contract's example reads as its say."""
    exp = Expectation("grocery", "pack", 20, 12)
    rules = reconcile(None, exp, TODAY)
    assert rules.counts == {"expected": 20, "seen": None, "damaged": None, "good": None}
    assert rules.proposal == {"receive": None, "flag": None, "reasons": []} and say_for(rules, exp) == RULES_SAY
    seen = [Seen(n, damaged=n in (3, 9), read=True, pieces_per_unit=10 if n in (7, 8) else 12) for n in range(1, 21)]
    c = reconcile(seen, exp, TODAY)
    assert c.counts == {"expected": 20, "seen": 20, "damaged": 2, "good": 18}
    assert c.pack == {"expected_pieces_per_unit": 12, "pieces_difference": -4,
                      "mismatches": [{"n": 7, "pieces_per_unit": 10}, {"n": 8, "pieces_per_unit": 10}]}
    assert c.proposal == {"receive": 18, "flag": 2, "reasons": ["2 damaged", "2 packs hold 10, not 12: 4 pieces short"]}
    assert say_for(c, exp) == "20 of 20 packs. 2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2?"
    over = reconcile([Seen(1, read=True, pieces_per_unit=13)], Expectation("grocery", "pack", 1, 12), TODAY)
    assert over.proposal["reasons"] == ["1 pack holds 13, not 12: 1 piece over"]
