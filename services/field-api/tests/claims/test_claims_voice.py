"""Supplier claims by voice through the Field Assistant (M5 contract section 4, ledger M5-X06): the rules classify
"make a claim", "claims" / "next claim", "approve" / "reject" and "confirm" themselves; the claims service does
the rest with the same rules as the HTTP API (read-back, 10 s confirm by the same person, simulated send)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.assistant.model import ModelRouter, get_router
from field_api.assistant.ports import AssistantPorts, get_ports
from field_api.claims.voice import ClaimsVoice


@pytest.fixture
def voice(looks: Any, model_router: ModelRouter) -> Iterator[TestClient]:
    app.dependency_overrides[get_ports] = lambda: AssistantPorts(claims=ClaimsVoice(looks=looks, router=model_router))
    app.dependency_overrides[get_router] = lambda: model_router
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_ports, None)
        app.dependency_overrides.pop(get_router, None)


class Talk:
    def __init__(self, client: TestClient, token: str, site: str) -> None:
        self.client, self.token, self.site, self.session = client, token, site, None

    def say(self, text: str, **state: str) -> dict[str, Any]:
        body: dict[str, Any] = {"site_id": self.site, "event": "utterance", "text": text}
        if self.session:
            body["session_id"] = self.session
        if state:
            body["client_state"] = state
        r = self.client.post("/v1/assistant/turns", json=body, headers={"Authorization": f"Bearer {self.token}"})
        assert r.status_code == 200, r.text
        out: dict[str, Any] = r.json()
        self.session = out["session_id"]
        return out


def _status(h: SimpleNamespace, env: dict[str, Any]) -> list[tuple[Any, ...]]:
    return h.admin_sql(env["tenant"], "SELECT status, confirm_words, confirmed_by FROM field.supplier_claim"
                                      " WHERE look_id = %s", (env["look"],))


def test_operator_makes_a_claim_after_a_look(voice: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                             ai_off: None, recorded_api: Any) -> None:
    op = Talk(voice, env["op"], env["site"])
    r = op.say("make a claim")
    assert r["say"] == "Take a look first, then say make a claim." and r["ai"] == "rules"
    r = op.say("make a claim", task_id=env["task"], look_id=env["look"])
    assert r["say"].startswith("Claim drafted for a supervisor. We claim for this delivery: 2 damaged units")
    assert r["ai"] == "rules" and recorded_api.requests == []  # rules classified it; AI off: the template
    assert _status(h, env) == [("draft", None, None)]
    assert op.say("approve")["say"] == "Claims are approved by a supervisor."
    assert op.say("claims")["say"] == "Claims are approved by a supervisor."


def test_supervisor_reads_approves_and_confirms_by_voice(voice: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                         ai_off: None) -> None:
    Talk(voice, env["op"], env["site"]).say("raise a claim", look_id=env["look"])
    sup = Talk(voice, env["sup"], env["site"])
    assert sup.say("approve")["say"] == "Say next claim first, so I know which claim."
    r = sup.say("claims")
    assert r["say"].startswith("Claim 1 of 1; say approve or reject. We claim for this delivery: 2 damaged units")
    assert r["card"]["body"].endswith("The photo and the posting record are attached.")
    r = sup.say("what was that again")  # not a claim word: the dialog stays open
    assert r["say"] == "Say approve or reject, or next claim."
    r = sup.say("approve")
    assert r["say"] == ("Approve the claim for 2 damaged units (24 pieces); 2 packs hold fewer pieces: 4 pieces "
                        "short? Say confirm within 10 seconds.")
    assert all("approve" not in str(a) and "confirm" not in str(a) for a in r["actions"])  # no confirm action, ever
    assert _status(h, env)[0][0] == "pending_confirm"
    r = sup.say("confirm")
    assert r["say"] == "Claim approved. Sending it to the supplier is simulated in this build."
    assert _status(h, env) == [("approved", "confirm", "sup-x")]
    assert h.admin_sql(env["tenant"], "SELECT count(*) FROM field.outbox WHERE event_type = 'claim.sent'"
                                      " AND tenant_id = %s", (env["tenant"],))[0][0] == 1
    assert sup.say("next claim")["say"] == "No claims are waiting."
    # outside a claim dialog "confirm" keeps its M3 meaning
    assert sup.say("confirm")["say"].startswith("Say post first, then confirm on the review step.")


def test_voice_reject_with_reason_next_claim_and_late_confirm(voice: TestClient, env: dict[str, Any],
                                                             h: SimpleNamespace, ai_off: None, looks: Any) -> None:
    second = looks.add(env["tenant"], h.make_look(str(uuid.uuid4()), env["capture"], env["task"], damaged=(5,),
                                                  mismatches={}))
    op = Talk(voice, env["op"], env["site"])
    op.say("make a claim", look_id=env["look"])
    op.say("make a claim", look_id=second)
    sup = Talk(voice, env["sup"], env["site"])
    assert sup.say("next claim")["say"].startswith("Claim 1 of 2;")
    r = sup.say("next claim")
    assert r["say"].startswith("Claim 2 of 2; say approve or reject. We claim for this delivery: 1 damaged unit")
    r = sup.say("reject because the photo is blurred")
    assert r["say"].startswith("Reject the claim for 1 damaged unit (12 pieces), reason the photo is blurred?")
    h.admin_sql(env["tenant"], "UPDATE field.supplier_claim SET decided_at = decided_at - interval '11 seconds',"
                               " confirm_by = confirm_by - interval '11 seconds' WHERE look_id = %s", (second,))
    r = sup.say("confirm")
    assert r["say"] == "Too late to confirm; the claim is waiting again. Say next claim to hear it."
    rows = h.admin_sql(env["tenant"], "SELECT status FROM field.supplier_claim WHERE look_id = %s", (second,))
    assert rows == [("draft",)]
    assert sup.say("claims")["say"].startswith("Claim 1 of 2;")


def test_an_abandoned_decision_is_void_after_10_s(voice: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                  ai_off: None) -> None:
    Talk(voice, env["op"], env["site"]).say("make a claim", look_id=env["look"])
    sup = Talk(voice, env["sup"], env["site"])
    sup.say("claims")
    sup.say("approve")
    other = Talk(voice, env["sup2"], env["site"])
    assert other.say("claims")["say"] == "No claims are waiting."  # one supervisor's decision is pending
    assert other.say("confirm")["say"].startswith("Say post first")  # nothing of theirs to confirm
    assert sup.say("cancel")["say"] == "OK."
    assert _status(h, env)[0][0] == "pending_confirm"
    h.admin_sql(env["tenant"], "UPDATE field.supplier_claim SET decided_at = decided_at - interval '11 seconds',"
                               " confirm_by = confirm_by - interval '11 seconds' WHERE look_id = %s", (env["look"],))
    assert other.say("claims")["say"].startswith("Claim 1 of 1;")  # void after 10 s: a draft again
    assert other.say("approve")["say"].startswith("Approve the claim for")
    assert sup.say("confirm")["say"].startswith("Say post first")  # the first supervisor's dialog ended with cancel
    assert other.say("confirm")["say"].startswith("Claim approved.")
    assert _status(h, env) == [("approved", "confirm", "sup-z")]


def test_claims_not_wired_in_a_build_without_the_port(env: dict[str, Any], ai_off: None) -> None:
    app.dependency_overrides[get_ports] = lambda: AssistantPorts()
    try:
        r = Talk(TestClient(app), env["sup"], env["site"]).say("claims")
    finally:
        app.dependency_overrides.pop(get_ports, None)
    assert r["say"] == "Claims are not available in this build."
