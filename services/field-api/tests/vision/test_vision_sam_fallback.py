"""The instances stage's words (M5-V02, then M5-V11 after the hosted looks of 3-4 Nov 2026).

M5-V02: SAM 3.1 found 0 of 8 packs for "pack" on 1 Nov, so a fallback word was tried. M5-V11: on the owner's real
biscuit packs "pack" and "box" both found 0 of 5 while "package" found 5 of 5 (and 8 of 8 on the SAMPLE photo), and
Muse Spark named the goods and estimated their count exactly. So the stage has two layers: SAM on the case's noun with
Muse naming the goods in parallel, then SAM on the generic words and the named nouns when the first answer is empty or
disagrees with the estimate. The answer nearest the estimate is kept; the spoken unit stays the case's noun."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from field_api.assistant.model import ModelError
from field_api.vision import service
from field_api.vision.image import Capture
from field_api.vision.ports import CallContext, FoundInstance, Naming

CAP = Capture(jpeg=b"\xff\xd8", width=1600, height=1200)


def boxes(n: int, score: float = 0.9) -> list[FoundInstance]:
    return [FoundInstance(box=(10 + 20 * i, 10, 25 + 20 * i, 100), score=score) for i in range(n)]


class FakeSam:
    model = "sam-3.1"

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, float]] = []
        self.lock = threading.Lock()

    def find(self, image_jpeg: bytes, width: int, height: int, prompt: str, *, timeout_s: float,
             ctx: CallContext) -> list[FoundInstance]:
        with self.lock:
            self.asked.append((prompt, timeout_s))
        a = self.answers.get(prompt, [])
        if isinstance(a, Exception):
            raise a
        return list(a)

    def words(self) -> list[str]:
        return [p for p, _ in self.asked]


class FakeNamer:
    model = "muse-spark-1.3"

    def __init__(self, answer: Naming | Exception) -> None:
        self.answer = answer
        self.asked: list[float] = []

    def name(self, image_jpeg: bytes, *, timeout_s: float, ctx: CallContext) -> Naming:
        self.asked.append(timeout_s)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def run(sam: FakeSam, namer: FakeNamer | None = None, deadline: float = 15.0) -> tuple[list[FoundInstance], list[str]]:
    reasons: list[str] = []
    return service.find_instances(sam, CAP, "pack", deadline, CallContext(None, None), reasons, namer), reasons


def test_m5_v11_sam_prompts_are_the_noun_then_the_generic_words() -> None:
    assert service.sam_prompts("pack") == ["pack", "package", "box"]
    assert service.sam_prompts(" Box ") == ["box", "package"]
    assert service.sam_prompts("package") == ["package", "box"]


def test_m5_v11_estimate_agrees_within_one_or_ten_percent() -> None:
    assert service.estimate_agrees(5, None) and service.estimate_agrees(4, 5) and service.estimate_agrees(6, 5)
    assert not service.estimate_agrees(3, 5) and not service.estimate_agrees(0, 5)
    assert service.estimate_agrees(18, 20) and not service.estimate_agrees(17, 20)


def test_m5_v11_choose_answer_prefers_the_estimate_then_the_score() -> None:
    answers = [("box", boxes(8, 0.6)), ("package", boxes(8, 0.88)), ("packet", boxes(3, 0.95))]
    assert service.choose_answer(answers, 8)[0] == "package"
    assert service.choose_answer(answers, 3)[0] == "packet"
    assert service.choose_answer(answers, None)[0] == "package"  # most instances, then the higher mean score
    assert service.choose_answer([("pack", []), ("box", [])], 5) is None


# --- without a namer (VISION_NAMING=false, or the tests' default ports) ---------------------------------------------

def test_m5_v02_first_word_found_means_no_retry() -> None:
    sam = FakeSam({"pack": boxes(1)})
    got, reasons = run(sam)
    assert len(got) == 1 and sam.words() == ["pack"] and reasons == []


def test_m5_v11_pack_finds_nothing_so_package_and_box_are_tried_at_once() -> None:
    sam = FakeSam({"pack": [], "package": boxes(5, 0.95), "box": boxes(2, 0.6)})
    got, reasons = run(sam)
    assert len(got) == 5 and sam.words()[0] == "pack" and sorted(sam.words()[1:]) == ["box", "package"]
    assert reasons == ["instances:retry:package,box", "instances:prompt:package"]
    assert all(t <= 15.0 for _, t in sam.asked)


def test_m5_v02_no_time_left_or_failed_retries_keep_the_empty_answer() -> None:
    sam = FakeSam({"pack": []})
    assert run(sam, deadline=0.5) == ([], ["instances:retry:no_time"])
    sam = FakeSam({"pack": [], "package": ModelError("AI_TIMEOUT"), "box": []})
    got, reasons = run(sam)
    assert got == [] and reasons == ["instances:retry:package,box", "instances:retry:package:AI_TIMEOUT"]


def test_m5_v02_an_error_on_the_first_word_still_propagates() -> None:
    with pytest.raises(ModelError):
        run(FakeSam({"pack": ModelError("AI_HTTP_500")}))
    namer = FakeNamer(Naming(("packet",), 5))
    with pytest.raises(ModelError):
        run(FakeSam({"pack": ModelError("AI_HTTP_500")}), namer)
    assert len(namer.asked) == 1  # the naming call ran (and is recorded); the look answers by rules


# --- with the namer (layer 1) ---------------------------------------------------------------------------------------

def test_m5_v11_owner_photo_pack_and_box_empty_package_matches_the_estimate() -> None:
    """The hosted look of 3 Nov 23:58 IST: "pack" 0, "box" 0, "package" 5; Muse said "packet", about 5."""
    sam = FakeSam({"pack": [], "package": boxes(5, 0.94), "box": [], "packet": boxes(5, 0.84)})
    got, reasons = run(sam, FakeNamer(Naming(("packet", "package", "pouch"), 5)))
    assert len(got) == 5
    assert "packet" not in sam.words()  # package already agrees with the estimate: no third round
    assert reasons == ["instances:retry:package,box", "instances:named:packet~5", "instances:prompt:package"]


def test_m5_v11_sample_photo_the_named_noun_alone_would_fail() -> None:
    """The try page's SAMPLE photo: Muse said "packet" (SAM: 0), "box" found 8 at 0.6, "package" 8 at 0.88."""
    sam = FakeSam({"pack": [], "package": boxes(8, 0.88), "box": boxes(8, 0.6), "packet": []})
    got, reasons = run(sam, FakeNamer(Naming(("packet", "pack", "pouch"), 8)))
    assert len(got) == 8 and all(f.score == 0.88 for f in got)
    assert reasons[-1] == "instances:prompt:package"


