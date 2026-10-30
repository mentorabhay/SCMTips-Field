"""AI budget guard (A-02): hard caps on paid calls, enforced in Postgres under an advisory lock."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard, BudgetRefused, Price, load_prices
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from hypothesis import given, settings
from hypothesis import strategies as st

PRICE = Price(Decimal("1.00"), Decimal("4.00"))  # $ per million tokens (test values)


def _guard(model: str) -> BudgetGuard:
    return BudgetGuard(prices={"llama": {model: PRICE}, "baseten": {}})


def _spent(provider: str = "llama") -> Decimal:
    return Decimal(BudgetGuard(prices={}).usage()["providers"][provider]["spent_usd"])


def _today() -> Decimal:
    return Decimal(BudgetGuard(prices={}).usage()["today_usd"])


@pytest.fixture
def caps(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str], None]:
    """Caps relative to what is already recorded, so runs don't interfere."""
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")

    def set_caps(provider_headroom: str, daily_headroom: str) -> None:
        monkeypatch.setenv("AI_BUDGET_LLAMA_USD", str(_spent() + Decimal(provider_headroom)))
        monkeypatch.setenv("AI_BUDGET_BASETEN_USD", "0")
        monkeypatch.setenv("AI_DAILY_CAP_USD", str(_today() + Decimal(daily_headroom)))

    return set_caps


def test_refuses_when_cloud_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    with pytest.raises(BudgetRefused) as e:
        _guard("m").reserve("llama", "m", input_tokens=10, max_output_tokens=10, purpose="t")
    assert e.value.code == "AI_CLOUD_DISABLED"


def test_refuses_unpriced_model_and_unset_caps(caps: Callable[[str, str], None], monkeypatch: pytest.MonkeyPatch) -> None:
    caps("1", "1")
    with pytest.raises(BudgetRefused) as e:
        _guard("m").reserve("llama", "other-model", input_tokens=1, max_output_tokens=1, purpose="t")
    assert e.value.code == "AI_PRICE_UNKNOWN"
    monkeypatch.delenv("AI_DAILY_CAP_USD")
    with pytest.raises(BudgetRefused) as e:
        _guard("m").reserve("llama", "m", input_tokens=1, max_output_tokens=1, purpose="t")
    assert e.value.code == "AI_CAP_UNSET"


def test_reserve_settle_and_cap(caps: Callable[[str, str], None]) -> None:
    caps("0.010", "1")
    g = _guard("m")
    before = _spent()
    r = g.reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")  # worst case $0.005
    assert r.reserved_usd == Decimal("0.005")
    assert _spent() == before + Decimal("0.005")
    assert g.settle(r, input_tokens=1000, output_tokens=250) == Decimal("0.002")
    assert _spent() == before + Decimal("0.002")
    g.reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")  # 0.007 total
    with pytest.raises(BudgetRefused) as e:  # 0.012 > 0.010
        g.reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")
    assert e.value.code == "AI_BUDGET_EXHAUSTED"
    with pytest.raises(RuntimeError):
        g.settle(r, input_tokens=1, output_tokens=1)  # already closed


def test_daily_cap_spans_providers(caps: Callable[[str, str], None]) -> None:
    caps("1", "0.004")
    with pytest.raises(BudgetRefused) as e:
        _guard("m").reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")
    assert e.value.code == "AI_DAILY_CAP"


def test_failed_call_counts_only_what_was_billed(caps: Callable[[str, str], None]) -> None:
    caps("1", "1")
    g = _guard("m")
    before = _spent()
    r = g.reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")
    g.fail(r, billed_usd=Decimal("0.001"))
    assert _spent() == before + Decimal("0.001")


def test_concurrent_reservations_never_overspend(caps: Callable[[str, str], None]) -> None:
    caps("0.050", "1")  # room for exactly 10 calls of $0.005
    g = _guard("m")
    before = _spent()
    ok: list[int] = []
    refused: list[int] = []

    def worker() -> None:
        try:
            g.reserve("llama", "m", input_tokens=1000, max_output_tokens=1000, purpose="t")
            ok.append(1)
        except BudgetRefused:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 10 and len(refused) == 6
    assert _spent() - before == Decimal("0.050")


@settings(max_examples=50, deadline=None)
@given(st.integers(0, 10**7), st.integers(0, 10**7))
def test_price_cost_is_linear_and_non_negative(tin: int, tout: int) -> None:
    c = PRICE.cost(tin, tout)
    assert c >= 0 and c == PRICE.cost(tin, 0) + PRICE.cost(0, tout)


def test_pricing_file_loads_with_non_negative_prices() -> None:
    prices = load_prices()
    assert set(prices) == {"llama", "baseten"}
    assert all(p.input_per_mtok >= 0 and p.output_per_mtok >= 0 for m in prices.values() for p in m.values())


def test_ai_usage_endpoint_needs_system_read() -> None:
    c = TestClient(app)
    op = create_dev_token("op", str(uuid.uuid4()), ["field.operator"])
    assert c.get("/v1/system/ai-usage", headers={"Authorization": f"Bearer {op}"}).status_code == 403
    sup = create_dev_token("sup", str(uuid.uuid4()), ["field.supervisor"])
    r = c.get("/v1/system/ai-usage", headers={"Authorization": f"Bearer {sup}"})
    assert r.status_code == 200 and set(r.json()["providers"]) == {"llama", "baseten"}
