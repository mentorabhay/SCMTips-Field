"""M4-M03: the spoken brief's figures are markers the model cannot change, and field-api runs the core's own
acceptance rule before it asks the core (hosted release scm-1a36ab0-569772d, 2 Nov: the model's brief was refused
by the core with "The figures are not the template's figures in the template's order with their signs").

The core's verdicts in tests/fixtures/core_brief_check_cases.json were made by running the SCMTips core's own
``lr_api.domain.ai.short.accept`` (the core's integration branch 6357b53) over the same templates and candidates; no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from field_api.briefs import core_rule, markers, numbers
from hypothesis import given, settings
from hypothesis import strategies as st

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "core_brief_check_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]

# The spoken template the core builds for a magnet-export-curbs decision (core short.decision_spoken over facts
# shaped like the scenario's: an alternate source, net -$1,908.90, commits $12,480.00, fill 96.4 %, two approvers).
MAGNET = next(c["template"] for c in CASES if c["facts"] == "magnet-risk")


def test_the_shared_fixtures_cover_the_core_refusal_seen_on_the_host() -> None:
    assert len(CASES) >= 60 and FIXTURES.read_text(encoding="utf-8").count("6357b53") == 1
    seen = {c["variant"] for c in CASES if not c["accepted_template_only"]}
    assert {"committed .00 dropped", "net sign dropped", "net minus as word", "committed before net"} <= seen
    assert any(c["accepted_template_only"] for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[f"{c['facts']}:{c['variant']}" for c in CASES])
def test_the_port_agrees_with_the_core_on_shared_fixtures(case: dict[str, Any]) -> None:
    got = core_rule.refusals(case["candidate"], case["template"], "spoken")
    assert got == case["problems_template_only"]
    assert (got == []) == case["accepted_template_only"]
    if not got:  # the template's numbers are a subset of the core's evidence: what the port accepts, the core does
        assert case["accepted_with_facts"]


@pytest.mark.parametrize(("rewrite", "why"), [
    (MAGNET.replace("$12,480.00", "$12,480"), "the cents dropped from the committed amount"),
    (MAGNET.replace("-$1,908.90", "$1,908.90"), "the net's minus sign dropped"),
    (MAGNET.replace("-$1,908.90", "minus $1,908.90"), "the net's minus sign said as a word"),
    (MAGNET.replace("Its net cost against the plan is -$1,908.90. Approving commits $12,480.00.",
                    "Approving commits $12,480.00, for a net cost against the plan of -$1,908.90."),
     "the committed amount moved before the net"),
])
def test_the_hosted_refusal_passes_the_old_local_check_and_fails_the_ported_rule(rewrite: str, why: str) -> None:
    """What the host saw: field-api's value check let the rewrite through, and the core refused it for the order of
    its figures. The ported rule now refuses it first, with the core's own sentence."""
    assert numbers.check(rewrite, MAGNET) == [], why
    assert core_rule.ORDER_PROBLEM in core_rule.refusals(rewrite, MAGNET), why


def test_masking_hides_every_figure_and_unmasking_restores_the_template() -> None:
    m = markers.mask(MAGNET)
    assert m.figures == ("-$1,908.90", "$12,480.00", "96.4 %", "2026-11-14")
    assert not any(ch.isdigit() for ch in m.text.replace("[F1]", "").replace("[F2]", "").replace("[F3]", "")
                   .replace("[F4]", ""))
    assert "is [F1]. Approving commits [F2]. The fill rate would be [F3]. " in m.text
    assert markers.unmask(m.text, m) == (MAGNET, [])
    assert core_rule.refusals(MAGNET, MAGNET) == []


