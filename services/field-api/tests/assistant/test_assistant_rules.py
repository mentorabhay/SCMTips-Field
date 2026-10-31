"""Field Assistant rules mode (M3 contract §4, ``ai: "rules"``): AI off, no network, real Postgres with RLS.

Intents: greeting + work list, "what do we have", most urgent, start <type or number>, what's next, how many left,
what is this (code lookup), the sandbox unknown-code dialog, summary, repeat, help, done, pause/resume/end.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.assistant.ports import AssistantPorts, CodeLookup, SandboxItemResult, get_ports
from field_api.assistant.rules import SKIP, clean_name, intent, is_yes, parse_quantity
from field_api.auth.jwt import Principal
from field_api.errors import FieldError

pytestmark = pytest.mark.unit
api = TestClient(app)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture(autouse=True)
def ai_off(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    yield
    app.dependency_overrides.pop(get_ports, None)


def turn(s: dict[str, Any], event: str, token: str | None = None, **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"site_id": s["site"], "event": event, "session_id": kw.pop("session_id", None)}
    task_id = kw.pop("task_id", None)
    body["client_state"] = {"task_id": task_id, "line_id": None, "step": None}
    body.update(kw)
    r = api.post("/v1/assistant/turns", json=body, headers=_h(token or s["op"]))
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    assert out["ai"] == "rules" and out["cost_usd"] == 0.0
    assert set(out) == {"session_id", "say", "card", "actions", "ai", "cost_usd"}
    assert set(out["card"]) == {"title", "body"}
    return out


# ---------------------------------------------------------------- pure parsing
@pytest.mark.parametrize(("text", "want"), [
    ("what do we have today", "work"), ("what's most urgent", "urgent"), ("start receipt", "start"),
    ("start 1800000022", "start"), ("what's next", "next"), ("how many left", "left"), ("what is this", "what_is"),
    ("summary", "summary"), ("repeat", "repeat"), ("help", "help"), ("confirm", "confirm"), ("post it", "post"),
    ("cancel", "cancel"), ("count four", "count"), ("hello", "greet"), ("when am I done", "done_def"),
    ("blue elephants", "unknown"),
])
def test_intents(text: str, want: str) -> None:
    assert intent(text)[0] == want


def test_quantities_names_and_yes() -> None:
    assert parse_quantity("twenty five") == Decimal(25)
    assert parse_quantity("4") == Decimal(4)
    assert parse_quantity("2,5 boxes") == Decimal("2.5")
    assert parse_quantity("a dozen") == Decimal(12)
    assert parse_quantity("one hundred and two") == Decimal(102)
    assert parse_quantity("skip") == SKIP
    assert parse_quantity("lots") is None
    assert clean_name("It's a blue coffee mug.") == "blue coffee mug"
    assert is_yes("yes please") and is_yes("add it") and not is_yes("yes, no wait") and not is_yes("no")


# ---------------------------------------------------------------- endpoint
def test_greeting_lists_work_most_urgent_first(site: dict[str, Any]) -> None:
    r = turn(site, "session_start")
    assert "2 jobs" in r["say"] and "1 receipt" in r["say"] and "1 count" in r["say"]
    assert "Count bin 03-05-02" in r["say"]  # high priority before medium
    assert r["say"].count(".") <= 2
    assert {"type": "listen", "mode": "command"} in r["actions"]
    r2 = turn(site, "utterance", text="what do we have today", session_id=r["session_id"])
    assert r2["session_id"] == r["session_id"] and "2 jobs" in r2["say"]
    assert "Delivery 1800000022" in r2["card"]["body"]


def test_start_by_type_and_number_opens_the_task(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "utterance", text="start receipt", session_id=sid)
    assert r["actions"] == [{"type": "open_task", "task_id": site["receive"]}]
    assert "Delivery 1800000022" in r["say"] and "post" in r["say"]
    r = turn(site, "utterance", text="start 22", session_id=sid)
    assert r["actions"] == [{"type": "open_task", "task_id": site["receive"]}]
    r = turn(site, "utterance", text="start the count", session_id=sid)
    assert r["actions"] == [{"type": "open_task", "task_id": site["count"]}]
    r = turn(site, "utterance", text="start swap", session_id=sid)
    assert not [a for a in r["actions"] if a["type"] == "open_task"] and "no open swap" in r["say"]


def test_next_and_left_on_receive_say_quantities(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "utterance", text="what's next", session_id=sid, task_id=site["receive"])
    assert "Steel bolt M8" in r["say"] and "24" in r["say"]
    r = turn(site, "utterance", text="how many left", session_id=sid, task_id=site["receive"])
    assert r["say"].startswith("2 of 2 lines left") and "36 pieces" in r["say"]


def test_count_task_never_says_the_book_quantity(site: dict[str, Any], h: SimpleNamespace) -> None:
    sid = turn(site, "session_start")["session_id"]
    for text in ("what's next", "how many left", "when am I done", "what is this", "summary", "post"):
        r = turn(site, "utterance", text=text, session_id=sid, task_id=site["count"])
        assert "7777" not in r["say"] and "7777" not in r["card"]["body"], text
    r = turn(site, "utterance", text="what's next", session_id=sid, task_id=site["count"])
    assert "03-05-02" in r["say"] and "Count what you see" in r["say"]
    r = turn(site, "step_done", session_id=sid, task_id=site["count"])
    assert "7777" not in r["say"]


def test_what_is_this_from_task_lines_when_codes_port_is_not_wired(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "utterance", text="what is this", code="MAT-NUT", session_id=sid, task_id=site["receive"])
    assert r["say"] == "That's Hex nut M8. It's line 20 of this job."
    assert r["actions"] == [{"type": "refresh_task", "task_id": site["receive"], "focus_code": "MAT-NUT"}]
    r = turn(site, "scan", code="03-05-02", session_id=sid)
    assert "bin 03-05-02" in r["say"] and "Count bin 03-05-02" in r["say"]
    r = turn(site, "utterance", text="what is this", session_id=sid)
    assert "barcode" in r["say"]
    r = turn(site, "unknown_code", code="4006381333931", session_id=sid, task_id=site["receive"])
    assert "sandbox" in r["say"] and r["actions"] == []  # production site: no add offered


def test_confirm_is_never_an_action_and_post_is_a_command(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "utterance", text="confirm", session_id=sid, task_id=site["receive"])
    assert r["actions"] == [] and "confirm" in r["say"].lower()
    r = turn(site, "utterance", text="post it", session_id=sid, task_id=site["receive"])
    assert r["actions"] == [{"type": "command", "command": "post"}]
    r = turn(site, "utterance", text="post", session_id=sid, task_id=site["count"])
    assert r["actions"] == [] and "still open" in r["say"]  # count lines not counted yet


def test_repeat_summary_pause_resume_and_end(site: dict[str, Any]) -> None:
    first = turn(site, "session_start")
    sid = first["session_id"]
    assert turn(site, "utterance", text="say that again", session_id=sid)["say"] == first["say"]
    assert turn(site, "pause", session_id=sid)["say"].startswith("Paused")
    assert turn(site, "resume", session_id=sid)["say"].startswith("Welcome back")
    assert "0 of 0 jobs" in turn(site, "utterance", text="summary", session_id=sid)["say"]
    end = turn(site, "session_end", session_id=sid)
    assert end["say"].startswith("Session ended")
    r = api.post("/v1/assistant/turns", json={"site_id": site["site"], "event": "utterance", "text": "hi",
                                              "session_id": sid}, headers=_h(site["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-AST-409-SESSION-ENDED"


def test_unknown_utterance_and_help(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "utterance", text="blue elephants", session_id=sid)
    assert "didn't catch" in r["say"]
    assert "what's next" in turn(site, "utterance", text="help", session_id=sid)["say"]


# ---------------------------------------------------------------- sandbox dialog through the ports
class Ports:
    """Doubles of track S's resolve_code / add_item (contract §7 signatures)."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.added: list[tuple[str, str, str, Decimal | None, str]] = []

    def resolve_code(self, principal: Principal, site_id: str, code: str) -> CodeLookup:
        return {"code": code, "kind": "unknown", "material": None, "bin": None, "site_mode": self.mode}

    def add_item(self, principal: Principal, task_id: str, code: str, description: str, qty: Decimal | None,
                 idempotency_key: str) -> SandboxItemResult:
        if self.mode != "sandbox":
            raise FieldError(status=403, code="FIELD-SBX-403-PRODUCTION", title="Not on a production site")
        self.added.append((task_id, code, description, qty, idempotency_key))
        return {"line_id": str(uuid.uuid4()), "material": "HOME-0001", "created_material": True}


