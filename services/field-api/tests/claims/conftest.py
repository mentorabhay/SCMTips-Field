"""Fixtures for the M5 stream X tests: supplier claims and the evidence page.

``LookDouble`` is the test double of the look port (``field_api.claims.looks``): stream V's ``field.vision_look``
does not exist on this branch, so the looks are dicts in the contract section 2 shape, held here in test code only.
``RecordedAPI`` is the scripted Meta Model API (OpenAI-compatible chat completions) as in tests/assistant: an httpx
MockTransport in test code; the real API is not reachable from the build sandbox (docs/META_FIELD.md row 19).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard, Price
from field_api.app import app
from field_api.assistant.model import ChatModel, ModelRouter, ProviderConfig, get_router
from field_api.auth.jwt import Principal, create_dev_token
from field_api.claims.looks import get_look_port
from field_api.crops import LocalCropStore

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
META_PRICE = Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))
FAKE_KEY = "test-key-" + "y" * 16  # not a credential: a marker the tests look for in outputs
PHOTO = b"\xff\xd8\xff\xe0" + b"M5-claims-test-photo" * 40 + b"\xff\xd9"


def admin_sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def make_look(look_id: str, capture_id: str | None, task_id: str | None, *, expected: int = 20, seen: int | None = 20,
              damaged: tuple[int, ...] = (3, 9), ppu: int | None = 12,
              mismatches: dict[int, int] | None = None, expiry: list[tuple[int, str]] | None = None,
              window: int = 90, raw: str = "BRANDX biscuits 12 x 50 g") -> dict[str, Any]:
    """A look in the M5 contract section 2 shape (as stream V returns it)."""
    mism = {7: 10, 11: 10} if mismatches is None else mismatches
    instances = []
    for n in range(1, (seen or 0) + 1):
        col, row = (n - 1) % 5, (n - 1) // 5
        instances.append({"n": n, "box": [40 + col * 360, 30 + row * 340, 360 + col * 360, 330 + row * 340],
                          "polygon": None, "score": 0.93, "damaged": n in damaged,
                          "damage_note": "crushed corner" if n in damaged else None,
                          "label": {"read": True, "pieces_per_unit": mism.get(n, ppu), "batch": "B2411",
                                    "expiry": "2027-03", "raw": raw}})
    flagged = [{"n": n, "expiry": "2026-12", "reason": r} for n, r in (expiry or [])]
    flag_n = set(damaged) | {n for n, _ in (expiry or [])}
    pack = None
    if ppu is not None:
        pack = {"expected_pieces_per_unit": ppu, "mismatches": [{"n": n, "pieces_per_unit": p} for n, p in mism.items()],
                "pieces_difference": sum(p - ppu for p in mism.values())}
    return {
        "look_id": look_id, "source": "model" if seen is not None else "rules", "task_id": task_id, "line_id": None,
        "image": {"capture_id": capture_id, "width": 1920, "height": 1440},
        "instances": instances,
        "counts": {"expected": expected, "seen": seen, "damaged": len(damaged), "good": (seen or 0) - len(flag_n)},
        "pack": pack,
        "expiry": {"window_days": window, "flagged": flagged, "batches": ["B2411"]} if expiry is not None else None,
        "proposal": {"receive": (seen or 0) - len(flag_n), "flag": len(flag_n), "reasons": []},
        "say": "Twenty of twenty.",
        "models": [{"model": "sam-3.1", "purpose": "instances", "latency_ms": 840, "cost_usd": 0.004, "outcome": "ok"}],
        "reasons": [],
    }


@dataclass
class LookDouble:
    """The look port's test double: {(tenant, look_id): look}."""

    looks: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    calls: int = 0

    def __call__(self, principal: Principal, look_id: str) -> dict[str, Any] | None:
        self.calls += 1
        return self.looks.get((principal.tenant_id, look_id))

    def add(self, tenant: str, look: dict[str, Any]) -> str:
        self.looks[(tenant, look["look_id"])] = look
        return str(look["look_id"])


Script = dict[str, Any] | int


@dataclass
class RecordedAPI:
    script: list[Script] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(req.content))
        item = self.script.pop(0) if self.script else 500
        if isinstance(item, int):
            return httpx.Response(item, json={"error": {"message": "scripted"}})
        return httpx.Response(200, json=item)


