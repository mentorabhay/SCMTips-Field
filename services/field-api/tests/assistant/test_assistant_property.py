"""Field Assistant invariants (Hypothesis), M3 contract §4:

- no response ever contains a confirm action, whatever the model or rules propose;
- count tasks never leak book / expected / counted quantities, in task data or in anything rules mode says;
- spoken text is at most two sentences.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from field_api.assistant.actions import COMMANDS, sanitize
from field_api.assistant.ports import AssistantPorts
from field_api.assistant.prompts import MAX_SAY_CHARS, clip_say
from field_api.assistant.rules import INTENTS, RulesEngine
from field_api.assistant.tools import AssistantTools, TurnContext
from field_api.assistant.work import LINE_FIELDS, project_task
from field_api.auth.jwt import Principal
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.property

json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-10**6, 10**7), st.floats(allow_nan=True),
                      st.text(max_size=20), st.sampled_from(["confirm", "post", "CONFIRM_POST", "yes post", "next"]))
json_value = st.recursive(json_leaf, lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=8), c,
                                                                                          max_size=3), max_leaves=8)
task_id = st.uuids().map(str)
action = st.one_of(
    st.fixed_dictionaries({"type": st.sampled_from(["open_task", "refresh_task", "confirm", "post_confirm"]),
                           "task_id": task_id}, optional={"focus_code": st.text(max_size=12), "x": json_value}),
    st.fixed_dictionaries({"type": st.just("command"),
                           "command": st.sampled_from([*sorted(COMMANDS), "confirm", "approve", "Confirm"])},
                          optional={"value": json_value}),
    st.fixed_dictionaries({"type": st.just("listen"), "mode": st.sampled_from(["command", "free", "confirm"])}),
    st.dictionaries(st.text(max_size=8), json_value, max_size=4),
    json_value,
)
ALLOWED_KEYS = {"open_task": {"type", "task_id"}, "refresh_task": {"type", "task_id", "focus_code"},
                "command": {"type", "command", "value"}, "listen": {"type", "mode"}}


@settings(max_examples=400, deadline=None)
@given(st.lists(action, max_size=8))
def test_no_response_ever_contains_a_confirm_action(proposed: list[Any]) -> None:
    out = sanitize(proposed)
    assert len(out) <= 4
    assert "confirm" not in json.dumps(out).lower()
    for a in out:
        assert set(a) <= ALLOWED_KEYS[a["type"]]
        if a["type"] == "command":
            assert a["command"] in COMMANDS and ("value" not in a or a["command"] == "count")


@settings(max_examples=100, deadline=None)
@given(st.lists(action, max_size=6), st.sets(task_id, max_size=3))
def test_actions_only_name_visible_tasks(proposed: list[Any], visible: set[str]) -> None:
    for a in sanitize(proposed, visible):
        assert "task_id" not in a or a["task_id"] in visible


qty = st.one_of(st.integers(1000, 10**6), st.decimals(1000, 10**6, places=3).map(float))
raw_line = st.fixed_dictionaries(
    {"id": task_id, "line_no": st.integers(1, 99), "material": st.text("ABC-0123", min_size=1, max_size=10),
     "description": st.text("abc ", max_size=12), "bin": st.sampled_from(["03-05-02", "02-01-01", None]),
     "status": st.sampled_from(["open", "counted", "done"]), "expected_qty": qty, "counted_qty": qty},
    optional={"book_qty": qty, "difference": qty, "picked_qty": qty, "unit_price": qty})


def _raw_task(ttype: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": ttype, "status": "open", "title": f"{ttype} job", "subtitle": "s",
            "ref_doc_no": "PI-1", "reason": None, "due": None, "priority": "high", "lines": lines}


@settings(max_examples=200, deadline=None)
@given(st.lists(raw_line, min_size=1, max_size=5))
def test_count_tasks_never_leak_book_quantity_in_task_data(lines: list[dict[str, Any]]) -> None:
    out = project_task(_raw_task("count", lines))
    for ln in out["lines"]:
        assert set(ln) <= set(LINE_FIELDS)
    text = json.dumps(out)
    for ln in lines:
        for k in ("expected_qty", "counted_qty", "book_qty", "difference", "picked_qty", "unit_price"):
            if k in ln:
                assert f'"{k}"' not in text
    receive = project_task(_raw_task("receive", lines))
    assert [ln["expected_qty"] for ln in receive["lines"]] == [ln["expected_qty"] for ln in lines]


@dataclass
class OfflineTools(AssistantTools):
    """Rules-mode tools over fixed, projected task data (no database), for the rules properties."""

    tasks: list[dict[str, Any]] | None = None

    def work(self) -> list[dict[str, Any]]:
        return [project_task(t) for t in self.tasks or []]

    def task_detail(self, task_id: str | None) -> dict[str, Any] | None:
        return next((t for t in self.work() if t["id"] == task_id), None)

    def session_summary(self) -> dict[str, Any]:
        return {"turns": 3, "jobs": 1, "jobs_done": 0, "documents": [], "cost_usd": 0.0}


PHRASES = ["what's next", "how many left", "how many should there be", "what is this", "summary", "post",
           "confirm", "yes confirm", "when am I done", "start count", "what do we have", "most urgent", "repeat",
           "count 3", "all here", "cancel", "help", "how much is in the bin", "book quantity please"]
utterance = st.one_of(st.sampled_from(PHRASES), st.text(max_size=40),
                      st.builds(lambda a, b: f"{a} {b}", st.sampled_from(PHRASES), st.text(max_size=10)))
EVENTS = ["utterance", "utterance", "utterance", "scan", "step_done", "resume", "session_start", "photo"]


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(raw_line, min_size=1, max_size=4), st.sampled_from(EVENTS), utterance,
       st.one_of(st.none(), st.sampled_from(["03-05-02", "MAT-1", "UNKNOWN-9"])))
def test_rules_never_confirm_and_never_say_count_quantities(lines: list[dict[str, Any]], event: str, text: str,
                                                            code: str | None) -> None:
    secret = 987654  # the book quantity of every count line
    for ln in lines:
        ln["expected_qty"] = ln["counted_qty"] = ln["book_qty"] = secret
    count = _raw_task("count", lines)
    p = Principal(id="op-1", tenant_id=str(uuid.uuid4()), roles=["field.operator"], permissions=[], site_ids=["*"])
    ctx = TurnContext(principal=p, site_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()), site_mode="production",
                      ports=AssistantPorts(), idempotency_key="k", task_id=count["id"])
    reply = RulesEngine(OfflineTools(ctx, tasks=[count]), last_said="Earlier.").answer(event, text, code, False)
    acts = sanitize(reply.actions)
    assert acts == reply.actions  # rules only ever propose allowed actions
    assert all(a.get("command") != "confirm" for a in acts)
    spoken = clip_say(reply.say)
    for s in (spoken, reply.card["title"], reply.card["body"]):
        assert str(secret) not in s.replace(",", "").replace(" ", "")


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=600))
def test_say_is_at_most_two_sentences(text: str) -> None:
    out = clip_say(text)
    assert len(out) <= MAX_SAY_CHARS + 1
    assert len([p for p in re.split(r"(?<=[.!?])\s+", out) if p]) <= 2


def test_every_intent_rule_compiles() -> None:
    assert all(re.compile(rx) for _n, rx in INTENTS)