def test_sandbox_unknown_code_dialog_name_then_quantity_then_add(site: dict[str, Any], h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    ports = Ports("sandbox")
    app.dependency_overrides[get_ports] = lambda: AssistantPorts(ports.resolve_code, ports.add_item)
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "unknown_code", code="4006381333931", session_id=sid, task_id=site["receive"])
    assert r["say"].endswith("What is it?") and r["actions"] == [{"type": "listen", "mode": "free"}]
    r = turn(site, "utterance", text="it's a blue coffee mug", session_id=sid, task_id=site["receive"])
    assert r["say"] == "Blue coffee mug. How many?"
    r = turn(site, "utterance", text="lots", session_id=sid, task_id=site["receive"])
    assert "Say a number" in r["say"] and not ports.added
    r = turn(site, "utterance", text="four", session_id=sid, task_id=site["receive"])
    assert r["say"] == "Added blue coffee mug, 4."
    assert r["actions"] == [{"type": "refresh_task", "task_id": site["receive"], "focus_code": "4006381333931"}]
    assert len(ports.added) == 1
    task_id, code, desc, qty, key = ports.added[0]
    assert (task_id, code, desc, qty) == (site["receive"], "4006381333931", "blue coffee mug", Decimal(4))
    assert key.endswith(":sandbox-item")
    r = turn(site, "utterance", text="yes", session_id=sid, task_id=site["receive"])  # dialog closed: nothing added
    assert len(ports.added) == 1


