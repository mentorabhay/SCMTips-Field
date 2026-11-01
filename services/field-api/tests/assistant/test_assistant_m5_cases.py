"""M5 test-case starters by voice (docs/design/M5_CONTRACT.md §1, M5-V07): "new grocery delivery" / "new pharmacy
delivery" are answered by rules (no model call), create the case receipt through the sandbox port and open it; a
production site refuses politely; a build without the port does not offer them."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.assistant.model import ModelRouter, get_router
from field_api.assistant.ports import AssistantPorts, SandboxCaseResult, get_ports
from field_api.assistant.rules import intent
from field_api.auth.jwt import Principal

pytestmark = pytest.mark.unit
api = TestClient(app)


@pytest.fixture(autouse=True)
def wired(ai_on: None, make_router: Callable[..., ModelRouter]) -> Iterator[None]:
    router = make_router()
    app.dependency_overrides[get_router] = lambda: router
    yield
    app.dependency_overrides.pop(get_router, None)
    app.dependency_overrides.pop(get_ports, None)


def _turn(s: dict[str, Any], text: str) -> dict[str, Any]:
    r = api.post("/v1/assistant/turns", json={"site_id": s["site"], "event": "utterance", "text": text,
                                              "client_state": {"task_id": None}},
                 headers={"Authorization": f"Bearer {s['op']}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return dict(r.json())


@pytest.mark.parametrize(("text", "arg"), [
    ("new grocery delivery", "grocery"), ("start a new grocery delivery", "grocery"),
    ("new pharmacy delivery", "pharmacy"), ("create a pharmacy receipt", "pharmacy"),
    ("open a new medicine delivery", "medicine"),
])
def test_m5_v07_case_intents(text: str, arg: str) -> None:
    assert intent(text) == ("new_case", arg)


def test_m5_v07_new_home_receipt_is_still_the_m4_intent() -> None:
    assert intent("new home receipt") == ("new_receipt", "") and intent("new delivery")[0] == "unknown"


def test_m5_v07_voice_starters_create_and_open_the_case(site: dict[str, Any], recorded_api: Any,
                                                        h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    made: list[str] = []

    def create_case(principal: Principal, site_id: str, case: str) -> SandboxCaseResult:
        made.append(case)
        tid = str(h.admin_sql(site["tenant"], "INSERT INTO field.task (tenant_id, site_id, type, status, priority,"
                                              " title, ref_doc_no) VALUES (%s, %s, 'receive', 'pending', 'normal',"
                                              " 'Case', '1912345678') RETURNING id", (site["tenant"], site_id))[0][0])
        return {"task_id": tid, "ref_doc_no": "1912345678", "object": "pack" if case == "grocery" else "box",
                "expected_units": 20 if case == "grocery" else 10,
                "expected_pieces_per_unit": 12 if case == "grocery" else None}

    app.dependency_overrides[get_ports] = lambda: AssistantPorts(create_case=create_case)
    r = _turn(site, "new grocery delivery")
    assert r["ai"] == "rules" and made == ["grocery"]
    assert r["say"] == "New grocery delivery open: 20 packs, 12 in each. Lay them out in one layer and say look."
    assert r["actions"][0]["type"] == "open_task"
    r = _turn(site, "new pharmacy delivery")
    assert made == ["grocery", "pharmacy"]
    assert r["say"] == "New pharmacy delivery open: 10 boxes. Lay them out in one layer and say look."
    assert recorded_api.requests == []  # rules only, no model call


def test_m5_v07_production_site_and_unwired_build_refuse(site: dict[str, Any], h: SimpleNamespace) -> None:
    app.dependency_overrides[get_ports] = lambda: AssistantPorts()
    r = _turn(site, "new grocery delivery")
    assert r["say"].startswith("This is a production site")
    h.set_sandbox(site)
    r = _turn(site, "new pharmacy delivery")
    assert r["say"] == "I can't create pharmacy deliveries in this build."
