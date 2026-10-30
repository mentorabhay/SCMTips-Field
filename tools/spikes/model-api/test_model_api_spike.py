"""Model API spike harness (T1.062 / TC1.151 / FR1.055).

The harness makes real HTTP calls; these tests drive it through httpx.MockTransport so that the
measurement and refusal logic is exercised without spending credits. They prove the harness, not
the API: TC1.151 itself is recorded only by a real run (results.json).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from field_api.ai.budget import BudgetGuard, Price
from hypothesis import given
from hypothesis import strategies as st

from tools.spikes.model_api_harness import MAX_CALLS, main, percentile, run_spike, validate_model_id


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch) -> BudgetGuard:
    """A real budget guard (Postgres) with a test price and generous caps above current spend."""
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    spent = Decimal(BudgetGuard(prices={}).usage()["providers"]["llama"]["spent_usd"])
    today = Decimal(BudgetGuard(prices={}).usage()["today_usd"])
    monkeypatch.setenv("AI_BUDGET_LLAMA_USD", str(spent + 1))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(today + 1))
    return BudgetGuard(prices={"llama": {"m": Price(Decimal("0.1"), Decimal("0.1"))}, "baseten": {}})


def _client(status: int, counter: list[int]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        counter.append(1)
        assert req.headers["authorization"].startswith("Bearer ")
        ok = {"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 9, "completion_tokens": 1}}
        return httpx.Response(status, json=ok if status == 200 else {"error": "x"})

    return httpx.Client(base_url="https://example.invalid/v1", transport=httpx.MockTransport(handler))


@pytest.mark.unit
def test_t1_062_refuses_contributor_models() -> None:
    for bad in ("muse-spark-1.3-contributor", "MUSE-CONTRIBUTOR-V1"):
        with pytest.raises(ValueError, match="-contributor"):
            validate_model_id(bad)
    validate_model_id("muse-spark-1.3")


@pytest.mark.unit
def test_t1_062_without_key_records_blocked_and_no_numbers(guard: BudgetGuard) -> None:
    n: list[int] = []
    s = run_spike("m", "hi", client=_client(200, n), api_key=None, calls=5, guard=guard)
    assert s.status == "BLOCKED" and s.p50_latency_ms is None and s.calls == [] and n == []


@pytest.mark.unit
def test_t1_062_measures_real_calls_and_caps_count(guard: BudgetGuard) -> None:
    n: list[int] = []
    s = run_spike("m", "hi", client=_client(200, n), api_key="k", calls=MAX_CALLS, guard=guard)
    assert s.status == "VERIFIED" and len(n) == MAX_CALLS and len(s.calls) == MAX_CALLS
    assert s.p50_latency_ms is not None and s.p95_latency_ms is not None and s.p50_latency_ms <= s.p95_latency_ms
    with pytest.raises(ValueError):
        run_spike("m", "hi", client=_client(200, n), api_key="k", calls=MAX_CALLS + 1, guard=guard)


@pytest.mark.unit
def test_t1_062_stops_after_refusal(guard: BudgetGuard) -> None:
    n: list[int] = []
    s = run_spike("m", "hi", client=_client(403, n), api_key="k", calls=MAX_CALLS, guard=guard)
    assert s.status == "BLOCKED" and len(n) == 1 and "HTTP 403" in s.reason


@pytest.mark.unit
def test_t1_062_every_call_goes_through_the_budget_guard(guard: BudgetGuard, monkeypatch: pytest.MonkeyPatch) -> None:
    before = Decimal(guard.usage()["providers"]["llama"]["spent_usd"])
    n: list[int] = []
    run_spike("m", "hi", client=_client(200, n), api_key="k", calls=3, guard=guard)
    assert Decimal(guard.usage()["providers"]["llama"]["spent_usd"]) - before == Decimal("0.000003")  # 3 x 10 tok
    monkeypatch.setenv("AI_BUDGET_LLAMA_USD", str(before))  # no headroom left
    s = run_spike("m", "hi", client=_client(200, n), api_key="k", calls=3, guard=guard)
    assert s.status == "BLOCKED" and "AI_BUDGET_EXHAUSTED" in s.reason and len(n) == 3


@pytest.mark.unit
def test_t1_062_refuses_to_spend_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    assert main(["--model", "m"]) == 2


@pytest.mark.property
@given(st.lists(st.floats(min_value=0, max_value=1e5, allow_nan=False), min_size=1, max_size=50))
def test_t1_062_percentile_is_a_measured_value_and_monotone(xs: list[float]) -> None:
    p50, p95 = percentile(xs, 50), percentile(xs, 95)
    assert p50 in xs and p95 in xs and p50 <= p95 <= max(xs)