def answer(content: str, prompt: int = 300, completion: int = 60) -> dict[str, Any]:
    return {"id": "chatcmpl-x", "object": "chat.completion", "model": "muse-spark-1.3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                      "prompt_tokens_details": {"cached_tokens": 0}}}


def caps_above_spend(monkeypatch: pytest.MonkeyPatch, headroom: str = "5") -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    for p, env in (("meta", "AI_BUDGET_META_USD"), ("baseten", "AI_BUDGET_BASETEN_USD")):
        monkeypatch.setenv(env, str(Decimal(usage["providers"][p]["spent_usd"]) + Decimal(headroom)))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + Decimal(headroom)))


@pytest.fixture
def recorded_api() -> RecordedAPI:
    return RecordedAPI()


@pytest.fixture
def model_router(recorded_api: RecordedAPI) -> ModelRouter:
    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.3": META_PRICE}})
    return ModelRouter([ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.3", "MODEL_API_KEY"),
                                  guard, httpx.MockTransport(recorded_api.handler))])


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    caps_above_spend(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", FAKE_KEY)


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


@pytest.fixture
def looks() -> LookDouble:
    return LookDouble()


@pytest.fixture
def client(looks: LookDouble, model_router: ModelRouter) -> Iterator[TestClient]:
    app.dependency_overrides[get_look_port] = lambda: looks
    app.dependency_overrides[get_router] = lambda: model_router
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_look_port, None)
        app.dependency_overrides.pop(get_router, None)


def _tenant_site(mode: str = "sandbox") -> dict[str, Any]:
    tenant, site_id = str(uuid.uuid4()), str(uuid.uuid4())
    plant = f"X{uuid.uuid4().hex[:7].upper()}"
    admin_sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status, mode)"
                      " VALUES (%s, %s, %s, 'Home table', 'warehouse', %s, 'active', %s)",
              (site_id, tenant, f"HX-{plant}", plant, mode))
    return {"tenant": tenant, "site": site_id, "plant": plant}


@pytest.fixture
def env(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, looks: LookDouble) -> dict[str, Any]:
    """A sandbox site with a receive task (one line), a photo capture stored in the crop store, a look on it, and
    tokens for every role (plus a supervisor of another tenant and an operator of another site)."""
    monkeypatch.setenv("FIELD_CROP_DIR", str(tmp_path / "crops"))
    e = _tenant_site()
    tenant, site_id = e["tenant"], e["site"]
    mat = str(admin_sql(tenant, "INSERT INTO field.material (tenant_id, erp_material_no, plant, description, base_uom)"
                                " VALUES (%s, 'SBX-000123', %s, 'biscuit pack', 'EA') RETURNING id",
                        (tenant, e["plant"]))[0][0])
    task = str(admin_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no)"
                                 " VALUES (%s, %s, 'receive', 'in_progress', 'medium', 'Grocery delivery 1800000077',"
                                 " '1800000077') RETURNING id", (tenant, site_id))[0][0])
    line = str(admin_sql(tenant, "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id,"
                                 " expected_qty, counted_qty, damaged_qty, uom, status) VALUES (%s, %s, %s, 10, %s, 20,"
                                 " 20, 2, 'EA', 'posted') RETURNING id", (tenant, site_id, task, mat))[0][0])
    device = str(admin_sql(tenant, "INSERT INTO field.device (tenant_id, kind, serial_no, model) VALUES (%s, 'phone',"
                                   " %s, 'Pixel') RETURNING id", (tenant, f"SN-{uuid.uuid4().hex[:8]}"))[0][0])
    capture = str(admin_sql(tenant, "INSERT INTO field.capture (tenant_id, site_id, device_id, task_id) VALUES"
                                    " (%s, %s, %s, %s) RETURNING id", (tenant, site_id, device, task))[0][0])
    uri = LocalCropStore().put(tenant, PHOTO)
    admin_sql(tenant, "INSERT INTO field.capture_evidence (tenant_id, capture_id, crop_s3_uri, file_size_bytes,"
                      " sha256_hash, retention_until) VALUES (%s, %s, %s, %s, %s, %s)",
              (tenant, capture, uri, len(PHOTO), hashlib.sha256(PHOTO).hexdigest(), datetime.now(UTC) + timedelta(days=30)))
    look_id = looks.add(tenant, make_look(str(uuid.uuid4()), capture, task))
    other = _tenant_site()
    e.update({
        "material": mat, "task": task, "line": line, "device": device, "capture": capture, "look": look_id,
        "op": create_dev_token("op-x", tenant, ["field.operator"], site_ids=[site_id]),
        "op_elsewhere": create_dev_token("op-y", tenant, ["field.operator"], site_ids=[str(uuid.uuid4())]),
        "tech": create_dev_token("tech-x", tenant, ["field.technician"], site_ids=[site_id]),
        "sup": create_dev_token("sup-x", tenant, ["field.supervisor"], site_ids=["*"]),
        "sup2": create_dev_token("sup-z", tenant, ["field.supervisor"], site_ids=["*"]),
        "viewer": create_dev_token("v-x", tenant, ["field.viewer"], site_ids=[site_id]),
        "integration": create_dev_token("int-x", tenant, ["field.integration"], site_ids=["*"]),
        "other_sup": create_dev_token("sup-o", other["tenant"], ["field.supervisor"], site_ids=["*"]),
        "other": other,
    })
    return e


