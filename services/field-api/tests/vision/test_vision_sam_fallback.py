"""M5-V02 fix after the hosted look of 1 Nov: SAM 3.1 found 0 of 8 packs for the prompt "pack" (and at Gate 0 "pack"
found 0 where "box" found 7 of 7). The instances stage now retries once with a fallback word inside the same deadline;
the spoken unit stays the case's noun."""

from __future__ import annotations

from typing import Any

import pytest
from field_api.assistant.model import ModelError
from field_api.vision import service
from field_api.vision.image import Capture
from field_api.vision.ports import CallContext, FoundInstance

CAP = Capture(jpeg=b"\xff\xd8", width=1600, height=1200)
ONE = FoundInstance(box=(10, 10, 100, 100), score=0.9)


class FakeSam:
    model = "sam-3.1"

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, float]] = []

    def find(self, image_jpeg: bytes, width: int, height: int, prompt: str, *, timeout_s: float,
             ctx: CallContext) -> list[FoundInstance]:
        self.asked.append((prompt, timeout_s))
        a = self.answers.get(prompt, [])
        if isinstance(a, Exception):
            raise a
        return list(a)


def test_m5_v02_sam_prompts_have_one_fallback_at_most() -> None:
    assert service.sam_prompts("pack") == ["pack", "box"]
    assert service.sam_prompts(" Box ") == ["box", "package"]
    assert service.sam_prompts("crate") == ["crate"]


def test_m5_v02_pack_finds_nothing_so_box_is_tried_and_counted() -> None:
    sam, reasons = FakeSam({"pack": [], "box": [ONE, ONE]}), []
    got = service.find_instances(sam, CAP, "pack", 15.0, CallContext(None, None), reasons)
    assert len(got) == 2 and [p for p, _ in sam.asked] == ["pack", "box"]
    assert reasons == ["instances:retry:box", "instances:prompt:box"]
    assert sam.asked[1][1] <= 15.0


def test_m5_v02_first_word_found_means_no_retry() -> None:
    sam, reasons = FakeSam({"pack": [ONE]}), []
    assert len(service.find_instances(sam, CAP, "pack", 15.0, CallContext(None, None), reasons)) == 1
    assert [p for p, _ in sam.asked] == ["pack"] and reasons == []


def test_m5_v02_no_time_left_or_a_failed_retry_keeps_the_empty_answer() -> None:
    sam, reasons = FakeSam({"pack": []}), []
    assert service.find_instances(sam, CAP, "pack", 0.5, CallContext(None, None), reasons) == []
    assert reasons == ["instances:retry:no_time"]
    sam, reasons = FakeSam({"pack": [], "box": ModelError("AI_TIMEOUT")}), []
    assert service.find_instances(sam, CAP, "pack", 15.0, CallContext(None, None), reasons) == []
    assert reasons == ["instances:retry:box", "instances:retry:AI_TIMEOUT"]


def test_m5_v02_an_error_on_the_first_word_still_propagates() -> None:
    sam = FakeSam({"pack": ModelError("AI_HTTP_500")})
    with pytest.raises(ModelError):
        service.find_instances(sam, CAP, "pack", 15.0, CallContext(None, None), [])
