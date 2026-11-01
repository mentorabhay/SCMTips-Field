"""Fixtures for the C3 authenticity tests (docs/design/M5_C3_CONTRACT.md).

- the maker: ``field_oem_testing.memory.MemoryOem`` (the OEM port's test double, rule 2.4), in place of the
  configured port (``get_oem_port`` overridden);
- the models: ``SealDouble``, an httpx transport in test code answering SAM 3.1 (``POST /responses``, box tokens) and
  Muse Spark 1.3 (``POST /chat/completions``, the seal JSON) in the UNVERIFIED shapes of the M5 look;
- a sandbox site, a capture with a real JPEG of a "seal" stored in the crop store, tokens for every role.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
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
from field_api.auth.jwt import create_dev_token
from field_api.authenticity.oem import get_oem_port
from field_api.authenticity.seal import ChatSealInspector, VisualPorts, get_visual_ports
from field_api.crops import LocalCropStore
from field_api.vision.sam import Sam31Instances
from field_oem_testing.memory import MemoryOem
from PIL import Image, ImageDraw

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
FAKE_KEY = "test-key-" + "c" * 16  # a marker, not a credential
PRICES = {"llama": {}, "baseten": {},
          "meta": {"sam-3.1": Price(Decimal(0), Decimal(0), per_image_usd=Decimal("0.005")),
                   "muse-spark-1.3": Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))}}
SEAL_BOX = (300, 200, 700, 420)
D = date


def admin_sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def seal_photo(width: int = 1000, height: int = 700) -> bytes:
    img = Image.new("RGB", (width, height), (220, 200, 170))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = SEAL_BOX
    d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(31, 58, 95), outline=(10, 10, 10))
    d.text((x0 + 10, y0 + 10), "SAMPLE SEAL", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def sse(text: str) -> bytes:
    events = [{"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}},
              {"type": "response.output_text.delta", "delta": text},
              {"type": "response.completed", "response": {"id": "resp_1", "status": "completed",
                                                          "usage": {"input_tokens": 0, "output_tokens": 0}}}]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


def sam_text(boxes: list[tuple[int, int, int, int]], width: int, height: int) -> str:
    recs = [f"{i}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={width};h={height};c=0.9|>"
            for i, (x0, y0, x1, y1) in enumerate(boxes)]
    return "<0f>" + ",".join(recs)


@dataclass
class SealDouble:
    """SAM answers ``boxes`` (per prompt: ``boxes_by_prompt`` first); Muse answers ``seal`` or a scripted status."""

    boxes: list[tuple[int, int, int, int]] = field(default_factory=lambda: [SEAL_BOX])
    boxes_by_prompt: dict[str, list[tuple[int, int, int, int]]] = field(default_factory=dict)
    seal: dict[str, Any] = field(default_factory=lambda: {"seal_visible": True, "signs": []})
    muse_status: int | None = None
    sam_status: int | None = None
    width: int = 1000
    height: int = 700
    prompts: list[str] = field(default_factory=list)
    muse_requests: list[dict[str, Any]] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path.endswith("/responses"):
            text_parts = [c.get("text") for m in body.get("input", []) if isinstance(m, dict)
                          for c in (m.get("content") or []) if isinstance(c, dict) and c.get("type") == "input_text"]
            prompt = str(text_parts[0]) if text_parts else ""
            self.prompts.append(prompt)
            if self.sam_status:
                return httpx.Response(self.sam_status, json={"error": {"message": "scripted"}})
            boxes = self.boxes_by_prompt.get(prompt, self.boxes)
            return httpx.Response(200, content=sse(sam_text(boxes, self.width, self.height)),
                                  headers={"content-type": "text/event-stream"})
        self.muse_requests.append(body)
        if self.muse_status:
            return httpx.Response(self.muse_status, json={"error": {"message": "scripted"}})
        return httpx.Response(200, json={
            "id": "chatcmpl-s", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(self.seal)}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 0}}})

    def ports(self) -> VisualPorts:
        guard = BudgetGuard(prices=PRICES)
        transport = httpx.MockTransport(self.handler)
        return VisualPorts(
            Sam31Instances("https://api.meta.ai/v1", "sam-3.1", guard, transport=transport),
            ChatSealInspector(ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.3",
                                                       "MODEL_API_KEY"), guard, transport)))


def caps_above_spend(monkeypatch: pytest.MonkeyPatch, headroom: str = "5") -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    for p, env in (("meta", "AI_BUDGET_META_USD"), ("baseten", "AI_BUDGET_BASETEN_USD")):
        monkeypatch.setenv(env, str(Decimal(usage["providers"][p]["spent_usd"]) + Decimal(headroom)))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + Decimal(headroom)))


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    caps_above_spend(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", FAKE_KEY)


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


@pytest.fixture
def oem() -> MemoryOem:
    return MemoryOem()


@pytest.fixture
def seal() -> SealDouble:
    return SealDouble()


@pytest.fixture
def client(oem: MemoryOem, seal: SealDouble) -> Iterator[TestClient]:
    app.dependency_overrides[get_oem_port] = lambda: oem
    app.dependency_overrides[get_visual_ports] = seal.ports
    app.dependency_overrides[get_router] = lambda: ModelRouter([])
    try:
        yield TestClient(app)
    finally:
        for dep in (get_oem_port, get_visual_ports, get_router):
            app.dependency_overrides.pop(dep, None)


def _site(tenant: str) -> str:
    site = str(uuid.uuid4())
    plant = f"C{uuid.uuid4().hex[:7].upper()}"
    admin_sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status, mode)"
                      " VALUES (%s, %s, %s, 'Returns dock', 'warehouse', %s, 'active', 'sandbox')",
              (site, tenant, f"C3-{plant}", plant))
    return site


def add_capture(e: dict[str, Any], data: bytes, *, site: str | None = None) -> str:
    tenant = e["tenant"]
    capture = str(admin_sql(tenant, "INSERT INTO field.capture (tenant_id, site_id, device_id) VALUES (%s, %s, %s)"
                                    " RETURNING id", (tenant, site or e["site"], e["device"]))[0][0])
    uri = LocalCropStore().put(tenant, data)
    admin_sql(tenant, "INSERT INTO field.capture_evidence (tenant_id, capture_id, crop_s3_uri, file_size_bytes,"
                      " sha256_hash, retention_until) VALUES (%s, %s, %s, %s, %s, %s)",
              (tenant, capture, uri, len(data), hashlib.sha256(data).hexdigest(), datetime.now(UTC) + timedelta(days=30)))
    return capture


@pytest.fixture
def env(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, oem: MemoryOem) -> dict[str, Any]:
    monkeypatch.setenv("FIELD_CROP_DIR", str(tmp_path / "crops"))
    tenant = str(uuid.uuid4())
    site, site2 = _site(tenant), _site(tenant)
    device = str(admin_sql(tenant, "INSERT INTO field.device (tenant_id, kind, serial_no, model) VALUES (%s, 'phone',"
                                   " %s, 'Pixel') RETURNING id", (tenant, f"SN-{uuid.uuid4().hex[:8]}"))[0][0])
    other = str(uuid.uuid4())
    other_site = _site(other)
    e: dict[str, Any] = {"tenant": tenant, "site": site, "site2": site2, "device": device, "other": other}
    e["photo"] = seal_photo()
    e["capture"] = add_capture(e, e["photo"])
    serial = f"KSO-{uuid.uuid4().hex[:8].upper()}"
    shipped = [("manufactured", D(2026, 9, 28)), ("shipped_to_seller", D(2026, 10, 2)), ("delivered", D(2026, 10, 8))]
    e["new"] = oem.add_unit(f"{serial}-N", events=shipped)
    e["returned"] = oem.add_unit(f"{serial}-R", events=[*shipped, ("activated", D(2026, 10, 12)),
                                                         ("returned", D(2026, 10, 20))])
    e["activated"] = oem.add_unit(f"{serial}-A", events=[*shipped, ("activated", D(2026, 10, 12))])
    e["forged"] = oem.forged(f"{serial}-F")
    e.update({
        "op": create_dev_token("op-c3", tenant, ["field.operator"], site_ids=[site], device_id=device),
        "op2": create_dev_token("op-c3b", tenant, ["field.operator"], site_ids=[site]),
        "sup": create_dev_token("sup-c3", tenant, ["field.supervisor"], site_ids=["*"]),
        "viewer": create_dev_token("v-c3", tenant, ["field.viewer"], site_ids=[site]),
        "tech": create_dev_token("tech-c3", tenant, ["field.technician"], site_ids=[site]),
        "integration": create_dev_token("int-c3", tenant, ["field.integration"], site_ids=["*"]),
        "op_elsewhere": create_dev_token("op-c3x", tenant, ["field.operator"], site_ids=[site2]),
        "other_op": create_dev_token("op-o", other, ["field.operator"], site_ids=[other_site]),
    })
    return e


def auth(token: str, key: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid.uuid4())}


def check(client: TestClient, token: str, code: str, key: str | None = None, **body: Any) -> httpx.Response:
    return client.post("/v1/authenticity/checks", json={"code": code, **body}, headers=auth(token, key))


@pytest.fixture
def h() -> SimpleNamespace:
    """Helpers (conftest functions are not importable under --import-mode=importlib)."""
    return SimpleNamespace(admin_sql=admin_sql, auth=auth, check=check, add_capture=add_capture,
                           seal_photo=seal_photo, FAKE_KEY=FAKE_KEY)
