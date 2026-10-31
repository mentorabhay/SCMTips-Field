"""Fixtures for the Field Assistant tests (M3 contract §4).

``recorded_api`` is the test double of the Meta Model API / Baseten (OpenAI-compatible chat completions): an
httpx transport that answers from scripted responses and records every request body. It lives in test code
only; production code never imports it. The scripted answers are hand-written in the OpenAI-compatible
response format (choices[0].message, tool_calls, usage with prompt_tokens_details.cached_tokens), because the
live API could not be reached from the build sandbox to capture real ones (docs/META_FIELD.md row 19).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from field_api.ai.budget import BudgetGuard, Price
from field_api.assistant.model import ChatModel, ModelRouter, ProviderConfig
from field_api.auth.jwt import create_dev_token

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
BOOK_QTY = Decimal("7777")  # a number that must never reach the model or the operator on a count task
META_PRICE = Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))
FAKE_KEY = "test-key-" + "x" * 16  # not a credential: a marker the tests look for in outputs


def admin_sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def ensure_site_mode_column() -> None:
    """field.site.mode as track S adds it (M3 contract §2, migration field_0060); a no-op once that is merged."""
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("ALTER TABLE field.site ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'production'"
                    " CHECK (mode IN ('production', 'sandbox'))")


def answer(content: str | dict[str, Any] | None = None, tool_calls: list[dict[str, Any]] | None = None,
           prompt: int = 900, cached: int = 600, completion: int = 40) -> dict[str, Any]:
    """One chat-completions answer in the OpenAI-compatible format."""
    msg: dict[str, Any] = {"role": "assistant",
                           "content": json.dumps(content) if isinstance(content, dict) else content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "model": "muse-spark-1.2",
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                      "prompt_tokens_details": {"cached_tokens": cached}}}


def tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


Script = dict[str, Any] | int | type[Exception]


@dataclass
class RecordedAPI:
    """Scripted chat-completions endpoint. Each script item: an answer dict (200), an int (that HTTP status), or
    an httpx exception class (raised as a transport failure)."""

    script: list[Script] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    auth_headers: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(req.content))
        self.auth_headers.append(req.headers.get("authorization", ""))
        self.hosts.append(f"{req.url.host}{req.url.path}")
        item = self.script.pop(0) if self.script else 500
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("scripted failure", request=req)
        if isinstance(item, int):
            return httpx.Response(item, json={"error": {"message": "scripted"}})
        return httpx.Response(200, json=item)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def sent_text(self) -> str:
        return json.dumps(self.requests)


def caps_above_spend(monkeypatch: pytest.MonkeyPatch, headroom: str = "5") -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    for p, env in (("meta", "AI_BUDGET_META_USD"), ("baseten", "AI_BUDGET_BASETEN_USD")):
        monkeypatch.setenv(env, str(Decimal(usage["providers"][p]["spent_usd"]) + Decimal(headroom)))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + Decimal(headroom)))


@pytest.fixture(autouse=True)
def photo_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    d = tmp_path / "assistant-photos"
    monkeypatch.setenv("FIELD_ASSISTANT_PHOTO_DIR", str(d))
    return d


@pytest.fixture
def recorded_api() -> RecordedAPI:
    return RecordedAPI()


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    caps_above_spend(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", FAKE_KEY)


@pytest.fixture
def make_router(recorded_api: RecordedAPI) -> Callable[..., ModelRouter]:
    def make(with_fallback: bool = False) -> ModelRouter:
        prices = {"llama": {}, "baseten": {"fallback-model": Price(Decimal("1"), Decimal("2"))},
                  "meta": {"muse-spark-1.2": META_PRICE}}
        guard = BudgetGuard(prices=prices)
        models = [ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.2", "MODEL_API_KEY"),
                            guard, recorded_api.transport)]
        if with_fallback:
            models.append(ChatModel(ProviderConfig("baseten", "https://fallback.example.invalid/v1", "fallback-model",
                                                   "BASETEN_API_KEY"), guard, recorded_api.transport))
        return ModelRouter(models)

    return make


@pytest.fixture
def site() -> Iterator[dict[str, Any]]:
    """A warehouse site with a receive task (2 lines), a count task (1 line, book qty BOOK_QTY) and tokens."""
    tenant, site_id = str(uuid.uuid4()), str(uuid.uuid4())
    plant = f"A{uuid.uuid4().hex[:7].upper()}"
    admin_sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
                      " VALUES (%s, %s, %s, 'Assistant DC', 'warehouse', %s, 'active')",
              (site_id, tenant, f"AS-{plant}", plant))
    mats = {}
    for no, desc in (("MAT-BOLT", "Steel bolt M8"), ("MAT-NUT", "Hex nut M8"), ("MAT-RRU", "Radio unit")):
        mats[no] = str(admin_sql(tenant, "INSERT INTO field.material (tenant_id, erp_material_no, plant, description,"
                                         " base_uom) VALUES (%s, %s, %s, %s, 'EA') RETURNING id",
                                 (tenant, no, plant, desc))[0][0])
    recv = str(admin_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no,"
                                 " subtitle) VALUES (%s, %s, 'receive', 'pending', 'medium', 'Delivery 1800000022',"
                                 " '1800000022', 'From V-1') RETURNING id", (tenant, site_id))[0][0])
    recv_lines = []
    for i, (m, q) in enumerate((("MAT-BOLT", 24), ("MAT-NUT", 12)), start=1):
        recv_lines.append(str(admin_sql(
            tenant, "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,"
                    " storage_bin, status) VALUES (%s, %s, %s, %s, %s, %s, 'EA', NULL, 'pending') RETURNING id",
            (tenant, site_id, recv, i * 10, mats[m], q))[0][0]))
    count = str(admin_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no,"
                                  " subtitle) VALUES (%s, %s, 'count', 'pending', 'high', 'Count bin 03-05-02',"
                                  " 'PI-0042', 'PI PI-0042') RETURNING id", (tenant, site_id))[0][0])
    count_line = str(admin_sql(
        tenant, "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,"
                " storage_bin, status) VALUES (%s, %s, %s, 1, %s, %s, 'EA', '03-05-02', 'pending') RETURNING id",
        (tenant, site_id, count, mats["MAT-RRU"], BOOK_QTY))[0][0])
    pi = str(admin_sql(tenant, "INSERT INTO field.pi_document (tenant_id, doc_number, fiscal_year, plant,"
                               " storage_location, status, site_id, task_id) VALUES (%s, 'PI-0042', '2026', %s, '101A',"
                               " 'open', %s, %s) RETURNING id", (tenant, plant, site_id, count))[0][0])
    admin_sql(tenant, "INSERT INTO field.pi_book (tenant_id, pi_document_id, task_line_id, book_qty, unit_price)"
                      " VALUES (%s, %s, %s, %s, 12.5)", (tenant, pi, count_line, BOOK_QTY))
    op = create_dev_token("op-1", tenant, ["field.operator"], site_ids=[site_id])
    yield {"tenant": tenant, "site": site_id, "plant": plant, "receive": recv, "receive_lines": recv_lines,
           "count": count, "count_line": count_line, "op": op,
           "op2": create_dev_token("op-2", tenant, ["field.operator"], site_ids=[site_id]),
           "tech": create_dev_token("tech-1", tenant, ["field.technician"], site_ids=[site_id]),
           "sup": create_dev_token("sup-1", tenant, ["field.supervisor"], site_ids=["*"]),
           "viewer": create_dev_token("v-1", tenant, ["field.viewer"], site_ids=[site_id])}


def set_sandbox(s: dict[str, Any]) -> None:
    ensure_site_mode_column()
    admin_sql(s["tenant"], "UPDATE field.site SET mode = 'sandbox' WHERE id = %s", (s["site"],))


@pytest.fixture
def h() -> SimpleNamespace:
    """Helpers for the test modules (conftest functions are not importable under --import-mode=importlib)."""
    return SimpleNamespace(answer=answer, tool_call=tool_call, admin_sql=admin_sql, set_sandbox=set_sandbox,
                           caps_above_spend=caps_above_spend, BOOK_QTY=BOOK_QTY, FAKE_KEY=FAKE_KEY,
                           META_PRICE=META_PRICE)
