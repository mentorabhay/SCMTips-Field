"""Rules first (M4 contract §4, owner's field test of 31 Oct 2026) and the M4 sandbox intents.

The owner's field-api log: every assistant turn tried Muse first, timed out after 6 s (AI_TIMEOUT, once
AI_TRANSPORT) and fell back to rules, so Start Work answered 6-7 s late. Now:
- greeting / session start, work list, most urgent, start, what's next, how many left, summary, pause / resume /
  end, step done, scans and the sandbox unknown-code dialog are answered by rules with ZERO model calls, even with
  the AI on and a model that would answer (proved here with the recorded-response double and the budget ledger);
- only what the rules cannot classify goes to the model, within ASSISTANT_MODEL_DEADLINE_S (default 3.5 s,
  1.5..6), proved with a real local HTTP server that never answers in time;
- on sandbox sites "new home receipt" and "count shelf <bin>" / "count a shelf" create the task through the
  sandbox ports and open it, and "nothing assigned" offers both; production sites refuse politely.
"""

from __future__ import annotations

import os
import statistics
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard
from field_api.app import app
from field_api.assistant.model import (
    MODEL_DEADLINE_S,
    ChatModel,
    ModelRouter,
    ProviderConfig,
    get_router,
    model_deadline_s,
)
from field_api.assistant.ports import AssistantPorts, CodeLookup, SandboxTaskResult, get_ports
from field_api.assistant.rules import bin_key, intent, match_bin
from field_api.assistant.service import TurnIn, needs_model
from field_api.auth.jwt import Principal
from field_api.errors import FieldError

pytestmark = pytest.mark.unit
api = TestClient(app)


@pytest.fixture(autouse=True)
def wired(ai_on: None, make_router: Callable[..., ModelRouter]) -> Iterator[None]:
    router = make_router()
    app.dependency_overrides[get_router] = lambda: router
    yield
    app.dependency_overrides.pop(get_router, None)
    app.dependency_overrides.pop(get_ports, None)


