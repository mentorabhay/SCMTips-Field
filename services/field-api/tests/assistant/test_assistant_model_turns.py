"""POST /v1/assistant/turns with the model (M3 contract §4), through the recorded-response double of the API.

What the server guarantees whatever the model answers: no confirm action ever, only visible task ids, two
sentences, count tasks never send book or expected quantities to the model, photos go to the model only for
"what is this" / unknown items, add_sandbox_item only after the operator's explicit yes, and any model failure
falls back to rules for that turn.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.assistant.model import ModelRouter, get_router
from field_api.assistant.ports import AssistantPorts, CodeLookup, SandboxItemResult, get_ports
from field_api.auth.jwt import Principal

pytestmark = pytest.mark.unit
api = TestClient(app)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def wired(ai_on: None, recorded_api: Any, make_router: Callable[..., ModelRouter]) -> Iterator[None]:
    router = make_router()
    app.dependency_overrides[get_router] = lambda: router
    yield
    app.dependency_overrides.pop(get_router, None)
    app.dependency_overrides.pop(get_ports, None)


def turn(s: dict[str, Any], event: str, status: int = 200, **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"site_id": s["site"], "event": event, "session_id": kw.pop("session_id", None),
                            "client_state": {"task_id": kw.pop("task_id", None)}}
    body.update(kw)
    r = api.post("/v1/assistant/turns", json=body,
                 headers={"Authorization": f"Bearer {s['op']}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == status, r.text
    out: dict[str, Any] = r.json()
    return out


def _turn_rows(session_id: str, h: SimpleNamespace, tenant: str) -> list[tuple[Any, ...]]:
    return h.admin_sql(tenant, "SELECT event, ai, said, actions, tool_calls, cost_usd, photo_ref FROM"
                               " field.assistant_turn WHERE session_id = %s ORDER BY at, id", (session_id,))


def test_model_answer_is_sanitised_and_costed(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer({
        "say": "Morning! Two jobs today. The count of bin 03-05-02 is most urgent. Want to start?",
        "card": {"title": "Today", "body": "Count bin 03-05-02\nDelivery 1800000022"},
        "actions": [{"type": "open_task", "task_id": site["count"]},
                    {"type": "command", "command": "confirm"},
                    {"type": "confirm_post", "task_id": site["count"]},
                    {"type": "command", "command": "post", "note": "yes post confirm"},
                    {"type": "open_task", "task_id": str(uuid.uuid4())},
                    {"type": "listen", "mode": "free"}],
    }, prompt=1200, cached=1000, completion=60)]
    r = turn(site, "session_start")
    assert r["ai"] == "model"
    assert r["say"] == "Morning! Two jobs today."  # at most two sentences
    assert r["actions"] == [{"type": "open_task", "task_id": site["count"]}, {"type": "listen", "mode": "free"}]
    want = (Decimal(200) * Decimal("1.25") + Decimal(1000) * Decimal("0.15") + Decimal(60) * Decimal("4.25")) / 10**6
    assert Decimal(str(r["cost_usd"])) == want
    rows = _turn_rows(r["session_id"], h, site["tenant"])
    assert rows[0][0:2] == ("session_start", "model") and Decimal(rows[0][5]) == want
    assert any(c.get("name") == "model_calls" for c in rows[0][4])
    sent = recorded_api.requests[0]
    assert sent["model"] == "muse-spark-1.2" and {t["function"]["name"] for t in sent["tools"]} == {
        "list_work", "task_detail", "lookup_code", "add_sandbox_item", "session_summary"}
    assert "Definition of done" in sent["messages"][0]["content"]


def test_count_task_never_sends_book_quantities_to_the_model(site: dict[str, Any], recorded_api: Any,
                                                             h: SimpleNamespace) -> None:
    recorded_api.script = [
        h.answer(tool_calls=[h.tool_call("task_detail", {"task_id": site["count"]}),
                             h.tool_call("lookup_code", {"code": "MAT-RRU"}),
                             h.tool_call("list_work", {})]),
        h.answer({"say": "Go to bin 03-05-02 and count the radio units.", "actions": []}),
    ]
    r = turn(site, "utterance", text="what do I count here and how many should there be", task_id=site["count"])
    assert r["ai"] == "model" and "03-05-02" in r["say"]
    sent = recorded_api.sent_text()
    assert str(h.BOOK_QTY) not in sent and "7777" not in sent
    tool_msgs = [m for m in recorded_api.requests[1]["messages"] if m["role"] == "tool"]
    detail = json.loads(tool_msgs[0]["content"])
    assert detail["ok"] and detail["task"]["type"] == "count"
    assert all("expected_qty" not in ln and "counted_qty" not in ln for ln in detail["task"]["lines"])
    rows = _turn_rows(r["session_id"], h, site["tenant"])
    assert [c["name"] for c in rows[0][4] if c["name"] != "model_calls"] == ["task_detail", "lookup_code", "list_work"]


def test_receive_task_detail_carries_quantities(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(tool_calls=[h.tool_call("task_detail", {"task_id": site["receive"]})]),
                           h.answer({"say": "24 bolts first.", "actions": []})]
    turn(site, "utterance", text="what's in this delivery", task_id=site["receive"])
    detail = json.loads([m for m in recorded_api.requests[1]["messages"] if m["role"] == "tool"][0]["content"])
    assert [ln["expected_qty"] for ln in detail["task"]["lines"]] == [24.0, 12.0]


def test_photo_goes_to_the_model_only_for_what_is_this(site: dict[str, Any], recorded_api: Any,
                                                       h: SimpleNamespace) -> None:
    photo = base64.b64encode(JPEG).decode()
    recorded_api.script = [h.answer({"say": "Looks like a coffee mug.", "actions": []}),
                           h.answer({"say": "Next is the bolts.", "actions": []})]
    r = turn(site, "utterance", text="what is this", photo_jpeg_b64=photo)
    turn(site, "utterance", text="what's next", photo_jpeg_b64=photo, session_id=r["session_id"])

    def has_image(req: dict[str, Any]) -> bool:
        return any(isinstance(m["content"], list) and any(p.get("type") == "image_url" for p in m["content"])
                   for m in req["messages"])

    assert has_image(recorded_api.requests[0]) and not has_image(recorded_api.requests[1])
    rows = _turn_rows(r["session_id"], h, site["tenant"])
    assert rows[0][6] and rows[0][6].startswith("file://")  # photo kept (30 days) for both turns
    sup = {"Authorization": f"Bearer {site['sup']}"}
    turn_id = api.get(f"/v1/assistant/sessions/{r['session_id']}", headers=sup).json()["turns"][0]["id"]
    img = api.get(f"/v1/assistant/sessions/{r['session_id']}/turns/{turn_id}/photo", headers=sup)
    assert img.status_code == 200 and img.content == JPEG and img.headers["content-type"] == "image/jpeg"


def test_photo_must_be_a_small_jpeg(site: dict[str, Any]) -> None:
    turn(site, "photo", status=422, photo_jpeg_b64=base64.b64encode(b"GIF89a....").decode())
    turn(site, "photo", status=422, photo_jpeg_b64="not base64!!")
    big = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * (1024 * 1024)).decode()
    turn(site, "photo", status=413, photo_jpeg_b64=big)


class Ports:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, str, Decimal | None]] = []

    def resolve_code(self, principal: Principal, site_id: str, code: str) -> CodeLookup:
        return {"code": code, "kind": "unknown", "material": None, "bin": None, "site_mode": "sandbox"}

    def add_item(self, principal: Principal, task_id: str, code: str, description: str, qty: Decimal | None,
                 idempotency_key: str) -> SandboxItemResult:
        self.added.append((task_id, code, description, qty))
        return {"line_id": str(uuid.uuid4()), "material": "HOME-0007", "created_material": True}


def test_add_sandbox_item_needs_the_operators_explicit_yes(site: dict[str, Any], recorded_api: Any,
                                                          h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    ports = Ports()
    app.dependency_overrides[get_ports] = lambda: AssistantPorts(ports.resolve_code, ports.add_item)
    code = "5901234123457"
    add = h.tool_call("add_sandbox_item", {"code": code, "description": "Blue mug", "qty": 4})
    recorded_api.script = [
        h.answer({"say": "Looks like a mug. What is it?", "actions": [{"type": "listen", "mode": "free"}]}),
        h.answer(tool_calls=[add]),  # the model jumps the gun: no yes yet
        h.answer({"say": "Blue mug, four. Shall I add it?", "actions": []}),
        h.answer(tool_calls=[h.tool_call("add_sandbox_item", {"code": "OTHER-CODE", "description": "x", "qty": 1}),
                             add]),
        h.answer({"say": "Added blue mug, four.",
                  "actions": [{"type": "refresh_task", "task_id": site["receive"], "focus_code": code}]}),
    ]
    photo = base64.b64encode(JPEG).decode()
    r = turn(site, "unknown_code", code=code, photo_jpeg_b64=photo, task_id=site["receive"])
    sid = r["session_id"]
    assert r["ai"] == "model" and r["say"].endswith("What is it?")
    r = turn(site, "utterance", text="a blue mug, four of them", session_id=sid, task_id=site["receive"])
    assert ports.added == []
    refused = json.loads([m for m in recorded_api.requests[2]["messages"] if m["role"] == "tool"][-1]["content"])
    assert refused["ok"] is False and "yes" in refused["error"]
    r = turn(site, "utterance", text="yes", session_id=sid, task_id=site["receive"])
    assert ports.added == [(site["receive"], code, "Blue mug", Decimal(4))]  # only the dialog's code
    assert r["actions"] == [{"type": "refresh_task", "task_id": site["receive"], "focus_code": code}]
    recorded_api.script = [h.answer(tool_calls=[add]), h.answer({"say": "Done.", "actions": []})]
    turn(site, "utterance", text="yes", session_id=sid, task_id=site["receive"])  # dialog closed after the add
    assert len(ports.added) == 1


@pytest.mark.parametrize("failure", [500, httpx.ReadTimeout, "garbage"])
def test_model_failure_falls_back_to_rules(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace,
                                          failure: Any) -> None:
    recorded_api.script = [{"choices": []} if failure == "garbage" else failure]
    r = turn(site, "session_start")
    assert r["ai"] == "rules" and "2 jobs" in r["say"]
    rows = _turn_rows(r["session_id"], h, site["tenant"])
    fb = [c for c in rows[0][4] if c["name"] == "fallback"]
    assert fb and fb[0]["reasons"]
    assert h.FAKE_KEY not in json.dumps(rows[0][4])


def test_ai_off_never_calls_the_model(site: dict[str, Any], recorded_api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    r = turn(site, "utterance", text="what do we have today")
    assert r["ai"] == "rules" and r["cost_usd"] == 0.0 and recorded_api.requests == []


def test_plain_text_answer_is_spoken_clipped(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer("Sure. Go to bin 03-05-02. Then count. Then rest.")]
    r = turn(site, "utterance", text="where now")
    assert r["ai"] == "model" and r["say"] == "Sure. Go to bin 03-05-02." and r["actions"] == []


def test_history_reaches_the_model(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer({"say": "Hi there.", "actions": []}), h.answer({"say": "Bolts.", "actions": []})]
    r = turn(site, "utterance", text="hello assistant")
    turn(site, "utterance", text="what next", session_id=r["session_id"])
    msgs = recorded_api.requests[1]["messages"]
    assert any(m["role"] == "user" and "hello assistant" in str(m["content"]) for m in msgs)
    assert any(m["role"] == "assistant" and "Hi there." in str(m["content"]) for m in msgs)


def test_budget_ledger_has_one_settled_row_per_call(site: dict[str, Any], recorded_api: Any,
                                                    h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(tool_calls=[h.tool_call("session_summary", {})]),
                           h.answer({"say": "Nothing done yet.", "actions": []})]
    r = turn(site, "utterance", text="summary")
    admin = os.environ["FIELD_ADMIN_DATABASE_URL"]
    with psycopg.connect(admin) as c, c.cursor() as cur:
        cur.execute("SELECT count(*), sum(cost_usd) FROM ops.ai_usage WHERE tenant_id = %s AND status = 'settled'",
                    (site["tenant"],))
        n, total = cur.fetchone() or (0, 0)
    assert n == 2 and Decimal(str(r["cost_usd"])).quantize(Decimal("0.000001")) == Decimal(total)
