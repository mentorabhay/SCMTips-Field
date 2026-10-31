"""`stack assistant-check` (M3 contract §4): one model call through the budget guard, one line, never the key.

The OK path runs against an httpx test double of the chat-completions API (the live Meta Model API is not
reachable from CI); the guard and its ledger are real.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from field_api.ai.budget import BudgetGuard, Price
from field_api.assistant.model import ChatModel, ModelRouter, ProviderConfig

from tools.dev_stack.assistant_check import check, load_env_local, run

pytestmark = pytest.mark.unit
KEY = "check-key-" + "y" * 20


def _router(status: int = 200) -> ModelRouter:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == f"Bearer {KEY}"
        body = {"choices": [{"message": {"role": "assistant", "content": "OK"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 0}}}
        return httpx.Response(status, json=body if status == 200 else {"error": "no"})

    guard = BudgetGuard(prices={"llama": {}, "baseten": {},
                                "meta": {"muse-spark-1.2": Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))}})
    return ModelRouter([ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.2", "MODEL_API_KEY"),
                                  guard, httpx.MockTransport(handler))])


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    monkeypatch.setenv("AI_BUDGET_META_USD", str(Decimal(usage["providers"]["meta"]["spent_usd"]) + 1))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + 1))
    monkeypatch.setenv("MODEL_API_KEY", KEY)


def test_ok_line(enabled: None) -> None:
    line = check(_router())
    assert re.fullmatch(r"assistant-check: OK model=muse-spark-1\.2 latency_ms=\d+ cost_usd=0\.\d{6}", line), line
    assert KEY not in line and "Reply with" not in line


def test_blocked_lines(enabled: None, monkeypatch: pytest.MonkeyPatch) -> None:
    assert check(_router(401)) == "assistant-check: BLOCKED meta:AI_HTTP_401"
    monkeypatch.delenv("MODEL_API_KEY")
    assert check(_router()) == "assistant-check: BLOCKED meta:AI_NO_KEY"
    assert check(ModelRouter([])) == "assistant-check: BLOCKED no model configured"
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    assert check(_router()).startswith("assistant-check: BLOCKED AI_CLOUD_DISABLED")


def test_run_prints_one_line_and_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    assert run([]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("assistant-check: BLOCKED")


def test_env_local_fills_only_missing_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env.local"
    env.write_text("# comment\nAI_CHECK_A=one\nexport AI_CHECK_B=\"two\"\nAI_CHECK_C=three\n", encoding="utf-8")
    monkeypatch.delenv("AI_CHECK_A", raising=False)
    monkeypatch.delenv("AI_CHECK_B", raising=False)
    monkeypatch.setenv("AI_CHECK_C", "kept")
    names = load_env_local(env)
    assert names == ["AI_CHECK_A", "AI_CHECK_B"] and json.dumps(names).count("one") == 0
    assert (os.environ["AI_CHECK_A"], os.environ["AI_CHECK_B"], os.environ["AI_CHECK_C"]) == ("one", "two", "kept")
    for n in names:
        monkeypatch.delenv(n)
