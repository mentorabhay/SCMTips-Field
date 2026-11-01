"""The C3 verdict rule table as properties (M5-T07): docs/design/M5_C3_CONTRACT.md section 3."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from field_api.authenticity import rules
from field_api.authenticity.seal_code import STATUSES
from field_api.briefs import numbers
from hypothesis import given, settings
from hypothesis import strategies as st

EVENT_TYPES = ("manufactured", "shipped_to_seller", "delivered", "activated", "returned", "refurbished")
days = st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 12, 31))
events = st.lists(st.tuples(st.sampled_from(EVENT_TYPES), days), max_size=8)
inputs = st.builds(
    rules.Inputs,
    code=st.sampled_from(STATUSES),
    registry=st.sampled_from(rules.REGISTRY_STATUSES),
    events=events.map(tuple),
    first_check=st.sampled_from(rules.FIRST_CHECK_STATUSES),
    first_checked_at=st.one_of(st.none(), st.datetimes(min_value=datetime(2025, 1, 1), max_value=datetime(2027, 12, 31),
                                                       timezones=st.just(UTC))),
    today=days,
)


@settings(max_examples=400, deadline=None)
@given(i=inputs)
def test_m5_t07_property_rule_table_first_match_wins(i: rules.Inputs) -> None:
    """M5-T07: every input gets exactly the verdict of the first matching rule R1-R14."""
    v = rules.decide(i)
    assert v.verdict in rules.VERDICTS and v.rule
    types = {t for t, _ in i.events}
    if i.code != "valid":
        assert (v.rule, v.verdict) == rules.CODE_RULES[i.code][:2]
        assert v.reasons == (rules.CODE_RULES[i.code][2],)
    elif i.registry != "found":
        assert v.verdict == "CANNOT_VERIFY" and v.rule in ("R8", "R9", "R10")
    elif types & {"returned", "refurbished"}:
        assert (v.rule, v.verdict) == ("R11", "RETURNED_REFURBISHED")
    elif "activated" in types:
        assert (v.rule, v.verdict) == ("R12", "GENUINE_PREVIOUSLY_ACTIVATED")
    elif i.first_check == "other_checker":
        assert (v.rule, v.verdict) == ("R13", "CANNOT_VERIFY")
    else:
        assert (v.rule, v.verdict) == ("R14", "GENUINE_NEW")


@settings(max_examples=400, deadline=None)
@given(i=inputs)
def test_m5_t07_property_genuine_new_only_for_a_clean_verified_unit(i: rules.Inputs) -> None:
    """M5-T07: GENUINE_NEW <=> valid code, unit found, never activated / returned / refurbished, first checker."""
    types = {t for t, _ in i.events}
    clean = (i.code == "valid" and i.registry == "found" and not types & {"activated", "returned", "refurbished"}
             and i.first_check != "other_checker")
    assert (rules.decide(i).verdict == "GENUINE_NEW") == clean
    # a counterfeit verdict comes from the signature alone: never from the registry or the first check
    if rules.decide(i).verdict == "LIKELY_COUNTERFEIT":
        assert i.code in ("unknown_key", "bad_signature")


@settings(max_examples=400, deadline=None)
@given(i=inputs)
def test_m5_t07_property_every_spoken_number_comes_from_the_facts(i: rules.Inputs) -> None:
    """M5-T07: the numbers of ``say`` (and of the visual sentence) are a subset of the facts' numbers."""
    v = rules.decide(i)
    said = numbers.values(v.say)
    facts = numbers.values(rules.facts_text(i))
    assert said <= facts, (v.say, rules.facts_text(i))
    assert not numbers.values(rules.visual_sentence(rules.SIGNS))


@given(status=st.sampled_from(("done", "failed", "pending", "none")), found=st.one_of(st.none(), st.booleans()),
       signs=st.lists(st.sampled_from(rules.SIGNS), unique=True, max_size=5))
def test_m5_t07_property_tamper_only_from_a_finished_visual_check(status: str, found: bool | None,
                                                                  signs: list[str]) -> None:
    """M5-T07: tamper is True only with a reported sign, False only for a seen seal without signs, else None."""
    t = rules.tamper_of(status, found, signs)
    if status != "done":
        assert t is None
    elif signs:
        assert t is True and rules.visual_sentence(signs).startswith("The seal shows ")
    else:
        assert t is (False if found else None)


def test_m5_t07_rules_contract_examples() -> None:
    today = date(2026, 11, 1)
    shipped = (("manufactured", date(2026, 9, 28)), ("shipped_to_seller", date(2026, 10, 2)))
    v = rules.decide(rules.Inputs("valid", "found", (*shipped, ("activated", date(2026, 10, 12)),
                                                     ("returned", date(2026, 10, 20))), "first", None, today))
    assert v.say == ("Code is genuine. But this unit was activated on 12 October and returned on 20 October. "
                     "It is not a new unit.")
    assert rules.visual_sentence(["tape_over_seal"]) == "The seal shows tape over the original."
    assert rules.visual_sentence(["seal_torn", "tape_over_seal"]) == "The seal shows tape over the original and a torn seal."
    first = datetime(2025, 12, 30, 9, tzinfo=UTC)
    same = rules.decide(rules.Inputs("valid", "found", shipped, "same_checker", first, today))
    assert same.say.endswith("You first checked it on 30 December 2025.")
    other = rules.decide(rules.Inputs("valid", "found", shipped, "other_checker", first, today))
    assert other.say.startswith("Code is genuine, but it was first checked on 30 December 2025 by someone else.")
    assert rules.decide(rules.Inputs("valid", "found", (("manufactured", today),), "first", None,
                                     today)).reasons == ("history:not_shipped",)
    refurb = rules.decide(rules.Inputs("valid", "found", (("refurbished", today - timedelta(days=3)),), today=today))
    assert refurb.say == "Code is genuine. But this unit was refurbished on 29 October. It is not a new unit."
