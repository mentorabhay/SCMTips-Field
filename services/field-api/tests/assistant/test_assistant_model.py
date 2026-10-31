"""Field Assistant model client (M3 contract §4): Meta Model API first, Baseten fallback, budget guard on every call.

Driven through the recorded-response double of the HTTP API (conftest.RecordedAPI); the budget guard is real
(Postgres ops.ai_usage). These tests prove the client and the guard wiring, not the live API (UNVERIFIED).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from field_api.ai.budget import BudgetGuard
from field_api.assistant.model import (
    META_BASE_URL,
    META_MODEL,
    CallLog,
    ChatModel,
    ModelError,
    ModelRouter,
    ProviderConfig,
    baseten_config,
    build_router,
    estimate_tokens,
    meta_config,
    validate_model_id,
)

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
MSGS = [{"role": "user", "content": "Reply with OK."}]


def _usage_row(request_id: str) -> tuple[Any, ...]:
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT provider, model, status, reserved_usd, cost_usd, input_tokens, output_tokens,"
                    " cached_input_tokens FROM ops.ai_usage WHERE request_id = %s", (request_id,))
        rows = cur.fetchall()
    assert len(rows) == 1, rows
    return tuple(rows[0])


def _call(router: ModelRouter, rid: str, log: CallLog | None = None, errors: list[str] | None = None) -> Any:
    return router.chat(MSGS, tools=None, deadline=time.monotonic() + 6, tenant_id=None, request_id=rid,
                       log=log or CallLog(), errors=errors if errors is not None else [])


def test_defaults_are_the_contract_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("META_MODEL_API_BASE_URL", "ASSISTANT_MODEL", "BASETEN_BASE_URL", "BASETEN_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    cfg = meta_config()
    assert (cfg.provider, cfg.base_url, cfg.model, cfg.key_env) == ("meta", "https://api.meta.ai/v1",
                                                                    "muse-spark-1.2", "MODEL_API_KEY")
    assert META_BASE_URL == "https://api.meta.ai/v1" and META_MODEL == "muse-spark-1.2"
    assert baseten_config() is None and len(build_router().models) == 1
    monkeypatch.setenv("BASETEN_BASE_URL", "https://model-x.api.baseten.co/v1")
    monkeypatch.setenv("BASETEN_MODEL_ID", "some-model")
    fb = baseten_config()
    assert fb is not None and (fb.provider, fb.key_env) == ("baseten", "BASETEN_API_KEY")
    assert [m.provider for m in build_router().models] == ["meta", "baseten"]


def test_contributor_model_ids_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = "muse-spark-1.2" + "-contributor"
    with pytest.raises(ValueError):
        validate_model_id(bad)
    with pytest.raises(ValueError):
        ProviderConfig("meta", META_BASE_URL, bad, "MODEL_API_KEY")
    monkeypatch.setenv("ASSISTANT_MODEL", bad)
    monkeypatch.delenv("BASETEN_BASE_URL", raising=False)
    assert build_router().models == []  # refused: the turn falls back to rules


def test_success_settles_with_the_providers_usage_incl_cached(
        ai_on: None, recorded_api: Any, make_router: Callable[..., ModelRouter], h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer("OK", prompt=900, cached=600, completion=40)]
    log = CallLog()
    res = _call(make_router(), "t-ok-" + os.urandom(4).hex(), log)
    assert res.message["content"] == "OK" and res.provider == "meta" and res.model == "muse-spark-1.2"
    want = (Decimal(300) * Decimal("1.25") + Decimal(600) * Decimal("0.15") + Decimal(40) * Decimal("4.25")) / 10**6
    assert res.cost_usd == want == Decimal("0.000635") and log.cost_usd == want
    assert recorded_api.hosts == ["api.meta.ai/v1/chat/completions"]
    assert recorded_api.auth_headers == [f"Bearer {h.FAKE_KEY}"]
    sent = recorded_api.requests[0]
    assert sent["model"] == "muse-spark-1.2" and sent["max_tokens"] == 1024 and sent["messages"] == MSGS


def test_usage_row_records_tokens_and_cost(ai_on: None, recorded_api: Any, make_router: Callable[..., ModelRouter],
                                           h: SimpleNamespace) -> None:
    rid = "t-row-" + os.urandom(4).hex()
    recorded_api.script = [h.answer("OK", prompt=1000, cached=0, completion=100)]
    _call(make_router(), rid)
    provider, model, status, reserved, cost, tin, tout, tcached = _usage_row(rid)
    assert (provider, model, status, tin, tout, tcached) == ("meta", "muse-spark-1.2", "settled", 1000, 100, 0)
    assert Decimal(cost) == Decimal("0.001675") and Decimal(reserved) > 0  # 1000*1.25 + 100*4.25 per M


def test_no_key_and_ai_off_make_no_call_and_no_reservation(
        monkeypatch: pytest.MonkeyPatch, recorded_api: Any, make_router: Callable[..., ModelRouter]) -> None:
    h_errors: list[str] = []
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    with pytest.raises(ModelError):
        _call(make_router(), "t-off", errors=h_errors)
    assert h_errors == ["meta:AI_CLOUD_DISABLED"]
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    errs: list[str] = []
    with pytest.raises(ModelError):
        _call(make_router(), "t-nokey", errors=errs)
    assert errs == ["meta:AI_NO_KEY"] and recorded_api.requests == []
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.ai_usage WHERE request_id IN ('t-off', 't-nokey')")
        assert cur.fetchone() == (0,)


def test_budget_refusal_makes_no_call(ai_on: None, monkeypatch: pytest.MonkeyPatch, recorded_api: Any,
                                      make_router: Callable[..., ModelRouter]) -> None:
    spent = Decimal(BudgetGuard(prices={}).usage()["providers"]["meta"]["spent_usd"])
    monkeypatch.setenv("AI_BUDGET_META_USD", str(spent))  # no headroom
    errs: list[str] = []
    with pytest.raises(ModelError):
        _call(make_router(), "t-cap", errors=errs)
    assert errs == ["meta:AI_BUDGET_EXHAUSTED"] and recorded_api.requests == []


@pytest.mark.parametrize(("item", "code", "billed_reserved"), [
    (httpx.ReadTimeout, "AI_TIMEOUT", True),
    (httpx.ConnectError, "AI_TRANSPORT", True),
    (500, "AI_HTTP_500", False),
    (429, "AI_HTTP_429", False),
])
def test_failures_close_the_reservation(ai_on: None, recorded_api: Any, make_router: Callable[..., ModelRouter],
                                        h: SimpleNamespace, item: Any, code: str, billed_reserved: bool) -> None:
    rid = f"t-fail-{code}-{os.urandom(3).hex()}"
    recorded_api.script = [item]
    errs: list[str] = []
    log = CallLog()
    with pytest.raises(ModelError):
        _call(make_router(), rid, log, errs)
    assert errs == [f"meta:{code}"]
    _p, _m, status, reserved, cost, *_ = _usage_row(rid)
    assert status == "failed"
    assert Decimal(cost) == (Decimal(reserved) if billed_reserved else Decimal(0))
    assert Decimal(cost) == log.cost_usd.quantize(Decimal("0.000001"), ROUND_HALF_UP)  # ledger: 6 decimals
    assert h.FAKE_KEY not in str(errs) and h.FAKE_KEY not in str(log.calls)


def test_answer_without_usage_is_billed_at_the_reservation(ai_on: None, recorded_api: Any,
                                                           make_router: Callable[..., ModelRouter]) -> None:
    rid = "t-nousage-" + os.urandom(3).hex()
    recorded_api.script = [{"choices": [{"message": {"role": "assistant", "content": "OK"}}]}]
    with pytest.raises(ModelError):
        _call(make_router(), rid)
    _p, _m, status, reserved, cost, *_ = _usage_row(rid)
    assert status == "failed" and Decimal(cost) == Decimal(reserved)


def test_fallback_to_baseten_when_meta_fails(ai_on: None, monkeypatch: pytest.MonkeyPatch, recorded_api: Any,
                                             make_router: Callable[..., ModelRouter], h: SimpleNamespace) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-" + h.FAKE_KEY)
    recorded_api.script = [503, h.answer("OK from fallback", cached=0)]
    errs: list[str] = []
    res = _call(make_router(with_fallback=True), "t-fb-" + os.urandom(3).hex(), errors=errs)
    assert res.provider == "baseten" and res.message["content"] == "OK from fallback"
    assert errs == ["meta:AI_HTTP_503"]
    assert recorded_api.hosts == ["api.meta.ai/v1/chat/completions", "fallback.example.invalid/v1/chat/completions"]
    assert recorded_api.auth_headers[1] == f"Bearer baseten-{h.FAKE_KEY}"


def test_deadline_stops_the_router(ai_on: None, make_router: Callable[..., ModelRouter]) -> None:
    errs: list[str] = []
    with pytest.raises(ModelError):
        make_router().chat(MSGS, tools=None, deadline=time.monotonic(), tenant_id=None, request_id=None,
                           log=CallLog(), errors=errs)
    assert errs == ["AI_DEADLINE"]


def test_timeout_is_at_most_six_seconds(ai_on: None, h: SimpleNamespace) -> None:
    seen: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.extensions.get("timeout"))
        return httpx.Response(200, json=h.answer("OK"))

    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.2": h.META_PRICE}})
    m = ChatModel(ProviderConfig("meta", META_BASE_URL, "muse-spark-1.2", "MODEL_API_KEY"), guard,
                  httpx.MockTransport(handler))
    m.chat(MSGS, timeout_s=60)
    assert seen and all(v == 6.0 for v in seen[0].values())


def test_estimate_counts_images_generously() -> None:
    text = [{"role": "user", "content": "x" * 300}]
    image = [{"role": "user", "content": [{"type": "text", "text": "what"},
                                          {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}]}]
    assert estimate_tokens(text, None) >= 100
    assert estimate_tokens(image, None) >= 1600


def test_reply_cut_off_by_reasoning_falls_back_and_is_still_billed(
        ai_on: None, recorded_api: Any, make_router: Callable[..., ModelRouter]) -> None:
    """Owner's live call, 31 Oct 2026 (India, HTTP 200): with max_tokens 20 Muse spent 18 on reasoning and
    answered content null, finish_reason length. That is no answer: the turn must fall back, and the tokens count."""
    rid = "t-trunc-" + os.urandom(3).hex()
    recorded_api.script = [{"choices": [{"finish_reason": "length", "index": 0,
                                         "message": {"content": None, "refusal": None, "role": "assistant"}}],
                            "model": "muse-spark-1.2",
                            "usage": {"completion_tokens": 20, "prompt_tokens": 13, "total_tokens": 33,
                                      "completion_tokens_details": {"reasoning_tokens": 18},
                                      "prompt_tokens_details": {"cached_tokens": 0}}}]
    errs: list[str] = []
    with pytest.raises(ModelError) as e:
        _call(make_router(), rid, errors=errs)
    assert e.value.code == "AI_UNAVAILABLE" and errs == ["meta:AI_TRUNCATED"]  # the router tried every model
    _p, _m, _status, _reserved, cost, inp, out, _cached = _usage_row(rid)
    assert (inp, out) == (13, 20)
    exact = (Decimal(13) * Decimal("1.25") + Decimal(20) * Decimal("4.25")) / 10**6  # 0.00010125
    assert abs(Decimal(cost) - exact) < Decimal("0.000001")  # stored at six decimals


def test_output_cap_is_a_setting_within_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from field_api.assistant.model import MAX_OUTPUT_TOKENS, max_output_tokens

    monkeypatch.delenv("ASSISTANT_MAX_OUTPUT_TOKENS", raising=False)
    assert max_output_tokens() == MAX_OUTPUT_TOKENS == 1024
    for raw, want in (("2048", 2048), ("10", 64), ("99999", 4096), ("lots", 1024)):
        monkeypatch.setenv("ASSISTANT_MAX_OUTPUT_TOKENS", raw)
        assert max_output_tokens() == want

