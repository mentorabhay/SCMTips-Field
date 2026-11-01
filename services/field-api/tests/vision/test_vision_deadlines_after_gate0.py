"""M5-V02: look deadlines raised after the owner's Gate 0 from India (1 Nov 2026,
docs/evidence/2026-11-01-m5-gate0-093109.txt: SAM 3.1 about 5 s, a Muse Spark image read over 7.7 s), while the
assistant keeps its 6 s per-call cap."""

from __future__ import annotations

import pytest

from field_api.assistant.model import CALL_TIMEOUT_S
from field_api.vision import settings


def test_look_deadlines_default_above_the_measured_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VISION_INSTANCES_DEADLINE_S", "VISION_LABELS_DEADLINE_S", "VISION_FALLBACK_DEADLINE_S"):
        monkeypatch.delenv(name, raising=False)
    assert settings.instances_deadline_s() == 15.0 > 4.958  # SAM 3.1, measured 4958 ms
    assert settings.labels_deadline_s() == 30.0 > 7.733  # Muse image read, timed out at 7733 ms
    assert settings.fallback_deadline_s() == 15.0


def test_look_deadlines_are_clamped_to_the_vision_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_LABELS_DEADLINE_S", "600")
    assert settings.labels_deadline_s() == settings.VISION_CALL_CAP_S == 60.0
    monkeypatch.setenv("VISION_INSTANCES_DEADLINE_S", "0.01")
    assert settings.instances_deadline_s() == 0.5


def test_the_assistant_keeps_its_own_six_second_cap() -> None:
    assert CALL_TIMEOUT_S == 6.0 < settings.VISION_CALL_CAP_S