def post_document(e: dict[str, Any], *, doc_number: str | None = None, year: str = "2026",
                  with_look: bool = True) -> dict[str, Any]:
    """A posted goods receipt of the env's task as Field records it: erp_document (payload as the voice confirm
    gate stages it, plus stream V's look_id), two posting jobs, their outbox events and the voice turn pair."""
    tenant = e["tenant"]
    doc_number = doc_number or str(5000000000 + uuid.uuid4().int % 999999999)
    now = datetime.now(UTC)
    post_ev = str(admin_sql(tenant, "INSERT INTO field.voice_event (tenant_id, device_id, task_id, transcript,"
                                    " confidence, intent, client_timestamp) VALUES (%s, %s, %s, 'post', 0.95, 'post', %s)"
                                    " RETURNING id", (tenant, e["device"], e["task"], now - timedelta(seconds=4)))[0][0])
    conf_ev = str(admin_sql(tenant, "INSERT INTO field.voice_event (tenant_id, device_id, task_id, transcript,"
                                    " confidence, intent, client_timestamp) VALUES (%s, %s, %s, 'confirm', 0.97,"
                                    " 'confirm', %s) RETURNING id",
                            (tenant, e["device"], e["task"], now - timedelta(seconds=1)))[0][0])
    payload = {"task_id": e["task"], "line_ids": [e["line"]], "requested_by": "op-x", "device_id": e["device"],
               "requested_at": (now - timedelta(seconds=1)).isoformat(), "delivery_document": "1800000077",
               "confirm_method": "voice", "post_voice_event_id": post_ev, "confirm_voice_event_id": conf_ev}
    if with_look:
        payload["look_id"] = e["look"]
    doc_id = str(admin_sql(tenant, "INSERT INTO field.erp_document (tenant_id, site_id, doc_type, doc_number, fiscal_year,"
                                   " movement_type, payload, status) VALUES (%s, %s, 'GR', %s, %s, '101', %s, 'posted')"
                                   " RETURNING id", (tenant, e["site"], doc_number, year, json.dumps(payload)))[0][0])
    jobs = []
    for seq, (family, items) in enumerate((
            ("InboundDeliveryItem", [{"DeliveryDocument": "1800000077", "DeliveryDocumentItem": "000010",
                                      "ActualDeliveryQuantity": "18.000"}]),
            ("GoodsReceipt", [{"DeliveryDocument": "1800000077"}])), start=1):
        jp = {"doc_family": family, "items": items, "header_data": {}, "seq": seq}
        jobs.append(str(admin_sql(tenant, "INSERT INTO field.posting_job (tenant_id, erp_doc_id, queue_key, seq, status,"
                                          " payload) VALUES (%s, %s, 'IBD:1800000077', %s, 'completed', %s) RETURNING id",
                                  (tenant, doc_id, seq, json.dumps(jp)))[0][0]))
    admin_sql(tenant, "INSERT INTO field.outbox (tenant_id, event_type, aggregate_id, payload) VALUES (%s, 'erp.posted',"
                      " %s, %s)", (tenant, jobs[-1], json.dumps({"type": "erp.posted", "data": {
                          "doc_type": "GoodsReceipt", "doc_no": doc_number, "doc_year": int(year),
                          "movement_types": ["101"], "queue_key": "IBD:1800000077"}})))
    return {"doc_id": doc_id, "doc_number": doc_number, "year": year, "jobs": jobs, "voice": [post_ev, conf_ev]}


def auth(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


@pytest.fixture
def h() -> SimpleNamespace:
    """Helpers (conftest functions are not importable under --import-mode=importlib)."""
    return SimpleNamespace(admin_sql=admin_sql, make_look=make_look, answer=answer, auth=auth, PHOTO=PHOTO,
                           FAKE_KEY=FAKE_KEY, post_document=post_document, tenant_site=_tenant_site)


Helper = Callable[..., Any]
