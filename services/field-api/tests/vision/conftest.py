"""Fixtures for the M5 vision look tests (docs/design/M5_CONTRACT.md §2).

``VisionDouble`` is the test double of the Meta Model API for the look, in test code only: an httpx transport that
answers ``POST /responses`` (SAM 3.1: server-sent events whose text carries ``<|box;...|>`` tokens, the shape of
Meta's docs and parser package) and ``POST /chat/completions`` (Muse Spark 1.3 / the Baseten fallback: an
OpenAI-compatible answer whose content is the label JSON for exactly the crops asked, from a truth table). The
shapes are hand-written from the docs; no real answer could be recorded (no key, no route: META_FIELD rows 20, 23).
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard, Price
from field_api.assistant.model import ChatModel, ProviderConfig
from field_api.auth.jwt import create_dev_token
from field_api.vision.labels import ChatLabelReader
from field_api.vision.ports import VisionPorts
from field_api.vision.sam import Sam31Instances
from PIL import Image, ImageDraw

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
FAKE_KEY = "test-key-" + "v" * 16  # a marker, not a credential
PRICES = {"llama": {}, "baseten": {"llama-3.2-vision": Price(Decimal("0.5"), Decimal("0.5"))},
          "meta": {"sam-3.1": Price(Decimal(0), Decimal(0), per_image_usd=Decimal("0.005")),
                   "muse-spark-1.3": Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))}}


def admin_sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def grid_boxes(n: int, cols: int = 5, width: int = 1000, height: int = 800) -> list[tuple[int, int, int, int]]:
    rows = (n + cols - 1) // cols
    cw, ch = width // cols, height // max(rows, 1)
    return [(c * cw + 10, r * ch + 10, (c + 1) * cw - 10, (r + 1) * ch - 10)
            for r in range(rows) for c in range(cols)][:n]


def photo(boxes: list[tuple[int, int, int, int]], width: int = 1000, height: int = 800) -> bytes:
    img = Image.new("RGB", (width, height), (235, 230, 220))
    d = ImageDraw.Draw(img)
    for i, (x0, y0, x1, y1) in enumerate(boxes, start=1):
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(200, 60 + 7 * i % 150, 40), outline=(20, 20, 20))
        d.text((x0 + 8, y0 + 8), f"PACK {i}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def sam_text(boxes: list[tuple[int, int, int, int]], width: int, height: int, scores: list[float] | None = None) -> str:
    recs = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        c = f";c={scores[i]}" if scores else ";c=0.91"
        recs.append(f"{i}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={width};h={height}{c}|>"
                    f"<|mask;x=0;y=0;data={y1 - y0},{x1 - x0},~!!!!M!0c|>")
    return "<0f>" + ",".join(recs)


def sse(text: str, usage: dict[str, int] | None = None) -> bytes:
    events = [{"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}}]
    for i in range(0, len(text), 64):
        events.append({"type": "response.output_text.delta", "delta": text[i:i + 64]})
    events.append({"type": "response.completed", "response": {"id": "resp_1", "status": "completed",
                                                              "usage": usage or {"input_tokens": 0, "output_tokens": 0}}})
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


Script = Any  # an answer (list of boxes), an int HTTP status, or an httpx exception class


@dataclass
class VisionDouble:
    """Scripted SAM 3.1 + label endpoints. ``labels``: {n: item} truth table (item fields as the schema); a crop
    without an entry answers label_readable false. ``label_script``: queued statuses / exceptions for chat calls."""

    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    width: int = 1000
    height: int = 800
    labels: dict[int, dict[str, Any]] = field(default_factory=dict)
    sam_script: list[Script] = field(default_factory=list)
    label_script: list[Script] = field(default_factory=list)
    shuffle: bool = True
    requests: list[dict[str, Any]] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    auth: list[str] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        self.requests.append(body)
        self.paths.append(f"{req.url.host}{req.url.path}")
        self.auth.append(req.headers.get("authorization", ""))
        script = self.sam_script if req.url.path.endswith("/responses") else self.label_script
        if script:
            item = script.pop(0)
            if isinstance(item, type) and issubclass(item, Exception):
                raise item("scripted failure", request=req)
            if isinstance(item, int):
                return httpx.Response(item, json={"error": {"message": "scripted"}})
        if req.url.path.endswith("/responses"):
            boxes = list(self.boxes)
            if self.shuffle:
                random.Random(7).shuffle(boxes)
            return httpx.Response(200, content=sse(sam_text(boxes, self.width, self.height)),
                                  headers={"content-type": "text/event-stream"})
        wanted = [int(m.group(1)) for part in body["messages"][-1]["content"] if part.get("type") == "text"
                  for m in [re.search(r"(\d+):$", part["text"])] if m]
        items = []
        for n in wanted:
            truth = self.labels.get(n, {})
            items.append({"n": n, "label_readable": truth.get("label_readable", bool(truth)),
                          "pieces_per_unit": truth.get("pieces_per_unit"), "batch": truth.get("batch"),
                          "expiry": truth.get("expiry"), "damaged": truth.get("damaged", False),
                          "damage_note": truth.get("damage_note"), "label_text": truth.get("label_text")})
        answer = {"id": "chatcmpl-v", "object": "chat.completion", "model": body["model"],
                  "choices": [{"index": 0, "finish_reason": "stop",
                               "message": {"role": "assistant", "content": json.dumps({"items": items})}}],
                  "usage": {"prompt_tokens": 900 * len(wanted), "completion_tokens": 300,
                            "prompt_tokens_details": {"cached_tokens": 0}}}
        return httpx.Response(200, json=answer)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def calls(self, suffix: str) -> int:
        return sum(1 for p in self.paths if p.endswith(suffix))


def caps_above_spend(monkeypatch: pytest.MonkeyPatch, headroom: str = "5") -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    for p, env in (("meta", "AI_BUDGET_META_USD"), ("baseten", "AI_BUDGET_BASETEN_USD")):
        monkeypatch.setenv(env, str(Decimal(usage["providers"][p]["spent_usd"]) + Decimal(headroom)))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + Decimal(headroom)))


def ports_for(double: VisionDouble, prices: dict[str, dict[str, Price]] | None = None,
              with_fallback: bool = False) -> VisionPorts:
    guard = BudgetGuard(prices=prices or PRICES)
    sam = Sam31Instances("https://api.meta.ai/v1", "sam-3.1", guard, double.transport)
    readers = [ChatLabelReader(ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.3",
                                                        "MODEL_API_KEY"), guard, double.transport))]
    if with_fallback:
        readers.append(ChatLabelReader(ChatModel(ProviderConfig("baseten", "https://bt.example.invalid/v1",
                                                                "llama-3.2-vision", "BASETEN_API_KEY"), guard,
                                                 double.transport), use_response_format=False))
    return VisionPorts(sam, tuple(readers))


@pytest.fixture(autouse=True)
def _crop_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CROP_DIR", str(tmp_path / "crops"))


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    caps_above_spend(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BASETEN_API_KEY", FAKE_KEY)


@pytest.fixture
def client() -> TestClient:
    from field_api.app import app

    return TestClient(app)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


def upload_capture(client: TestClient, s: dict[str, Any], jpeg: bytes, task_id: str | None = None) -> str:
    """A capture with its crop through the real captures API (device, consent, blur gates as the app meets them)."""
    r = client.post("/v1/captures", data={"metadata": json.dumps({
        "device_id": s["phone"], "task_id": task_id or s["receive"], "site_id": s["site"], "shutter_timestamp": 1,
        "blur_applied": True, "code_type": "photo", "code_value": f"look-{uuid.uuid4()}", "readability": 0.9})},
        files={"crop": ("look.jpg", jpeg, "image/jpeg")}, headers=_h(s["dev"]))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


@pytest.fixture
def site(client: TestClient) -> Iterator[dict[str, Any]]:
    """A warehouse site with a receive task (one line of 20 packs, a C1 expectation of 12 pieces per pack), a count
    task (book quantity 7777: never shown), a phone with consent, and tokens."""
    tenant, site_id = str(uuid.uuid4()), str(uuid.uuid4())
    plant = f"V{uuid.uuid4().hex[:7].upper()}"
    admin_sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
                      " VALUES (%s, %s, %s, 'Vision DC', 'warehouse', %s, 'active')", (site_id, tenant, f"VI-{plant}", plant))
    mat = str(admin_sql(tenant, "INSERT INTO field.material (tenant_id, erp_material_no, plant, description, base_uom)"
                                " VALUES (%s, 'MAT-PACK', %s, 'biscuit pack', 'EA') RETURNING id", (tenant, plant))[0][0])
    recv = str(admin_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no)"
                                 " VALUES (%s, %s, 'receive', 'pending', 'normal', 'Delivery 1890000001', '1890000001')"
                                 " RETURNING id", (tenant, site_id))[0][0])
    line = str(admin_sql(tenant, "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id,"
                                 " expected_qty, uom, status) VALUES (%s, %s, %s, 10, %s, 20, 'EA', 'pending') RETURNING id",
                         (tenant, site_id, recv, mat))[0][0])
    count = str(admin_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no)"
                                  " VALUES (%s, %s, 'count', 'pending', 'normal', 'Count', 'PI-V1') RETURNING id",
                          (tenant, site_id))[0][0])
    count_line = str(admin_sql(tenant, "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id,"
                                       " expected_qty, uom, storage_bin, status) VALUES (%s, %s, %s, 1, %s, 7777, 'EA',"
                                       " 'B-1', 'pending') RETURNING id", (tenant, site_id, count, mat))[0][0])
    op = create_dev_token("op-v", tenant, ["field.operator"], site_ids=[site_id])
    phone = client.post("/v1/devices", json={"kind": "phone", "serial_no": f"P-{uuid.uuid4()}", "model": "Pixel"},
                        headers=_h(op)).json()["id"]
    dev = create_dev_token("op-v", tenant, ["field.operator"], site_ids=[site_id], device_id=phone)
    r = client.post("/v1/consents", json={"site_id": site_id, "device_id": phone}, headers=_h(dev))
    assert r.status_code == 201, r.text
    yield {"tenant": tenant, "site": site_id, "plant": plant, "receive": recv, "line": line, "count": count,
           "count_line": count_line, "op": op, "dev": dev, "phone": phone,
           "viewer": create_dev_token("v-v", tenant, ["field.viewer"], site_ids=[site_id]),
           "sup": create_dev_token("sup-v", tenant, ["field.supervisor"], site_ids=["*"]),
           "other": create_dev_token("op-x", str(uuid.uuid4()), ["field.operator"], site_ids=["*"])}


def add_case_line(s: dict[str, Any], case: str, ppu: int | None = None, window: int | None = None,
                  line: str | None = None, task: str | None = None, noun: str = "pack") -> None:
    admin_sql(s["tenant"], "INSERT INTO field.vision_case_line (tenant_id, site_id, task_id, task_line_id, \"case\","
                           " object, expected_pieces_per_unit, expiry_window_days) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
              (s["tenant"], s["site"], task or s["receive"], line or s["line"], case, noun, ppu, window))


@pytest.fixture
def v() -> SimpleNamespace:
    """Helpers for the test modules (conftest functions are not importable under --import-mode=importlib)."""
    return SimpleNamespace(grid_boxes=grid_boxes, photo=photo, sam_text=sam_text, sse=sse, VisionDouble=VisionDouble,
                           ports_for=ports_for, upload_capture=upload_capture, admin_sql=admin_sql,
                           add_case_line=add_case_line, caps_above_spend=caps_above_spend, FAKE_KEY=FAKE_KEY,
                           PRICES=PRICES, h=_h)