def turn(s: dict[str, Any], event: str, **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"site_id": s["site"], "event": event, "session_id": kw.pop("session_id", None),
                            "client_state": {"task_id": kw.pop("task_id", None)}}
    body.update(kw)
    r = api.post("/v1/assistant/turns", json=body,
                 headers={"Authorization": f"Bearer {s['op']}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _usage_rows(tenant: str) -> int:
    with psycopg.connect(os.environ["FIELD_ADMIN_DATABASE_URL"]) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.ai_usage WHERE tenant_id = %s", (tenant,))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _t(event: str, text: str | None = None, code: str | None = None) -> TurnIn:
    return TurnIn(session_id=None, site_id="s", event=event, text=text, code=code, photo_jpeg_b64=None,
                  task_id=None, line_id=None, step=None)


# ---------------------------------------------------------------- the routing decision (pure)
@pytest.mark.parametrize(("t", "dialog", "photo", "want"), [
    (_t("session_start"), None, False, False), (_t("session_end"), None, False, False),
    (_t("pause"), None, False, False), (_t("resume"), None, False, False), (_t("step_done"), None, False, False),
    (_t("scan", code="X1"), None, False, False), (_t("unknown_code", code="X1"), None, True, False),
    (_t("utterance", "hi"), None, False, False), (_t("utterance", "what do we have today"), None, False, False),
    (_t("utterance", "what's most urgent"), None, False, False), (_t("utterance", "start receipt"), None, False, False),
    (_t("utterance", "what's next"), None, False, False), (_t("utterance", "how many left"), None, False, False),
    (_t("utterance", "summary"), None, False, False), (_t("utterance", "new home receipt"), None, False, False),
    (_t("utterance", "count shelf HOME-A"), None, False, False),
    (_t("utterance", "a blue coffee mug"), {"kind": "sandbox_item"}, False, False),  # an open dialog: rules
    (_t("utterance", "what is this", code="X1"), None, True, False),  # a code: rules look it up
    (_t("utterance", "what is this"), None, True, True),  # a photo, no code: only the model can see it
    (_t("photo"), None, True, True), (_t("photo", code="X1"), None, True, False), (_t("photo"), None, False, False),
    (_t("utterance", "is the dock busy"), None, False, True),  # rules cannot classify it
])
def test_needs_model_only_for_what_rules_cannot_answer(t: TurnIn, dialog: dict[str, Any] | None, photo: bool,
                                                       want: bool) -> None:
    assert needs_model(t, dialog, photo) is want


# ---------------------------------------------------------------- zero model calls, measured latency
def test_rules_first_turns_make_zero_model_calls_and_answer_at_once(site: dict[str, Any], recorded_api: Any,
                                                                    h: SimpleNamespace) -> None:
    """AI on, key set, a model that would answer: none of these turns may call it."""
    recorded_api.script = [h.answer({"say": "MODEL ANSWER", "actions": []}) for _ in range(40)]
    timings: list[float] = []

    def timed(event: str, **kw: Any) -> dict[str, Any]:
        t0 = time.perf_counter()
        r = turn(site, event, **kw)
        timings.append(time.perf_counter() - t0)
        assert r["ai"] == "rules" and r["cost_usd"] == 0.0 and "MODEL" not in r["say"], (event, kw, r)
        return r

    first = timed("session_start")
    sid = first["session_id"]
    assert "2 jobs" in first["say"]
    for text in ("hello", "what do we have today", "what's most urgent", "what's next", "how many left", "summary",
                 "help", "repeat", "when am I done"):
        timed("utterance", text=text, session_id=sid)
    assert timed("utterance", text="start receipt", session_id=sid)["actions"] == [
        {"type": "open_task", "task_id": site["receive"]}]
    for text in ("what's next", "how many left", "post"):
        timed("utterance", text=text, session_id=sid, task_id=site["receive"])
    timed("utterance", text="what is this", code="MAT-NUT", session_id=sid, task_id=site["receive"])
    timed("scan", code="MAT-BOLT", session_id=sid, task_id=site["receive"])
    timed("step_done", session_id=sid, task_id=site["receive"])
    timed("unknown_code", code="4006381333931", session_id=sid, task_id=site["receive"])
    timed("pause", session_id=sid)
    timed("resume", session_id=sid)
    timed("session_end", session_id=sid)
    assert recorded_api.requests == [] and _usage_rows(site["tenant"]) == 0
    rows = h.admin_sql(site["tenant"], "SELECT ai, latency_ms, tool_calls FROM field.assistant_turn t JOIN"
                                       " field.assistant_session s ON s.id = t.session_id WHERE s.id = %s", (sid,))
    assert len(rows) == len(timings) and all(r[0] == "rules" for r in rows)
    assert all(not any(c.get("name") in ("fallback", "model_calls") for c in r[2]) for r in rows)
    # Measured on the build machine (HTTP through TestClient + Postgres): far below the shortest model deadline.
    print(f"\nrules-first turns: n={len(timings)} median={statistics.median(timings) * 1000:.0f} ms "
          f"max={max(timings) * 1000:.0f} ms; server latency_ms max={max(r[1] for r in rows)}")
    assert max(timings) < 1.5


def test_sandbox_dialog_is_rules_only_with_ai_on(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    added: list[tuple[str, str, Decimal | None]] = []

    def resolve(principal: Principal, site_id: str, code: str) -> CodeLookup:
        return {"code": code, "kind": "unknown", "material": None, "bin": None, "site_mode": "sandbox"}

    def add(principal: Principal, task_id: str, code: str, description: str, qty: Decimal | None,
            idempotency_key: str) -> Any:
        added.append((code, description, qty))
        return {"line_id": str(uuid.uuid4()), "material": "HOME-0003", "created_material": True}

    app.dependency_overrides[get_ports] = lambda: AssistantPorts(resolve, add)
    recorded_api.script = [h.answer({"say": "MODEL", "actions": []}) for _ in range(5)]
    r = turn(site, "unknown_code", code="777", task_id=site["receive"])
    sid = r["session_id"]
    r = turn(site, "utterance", text="tell me something useful", session_id=sid, task_id=site["receive"])
    assert r["say"] == "Tell me something useful. How many?"  # in the dialog every utterance is the answer
    r = turn(site, "utterance", text="three", session_id=sid, task_id=site["receive"])
    assert added == [("777", "tell me something useful", Decimal(3))] and r["ai"] == "rules"
    assert recorded_api.requests == []


# ---------------------------------------------------------------- the model's deadline
def test_model_deadline_is_a_setting_within_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSISTANT_MODEL_DEADLINE_S", raising=False)
    assert model_deadline_s() == MODEL_DEADLINE_S == 3.5
    for raw, want in (("2", 2.0), ("0.2", 1.5), ("60", 6.0), ("4.25", 4.25), ("soon", 3.5), ("nan", 3.5)):
        monkeypatch.setenv("ASSISTANT_MODEL_DEADLINE_S", raw)
        assert model_deadline_s() == want


@pytest.mark.parametrize(("setting", "ceiling"), [(None, 3.5), ("2", 2.0)])
def test_unclassified_turn_gives_the_model_only_the_deadline(site: dict[str, Any], h: SimpleNamespace,
                                                             monkeypatch: pytest.MonkeyPatch, setting: str | None,
                                                             ceiling: float) -> None:
    if setting is None:
        monkeypatch.delenv("ASSISTANT_MODEL_DEADLINE_S", raising=False)
    else:
        monkeypatch.setenv("ASSISTANT_MODEL_DEADLINE_S", setting)
    seen: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.extend(v for v in req.extensions["timeout"].values() if v is not None)
        raise httpx.ReadTimeout("slow", request=req)

    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.2": h.META_PRICE}})
    router = ModelRouter([ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.2",
                                                   "MODEL_API_KEY"), guard, httpx.MockTransport(handler))])
    app.dependency_overrides[get_router] = lambda: router
    r = turn(site, "utterance", text="is the dock busy")
    assert r["ai"] == "rules" and seen and max(seen) <= ceiling and min(seen) > ceiling - 0.5


class _SlowModel(BaseHTTPRequestHandler):
    """A chat-completions endpoint that answers far too late (real sockets, real timeout)."""

    def do_POST(self) -> None:  # noqa: N802 (http.server's method name)
        time.sleep(8)

    def log_message(self, *args: Any) -> None:
        return


def test_slow_model_falls_back_within_the_deadline(site: dict[str, Any], h: SimpleNamespace,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's case, measured: a model that never answers in time costs at most the deadline, then rules."""
    monkeypatch.setenv("ASSISTANT_MODEL_DEADLINE_S", "1.5")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowModel)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.2": h.META_PRICE}})
        router = ModelRouter([ChatModel(ProviderConfig("meta", f"http://127.0.0.1:{server.server_port}/v1",
                                                       "muse-spark-1.2", "MODEL_API_KEY"), guard)])
        app.dependency_overrides[get_router] = lambda: router
        t0 = time.perf_counter()
        r = turn(site, "utterance", text="is the dock busy")
        took = time.perf_counter() - t0
    finally:
        server.shutdown()
    print(f"\nslow model, deadline 1.5 s: turn answered by rules after {took * 1000:.0f} ms")
    assert r["ai"] == "rules" and 1.4 < took < 2.5
    rows = h.admin_sql(site["tenant"], "SELECT tool_calls FROM field.assistant_turn WHERE session_id = %s",
                       (r["session_id"],))
    fb = [c for c in rows[0][0] if c["name"] == "fallback"]
    assert fb and "meta:AI_TIMEOUT" in fb[0]["reasons"]


# ---------------------------------------------------------------- M4 sandbox intents
@pytest.mark.parametrize(("text", "want", "arg"), [
    ("new home receipt", "new_receipt", ""), ("start a home receipt", "new_receipt", ""),
    ("create a new receipt", "new_receipt", ""), ("another receipt please", "new_receipt", ""),
    ("start receipt", "start", "receipt"), ("start the count", "start", "the count"),
    ("count shelf HOME-A", "new_count", "home-a"), ("count a shelf", "new_count", ""),
    ("okay count the shelf b", "new_count", "b"), ("start a count of shelf 03-05-02", "new_count", "03-05-02"),
    ("count bin 03-05-02", "new_count", "03-05-02"), ("new count", "new_count", ""),
    ("make a new shelf count", "new_count", ""), ("count four", "count", "four"), ("count 12", "count", "12"),
])
def test_new_work_intents(text: str, want: str, arg: str) -> None:
    assert intent(text) == (want, arg)


def test_bins_match_as_spoken() -> None:
    bins = ["HOME-A", "HOME-B", "03-05-02", "03-05-12"]
    assert bin_key("zero three dash zero five dash zero two") == "030502"
    assert match_bin("a", bins) == "HOME-A" and match_bin("shelf home b", bins) == "HOME-B"
    assert match_bin("zero three zero five zero two", bins) == "03-05-02"
    assert match_bin("2", bins) is None  # ends 03-05-02 and 03-05-12: ambiguous
    assert match_bin("", bins) is None and match_bin("kitchen", bins) is None


class SandboxPorts:
    """Doubles of field_api.sandbox.service.create_receipt / create_count that create real task rows (so the
    open_task action passes the visible-task check), plus the resolve/add pair."""

    def __init__(self, s: dict[str, Any], h: SimpleNamespace, mode: str = "sandbox") -> None:
        self.s, self.h, self.mode = s, h, mode
        self.receipts: list[str] = []
        self.counts: list[str] = []

    def _task(self, ttype: str, title: str) -> SandboxTaskResult:
        ref = f"19{uuid.uuid4().int % 10**8:08d}"
        tid = str(self.h.admin_sql(self.s["tenant"], "INSERT INTO field.task (tenant_id, site_id, type, status,"
                                                     " priority, title, ref_doc_no) VALUES (%s, %s, %s, 'pending',"
                                                     " 'normal', %s, %s) RETURNING id",
                                   (self.s["tenant"], self.s["site"], ttype, title, ref))[0][0])
        return {"task_id": tid, "ref_doc_no": ref}

    def create_receipt(self, principal: Principal, site_id: str) -> SandboxTaskResult:
        if self.mode != "sandbox":
            raise FieldError(status=403, code="FIELD-SBX-403-PRODUCTION", title="Production site")
        self.receipts.append(site_id)
        return self._task("receive", "Delivery home")

    def create_count(self, principal: Principal, site_id: str, storage_bin: str) -> SandboxTaskResult:
        self.counts.append(storage_bin)
        return self._task("count", f"Count bin {storage_bin}")

    def ports(self) -> AssistantPorts:
        return AssistantPorts(create_receipt=self.create_receipt, create_count=self.create_count)


def _bins(s: dict[str, Any], h: SimpleNamespace, codes: tuple[str, ...] = ("HOME-A", "HOME-B")) -> None:
    for c in codes:
        h.admin_sql(s["tenant"], "INSERT INTO field.location (tenant_id, site_id, kind, code, path, depth, erp_ref,"
                                 " erp_ref_type) VALUES (%s, %s, 'position', %s, %s, 1, %s, 'storage_bin')",
                    (s["tenant"], s["site"], c, f"/{c}", f"{s['plant']}/0001/{c}/{uuid.uuid4().hex[:6]}"))


def _close_all_jobs(s: dict[str, Any], h: SimpleNamespace) -> None:
    h.admin_sql(s["tenant"], "UPDATE field.task SET status = 'completed' WHERE site_id = %s", (s["site"],))


def test_new_home_receipt_creates_and_opens_it(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    sp = SandboxPorts(site, h)
    app.dependency_overrides[get_ports] = sp.ports
    r = turn(site, "utterance", text="start a home receipt")
    assert r["ai"] == "rules" and sp.receipts == [site["site"]]
    assert r["say"] == "New home receipt open. Look at each box's barcode and I'll add it."
    assert len(r["actions"]) == 1 and r["actions"][0]["type"] == "open_task"
    tid = r["actions"][0]["task_id"]
    assert h.admin_sql(site["tenant"], "SELECT type, status FROM field.task WHERE id = %s", (tid,)) == [
        ("receive", "pending")]
    rows = h.admin_sql(site["tenant"], "SELECT tool_calls, task_id::text FROM field.assistant_turn"
                                       " WHERE session_id = %s", (r["session_id"],))
    assert {"name": "new_receipt", "args": {}, "ok": True} in rows[0][0] and rows[0][1] == tid
    assert recorded_api.requests == []


def test_production_site_refuses_new_work_politely(site: dict[str, Any], recorded_api: Any,
                                                   h: SimpleNamespace) -> None:
    sp = SandboxPorts(site, h, mode="production")
    app.dependency_overrides[get_ports] = sp.ports
    _bins(site, h)
    for text in ("new home receipt", "count shelf HOME-A", "count a shelf"):
        r = turn(site, "utterance", text=text)
        assert r["ai"] == "rules" and r["say"].startswith("This is a production site") and r["actions"] == [
            {"type": "listen", "mode": "command"}], text
    assert sp.receipts == [] and sp.counts == [] and recorded_api.requests == []


def test_count_a_shelf_asks_which_then_creates(site: dict[str, Any], recorded_api: Any, h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    sp = SandboxPorts(site, h)
    app.dependency_overrides[get_ports] = sp.ports
    _bins(site, h)
    r = turn(site, "utterance", text="count a shelf")
    sid = r["session_id"]
    assert r["say"] == "Which shelf? Say HOME-A or HOME-B." and r["actions"] == [{"type": "listen", "mode": "free"}]
    r = turn(site, "utterance", text="the kitchen one", session_id=sid)
    assert r["say"].startswith("Which shelf?") and sp.counts == []  # unknown answer: asked again
    r = turn(site, "utterance", text="shelf b", session_id=sid)
    assert sp.counts == ["HOME-B"] and r["actions"][0]["type"] == "open_task"
    assert r["say"] == "Count of shelf HOME-B open. Look at each box's barcode and say how many."
    r = turn(site, "utterance", text="count shelf zebra", session_id=sid)
    assert r["say"].startswith("I don't know shelf zebra here.") and sp.counts == ["HOME-B"]
    r = turn(site, "scan", code="HOME-A", session_id=sid)  # the shelf's label answers "Which shelf?"
    assert sp.counts == ["HOME-B", "HOME-A"]
    r = turn(site, "utterance", text="count a shelf", session_id=sid)
    r = turn(site, "utterance", text="what do we have", session_id=sid)  # another request closes the dialog
    assert "jobs" in r["say"] and sp.counts == ["HOME-B", "HOME-A"]
    assert recorded_api.requests == []


def test_count_shelf_through_the_real_sandbox_service(site: dict[str, Any], h: SimpleNamespace) -> None:
    """get_ports as wired in production: field_api.sandbox.service.create_count (database only, no ERP call)."""
    h.set_sandbox(site)
    _bins(site, h)
    r = turn(site, "utterance", text="count shelf home a")
    assert r["ai"] == "rules" and r["say"].startswith("Count of shelf HOME-A open.")
    tid = r["actions"][0]["task_id"]
    rows = h.admin_sql(site["tenant"], "SELECT t.type, t.status, p.storage_bin, p.posting_blocked FROM field.task t"
                                       " JOIN field.pi_document p ON p.task_id = t.id WHERE t.id = %s", (tid,))
    assert rows == [("count", "pending", "HOME-A", False)]


def test_nothing_assigned_offers_new_work_on_sandbox_sites(site: dict[str, Any], recorded_api: Any,
                                                           h: SimpleNamespace) -> None:
    _close_all_jobs(site, h)
    sp = SandboxPorts(site, h)
    app.dependency_overrides[get_ports] = sp.ports
    r = turn(site, "session_start")
    assert r["say"] == "Hi. No open jobs at this site right now."  # production: nothing to offer
    h.set_sandbox(site)
    r = turn(site, "session_start")
    assert r["say"] == "Hi. Nothing is assigned here; say new home receipt, or count a shelf."
    assert r["card"] == {"title": "Nothing assigned", "body": "new home receipt · count a shelf"}
    sid = r["session_id"]
    for text in ("what's next", "what's most urgent", "how many left"):
        assert "new home receipt" in turn(site, "utterance", text=text, session_id=sid)["say"], text
    assert "new home receipt" in turn(site, "utterance", text="help", session_id=sid)["say"]
    r = turn(site, "utterance", text="new home receipt", session_id=sid)
    assert r["actions"][0]["type"] == "open_task" and sp.receipts == [site["site"]]
    assert recorded_api.requests == []


def test_new_work_failures_are_spoken(site: dict[str, Any], h: SimpleNamespace) -> None:
    h.set_sandbox(site)

    def refuse(principal: Principal, site_id: str) -> SandboxTaskResult:
        raise FieldError(status=502, code="FIELD-SBX-502-ERP", title="The ERP refused the sandbox action")

    def count(principal: Principal, site_id: str, storage_bin: str) -> SandboxTaskResult:
        raise FieldError(status=403, code="FIELD-AUTH-403-PERMISSION", title="Permission denied")

    app.dependency_overrides[get_ports] = lambda: AssistantPorts(create_receipt=refuse, create_count=count)
    _bins(site, h, ("HOME-A",))
    r = turn(site, "utterance", text="new home receipt")
    assert r["say"] == "I couldn't create the receipt. The ERP refused the sandbox action." and r["actions"] == []
    r = turn(site, "utterance", text="count a shelf")  # one shelf: no question
    assert r["say"] == "I couldn't start the count. Permission denied." and r["actions"] == []
    app.dependency_overrides[get_ports] = lambda: AssistantPorts()
    assert turn(site, "utterance", text="new home receipt")["say"] == "I can't create receipts in this build."