def test_a_fluent_marker_rewrite_becomes_text_the_core_accepts() -> None:
    m = markers.mask(MAGNET)
    reply = ("A decision on export licence checks that hold rare-earth magnet and brushless motor shipments. The "
             "recommended option is the alternate source, with a net cost against the plan of [F1]. Approving "
             "commits [F2], and the fill rate would be [F3]. It is waiting for approval, with a deadline of [F4], "
             "needs two approvers, and approving asks for your second factor.")
    text, unknown = markers.unmask(reply, m)
    assert unknown == [] and "of -$1,908.90. Approving commits $12,480.00, and the fill rate would be 96.4 %." in text
    assert numbers.check(text, MAGNET) == [] and core_rule.refusals(text, MAGNET) == []
    fixture = next(c for c in CASES if c["facts"] == "magnet-risk" and c["variant"] == "fluent same figures")
    assert text == fixture["candidate"] and fixture["accepted_template_only"] and fixture["accepted_with_facts"]


def test_markers_moved_dropped_or_invented_are_refused_locally() -> None:
    m = markers.mask(MAGNET)
    moved = m.text.replace("[F1]", "@").replace("[F2]", "[F1]").replace("@", "[F2]")
    assert core_rule.ORDER_PROBLEM in core_rule.refusals(markers.unmask(moved, m)[0], MAGNET)
    text, unknown = markers.unmask(m.text.replace("[F3]", "[F9]"), m)
    assert unknown == ["local:unknown_marker:F9"] and core_rule.refusals(text, MAGNET)
    assert "local:number_dropped:96.4" in numbers.check(markers.unmask(m.text.replace(" [F3]", ""), m)[0], MAGNET)
    assert markers.unmask("[ f2 ] and [F1]", m)[0] == "$12,480.00 and -$1,908.90"  # spacing and case are forgiven


def test_marker_like_text_in_a_template_is_never_masked() -> None:
    m = markers.mask("Option [F1] costs 42 USD.")
    assert m.figures == () and m.text == "Option [F1] costs 42 USD."


def test_codes_dates_and_percent_signs_stay_inside_their_marker() -> None:
    t = "Motors CP-204 for FG-100 (2806 KV): 12.5 % by week 14, 2026-11-14; cost -₹12,34,567.50."
    m = markers.mask(t)
    assert m.figures == ("CP-204", "FG-100", "2806", "12.5 %", "14", "2026-11-14", "-₹12,34,567.50")
    assert m.text == "Motors [F1] for [F2] ([F3] KV): [F4] by week [F5], [F6]; cost [F7]."
    assert markers.unmask(m.text, m)[0] == t


_money = st.builds(lambda neg, n, c: ("-" if neg else "") + f"${n:,}.{c:02d}", st.booleans(),
                   st.integers(0, 10**7), st.integers(0, 99))
_pct = st.builds(lambda n: f"{n / 10:.1f} %", st.integers(0, 1000))
_date = st.builds(lambda y, mo, d: f"{y}-{mo:02d}-{d:02d}", st.integers(2025, 2030), st.integers(1, 12),
                  st.integers(1, 28))


@settings(max_examples=150, deadline=None)
@given(net=_money, committed=_money, fill=_pct, due=_date)
def test_unmasked_markers_always_give_back_the_template_and_pass_the_core_rule(net: str, committed: str, fill: str,
                                                                                due: str) -> None:
    t = (f"A decision: Response to: Port closed. The recommended option is the reroute. Its net cost against the "
         f"plan is {net}. Approving commits {committed}. The fill rate would be {fill}. It is waiting for approval, "
         f"with a deadline of {due}. It needs two approvers.")
    m = markers.mask(t)
    assert m.figures == (net, committed, fill, due)
    assert markers.unmask(m.text, m) == (t, [])
    assert core_rule.refusals(t, t) == []
    # any swap of two different figures' markers is refused by the ported rule
    if net.lstrip("-") != committed.lstrip("-"):
        swapped = m.text.replace("[F1]", "@").replace("[F2]", "[F1]").replace("@", "[F2]")
        assert core_rule.refusals(markers.unmask(swapped, m)[0], t)
