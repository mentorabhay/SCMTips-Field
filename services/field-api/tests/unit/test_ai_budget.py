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
    assert set(prices) == {"llama", "baseten", "meta"}
    assert all(p.input_per_mtok >= 0 and p.output_per_mtok >= 0 for m in prices.values() for p in m.values())
    assert all(p.cached_input_per_mtok is None or p.cached_input_per_mtok >= 0
               for m in prices.values() for p in m.values())


def test_ai_usage_endpoint_needs_system_read() -> None:
    c = TestClient(app)
    op = create_dev_token("op", str(uuid.uuid4()), ["field.operator"])
    assert c.get("/v1/system/ai-usage", headers={"Authorization": f"Bearer {op}"}).status_code == 403
    sup = create_dev_token("sup", str(uuid.uuid4()), ["field.supervisor"])
    r = c.get("/v1/system/ai-usage", headers={"Authorization": f"Bearer {sup}"})
    assert r.status_code == 200 and set(r.json()["providers"]) == {"llama", "baseten", "meta"}


# --------------------------------------------------------------------------- M3: Meta Model API provider
MUSE = Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))


def test_pricing_file_has_muse_spark_with_cached_input() -> None:
    """config/ai_pricing.yaml (M3 contract §4): muse-spark-1.2 at 1.25 / cached 0.15 / 4.25 USD per million."""
    assert load_prices()["meta"]["muse-spark-1.2"] == MUSE


def test_cached_input_tokens_are_billed_at_the_cached_rate() -> None:
    assert MUSE.cost(1_000_000, 0) == Decimal("1.25")
    assert MUSE.cost(1_000_000, 0, cached_input_tokens=1_000_000) == Decimal("0.15")
    assert MUSE.cost(1_000_000, 1_000_000, cached_input_tokens=400_000) == Decimal("0.75") + Decimal("0.06") + Decimal("4.25")
    assert PRICE.cost(1000, 0, cached_input_tokens=1000) == PRICE.cost(1000, 0)  # no cached rate: normal input rate
    with pytest.raises(ValueError):
        MUSE.cost(10, 0, cached_input_tokens=11)


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 10**7), st.integers(0, 10**6), st.integers(0, 10**7))
def test_cached_cost_never_exceeds_uncached(tin: int, tout: int, cached_part: int) -> None:
    cached = min(cached_part, tin)
    assert 0 <= MUSE.cost(tin, tout, cached) <= MUSE.cost(tin, tout)


def test_meta_provider_has_its_own_cap_and_records_cached_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    spent = _spent("meta")
    monkeypatch.setenv("AI_BUDGET_META_USD", str(spent + Decimal("0.010")))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(_today() + Decimal("1")))
    g = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.2": MUSE}})
    r = g.reserve("meta", "muse-spark-1.2", input_tokens=1000, max_output_tokens=300, purpose="t")
    assert r.reserved_usd == Decimal("0.002525")  # worst case, no cache hit: 1000 x 1.25 + 300 x 4.25 per M
    cost = g.settle(r, input_tokens=1000, output_tokens=100, cached_input_tokens=800)
    assert cost == (Decimal(200) * Decimal("1.25") + Decimal(800) * Decimal("0.15") + Decimal(100) * Decimal("4.25")) / 10**6
    assert _spent("meta") == spent + cost.quantize(Decimal("0.000001"))
    monkeypatch.delenv("AI_BUDGET_META_USD")
    with pytest.raises(BudgetRefused) as e:
        g.reserve("meta", "muse-spark-1.2", input_tokens=1, max_output_tokens=1, purpose="t")
    assert e.value.code == "AI_CAP_UNSET"
    usage = BudgetGuard(prices={}).usage()
    assert usage["providers"]["meta"]["spent_usd"] is not None