def test_m5_v11_first_answer_agrees_so_one_sam_call() -> None:
    sam = FakeSam({"pack": boxes(5)})
    got, reasons = run(sam, FakeNamer(Naming(("packet",), 5)))
    assert len(got) == 5 and sam.words() == ["pack"] and reasons == ["instances:named:packet~5"]


def test_m5_v11_first_answer_disagrees_so_layer_two_runs_and_the_nearest_wins() -> None:
    sam = FakeSam({"pack": boxes(2), "package": boxes(5, 0.8), "box": boxes(9, 0.9)})
    got, reasons = run(sam, FakeNamer(Naming(("packet",), 5)))
    assert len(got) == 5
    assert reasons == ["instances:named:packet~5", "instances:retry:package,box", "instances:prompt:package"]
    assert "packet" not in sam.words()  # "package" agrees with the estimate: the named noun is not needed


def test_m5_v11_named_nouns_are_tried_when_nothing_agrees() -> None:
    sam = FakeSam({"pack": [], "package": [], "box": [], "bottle": boxes(6)})
    got, reasons = run(sam, FakeNamer(Naming(("bottle", "jar"), 6)))
    assert len(got) == 6 and sorted(sam.words()[3:]) == ["bottle", "jar"]
    assert reasons == ["instances:retry:package,box", "instances:named:bottle~6", "instances:retry:bottle,jar",
                       "instances:prompt:bottle"]


def test_m5_v11_a_count_that_still_disagrees_is_said_in_the_reasons() -> None:
    sam = FakeSam({"pack": boxes(3)})
    got, reasons = run(sam, FakeNamer(Naming(("pack",), 8)))
    assert len(got) == 3 and reasons[-1] == "instances:estimate:3/8"


def test_m5_v11_a_failed_naming_call_keeps_layer_two_without_an_estimate() -> None:
    sam = FakeSam({"pack": [], "package": boxes(4), "box": boxes(4, 0.5)})
    got, reasons = run(sam, FakeNamer(ModelError("AI_TIMEOUT")))
    assert len(got) == 4
    assert reasons == ["instances:retry:package,box", "instances:naming:AI_TIMEOUT", "instances:prompt:package"]


def test_m5_v11_the_naming_call_is_capped_by_its_own_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_NAMING_DEADLINE_S", "4")
    namer = FakeNamer(Naming(("packet",), 1))
    run(FakeSam({"pack": boxes(1)}), namer)
    assert namer.asked == [4.0]