def test_sandbox_dialog_cancel_and_not_wired(site: dict[str, Any], h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "unknown_code", code="999000111", session_id=sid, task_id=site["receive"])
    assert "can't add items in this build" in r["say"]  # ports not wired on this branch
    ports = Ports("sandbox")
    app.dependency_overrides[get_ports] = lambda: AssistantPorts(ports.resolve_code, ports.add_item)
    turn(site, "unknown_code", code="999000111", session_id=sid, task_id=site["receive"])
    r = turn(site, "utterance", text="cancel", session_id=sid, task_id=site["receive"])
    assert r["say"] == "OK, not added." and not ports.added
    r = turn(site, "unknown_code", code="999000111", session_id=sid)  # no job open
    assert "Open a receipt or a count first" in r["say"]


def test_production_site_refuses_the_sandbox_dialog(site: dict[str, Any]) -> None:
    ports = Ports("production")
    app.dependency_overrides[get_ports] = lambda: AssistantPorts(ports.resolve_code, ports.add_item)
    sid = turn(site, "session_start")["session_id"]
    r = turn(site, "unknown_code", code="4006381333931", session_id=sid, task_id=site["receive"])
    assert "sandbox site" in r["say"] and not ports.added


# ---------------------------------------------------------------- request rules
def test_permissions_scope_and_idempotency(site: dict[str, Any]) -> None:
    body = {"site_id": site["site"], "event": "session_start"}
    r = api.post("/v1/assistant/turns", json=body, headers=_h(site["viewer"]))
    assert r.status_code == 403
    assert api.post("/v1/assistant/turns", json=body).status_code == 401
    for role in ("tech", "sup"):
        assert api.post("/v1/assistant/turns", json=body, headers=_h(site[role])).status_code == 200
    other = api.post("/v1/assistant/turns", json={**body, "site_id": str(uuid.uuid4())}, headers=_h(site["op"]))
    assert other.status_code == 403  # not in the token's sites
    r = api.post("/v1/assistant/turns", json=body,
                 headers={"Authorization": f"Bearer {site['op']}", "X-Test-Omit-Idempotency-Key": "1"})
    assert r.status_code == 400 and r.json()["code"] == "FIELD-IDEM-400-MISSING-KEY"
    hdr = _h(site["op"])
    a = api.post("/v1/assistant/turns", json=body, headers=hdr)
    b = api.post("/v1/assistant/turns", json=body, headers=hdr)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert b.headers.get("Idempotent-Replayed") == "true"
    r = api.post("/v1/assistant/turns", json={**body, "event": "dance"}, headers=_h(site["op"]))
    assert r.status_code == 422


def test_session_belongs_to_its_operator(site: dict[str, Any]) -> None:
    sid = turn(site, "session_start")["session_id"]
    r = api.post("/v1/assistant/turns", json={"site_id": site["site"], "event": "utterance", "text": "hi",
                                              "session_id": sid}, headers=_h(site["op2"]))
    assert r.status_code == 404
