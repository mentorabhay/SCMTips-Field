"""Spoken answers ask Meta's model for minimal reasoning (hosting TO_FIELD §14, 2 Nov: the decision brief timed out on
the host and the template was spoken instead). Baseten never gets the field; the brief deadline can be tuned by env."""

from __future__ import annotations

import time
from typing import Any, cast

import pytest
from field_api.assistant import model
from field_api.briefs import service as briefs


class Fake:
    def __init__(self, provider: str) -> None:
        self.cfg = type("Cfg", (), {"provider": provider})()
        self.seen: dict[str, Any] = {}

    @property
    def provider(self) -> str:
        return str(self.cfg.provider)

    def chat(self, messages: Any, **kw: Any) -> str:
        self.seen = kw
        return "ok"


def test_spoken_effort_defaults_to_minimal_and_takes_a_valid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOKEN_REASONING_EFFORT", raising=False)
    assert model.spoken_reasoning_effort() == "minimal"
    monkeypatch.setenv("SPOKEN_REASONING_EFFORT", "LOW")
    assert model.spoken_reasoning_effort() == "low"
    monkeypatch.setenv("SPOKEN_REASONING_EFFORT", "none")  # Meta answers 400 for "none" (Gate 0)
    assert model.spoken_reasoning_effort() == "minimal"


def test_router_sends_reasoning_effort_to_meta_only() -> None:
    meta, baseten = Fake("meta"), Fake("baseten")
    log = cast(model.CallLog, None)
    for fake, want in ((meta, "minimal"), (baseten, None)):
        router = model.ModelRouter([cast(model.ChatModel, fake)])
        router.chat([], tools=None, deadline=time.monotonic() + 5, tenant_id=None, request_id=None, log=log,
                    errors=[], reasoning_effort="minimal")
        assert fake.seen["reasoning_effort"] == want


def test_brief_deadline_env_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIEF_DEADLINE_S", raising=False)
    assert briefs.brief_deadline_s() == 4.0
    for raw, want in (("6", 6.0), ("1", 2.0), ("30", 8.0), ("x", 4.0), ("nan", 4.0)):
        monkeypatch.setenv("BRIEF_DEADLINE_S", raw)
        assert briefs.brief_deadline_s() == want
