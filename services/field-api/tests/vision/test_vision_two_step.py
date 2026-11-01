"""M5-S01: the two-step look. POST /v1/vision/looks answers once SAM's instances are counted (``final`` false, source
partial, the count only, say "<count>. Reading the labels."); the label read runs after the answer and GET
/v1/vision/looks/{id} then answers the final look (``final`` true, the full say and ``say_next``). Label failure,
time-out, an error or an unfinished read past its due time (a restart) all end the look in a definite partial state.
A claim is refused (409) while the labels are read. On Postgres with RLS, the real captures API and budget guard, and
the SAM 3.1 / Muse adapters over the test double of the Meta API (test code only)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import verify_token
from field_api.briefs.numbers import values
from field_api.vision import service as svc
from field_api.vision.ports import CallContext, LabelRead, VisionPorts
from field_api.vision.reconcile import Expectation
from field_api.vision.say import LABELS_FAILED_SAY, PENDING_SAY, first_say, next_say
from field_api.vision.service import get_vision_ports

pytestmark = pytest.mark.unit

C1_LABELS = {n: {"pieces_per_unit": 12} for n in range(1, 21)}
C1_LABELS[7] = {"pieces_per_unit": 10}
C1_LABELS[12] = {"pieces_per_unit": 10}
C1_LABELS[3] = {**C1_LABELS[3], "damaged": True, "damage_note": "crushed corner"}
C1_LABELS[18] = {**C1_LABELS[18], "damaged": True, "damage_note": "torn"}


def _get(client: TestClient, s: dict[str, Any], look_id: str) -> dict[str, Any]:
    r = client.get(f"/v1/vision/looks/{look_id}", headers={"Authorization": f"Bearer {s['dev']}"})
    assert r.status_code == 200, r.text
    return dict(r.json())


def _deferred(client: TestClient, s: dict[str, Any], v: SimpleNamespace, ports: VisionPorts, key: str,
              case: str = "grocery") -> tuple[dict[str, Any], list[Callable[[], None]]]:
    """A look through the service with the label read held back (as the route's background task would run it)."""
    cap = v.upload_capture(client, s, v.photo(v.grid_boxes(20)))
    held: list[Callable[[], None]] = []
    first = svc.create_look(verify_token(s["dev"]), svc.LookIn(task_id=s["receive"], line_id=s["line"], capture_id=cap,
                                                               case=case), key, ports, defer=held.append)
    return first, held


def test_m5_s01_first_answer_counts_then_get_answers_the_final_look(client: TestClient, site: dict[str, Any],
                                                                     v: SimpleNamespace, ai_on: None) -> None:
    """The first answer has the count and outlines, no labels, nothing proposed, and a number-checked say; until the
    label read runs, GET answers the same first answer; after it, the final look with say_next (what follows the
    count the operator already heard). The label read is the only thing deferred: SAM is called once."""
    v.add_case_line(site, "grocery", ppu=12)
    double = v.VisionDouble(boxes=v.grid_boxes(20), labels=C1_LABELS)
    first, held = _deferred(client, site, v, v.ports_for(double), "two-step-1")
    assert first["final"] is False and first["source"] == "partial" and first["say_next"] is None
    assert first["counts"] == {"expected": 20, "seen": 20, "damaged": None, "good": None}
    assert first["proposal"] == {"receive": None, "flag": None, "reasons": []}
    assert first["pack"] is None and first["expiry"] is None and first["reasons"] == []
    assert [i["n"] for i in first["instances"]] == list(range(1, 21))
    assert all(i["label"]["read"] is False and i["damaged"] is False for i in first["instances"])
    assert first["say"] == "20 of 20 packs. Reading the labels."
    assert {int(x) for x in values(first["say"])} <= {20}
    assert [m["purpose"] for m in first["models"]] == ["instances"]
    assert double.calls("/chat/completions") == 0 and len(held) == 1
    assert _get(client, site, first["look_id"]) == first  # still reading
    held[0]()
    final = _get(client, site, first["look_id"])
    assert final["final"] is True and final["source"] == "model" and final["look_id"] == first["look_id"]
    assert final["counts"] == {"expected": 20, "seen": 20, "damaged": 2, "good": 18}
    assert final["proposal"] == {"receive": 18, "flag": 2,
                                 "reasons": ["2 damaged", "2 packs hold 10, not 12: 4 pieces short"]}
    assert final["say"] == "20 of 20 packs. 2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2?"
    assert final["say_next"] == "2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2?"
    assert {int(x) for x in values(final["say_next"])} <= {20, 2, 10, 12, 4, 18}
    assert [m["purpose"] for m in final["models"]] == ["instances", "labels", "labels", "labels"]
    assert double.calls("/responses") == 1
    held[0]()  # a second run (e.g. a retried task) writes nothing: the look is final
    assert _get(client, site, first["look_id"]) == final


def test_m5_s01_route_answers_first_and_reads_labels_after_the_answer(client: TestClient, site: dict[str, Any],
                                                                      v: SimpleNamespace, ai_on: None) -> None:
    """Through the route: the POST body is the first answer (final false); the background task ran after it (the test
    client returns when it is done), so GET is final; a replay with the same Idempotency-Key gives the stored first
    answer again and starts no second read."""
    v.add_case_line(site, "grocery", ppu=12)
    double = v.VisionDouble(boxes=v.grid_boxes(20), labels=C1_LABELS)
    cap = v.upload_capture(client, site, v.photo(double.boxes))
    h = v.h(site["dev"])
    body = {"task_id": site["receive"], "line_id": site["line"], "capture_id": cap, "case": "grocery"}
    app.dependency_overrides[get_vision_ports] = lambda: v.ports_for(double)
    try:
        r = client.post("/v1/vision/looks", json=body, headers=h)
        calls = len(double.requests)
        again = client.post("/v1/vision/looks", json=body, headers=h)
    finally:
        app.dependency_overrides.pop(get_vision_ports, None)
    assert r.status_code == 200 and r.json()["final"] is False and r.json()["say"] == "20 of 20 packs. Reading the labels."
    assert again.status_code == 200 and again.json() == r.json() and len(double.requests) == calls == 4
    final = _get(client, site, r.json()["look_id"])
    assert final["final"] is True and final["proposal"]["receive"] == 18 and final["source"] == "model"


def test_m5_s01_label_failure_ends_partial_and_asks_for_the_numbers(client: TestClient, site: dict[str, Any],
                                                                     v: SimpleNamespace, ai_on: None) -> None:
    """Muse fails (no fallback): the look ends final, partial, reason kept, say "I couldn't read the labels. Say your
    numbers." (no number), and the label-free check (every label unread) as its counts and proposal."""
    v.add_case_line(site, "grocery", ppu=12)
    double = v.VisionDouble(boxes=v.grid_boxes(5), labels={}, label_script=[500])
    first, held = _deferred(client, site, v, v.ports_for(double), "two-step-fail")
    assert first["final"] is False and first["counts"]["seen"] == 5
    held[0]()
    final = _get(client, site, first["look_id"])
    assert final["final"] is True and final["source"] == "partial"
    assert final["say"] == final["say_next"] == LABELS_FAILED_SAY and values(final["say"]) == set()
    assert final["reasons"] == ["labels:muse-spark-1.3:AI_HTTP_500"]
    assert final["counts"] == {"expected": 20, "seen": 5, "damaged": 0, "good": 5}
    assert final["proposal"]["reasons"][-1] == "5 labels not read"
    assert all(i["label"]["read"] is False for i in final["instances"])


class _Broken:
    """A label reader that raises something other than a model error (test code only)."""

    model = "broken-reader"

    def read(self, crops: Sequence[tuple[int, bytes]], *, case: str, object_noun: str, timeout_s: float,
             ctx: CallContext) -> dict[int, LabelRead]:
        raise RuntimeError("unexpected")


def test_m5_s01_an_error_in_the_label_read_still_ends_the_look(client: TestClient, site: dict[str, Any],
                                                               v: SimpleNamespace, ai_on: None) -> None:
    double = v.VisionDouble(boxes=v.grid_boxes(4), labels={})
    ports = VisionPorts(v.ports_for(double).instances, (_Broken(),))
    first, held = _deferred(client, site, v, ports, "two-step-error")
    held[0]()  # must not raise
    final = _get(client, site, first["look_id"])
    assert final["final"] is True and final["source"] == "partial" and final["say"] == LABELS_FAILED_SAY
    assert final["reasons"] == ["labels:error"] and final["counts"]["seen"] == 4


def test_m5_s01_an_unfinished_read_past_its_due_time_is_given_up_on_the_next_read(
        client: TestClient, site: dict[str, Any], v: SimpleNamespace, ai_on: None) -> None:
    """field-api restarted during the label read (the held task never runs): before the due time GET still says
    reading; after it, GET ends the look (labels:not_finished); a late label read then writes nothing."""
    v.add_case_line(site, "grocery", ppu=12)
    double = v.VisionDouble(boxes=v.grid_boxes(20), labels=C1_LABELS)
    first, held = _deferred(client, site, v, v.ports_for(double), "two-step-restart")
    assert _get(client, site, first["look_id"])["final"] is False
    v.admin_sql(site["tenant"], "UPDATE field.vision_look SET labels_due_at = NOW() - interval '1 second'"
                                " WHERE id = %s", (first["look_id"],))
    ended = _get(client, site, first["look_id"])
    assert ended["final"] is True and ended["source"] == "partial" and ended["reasons"] == ["labels:not_finished"]
    assert ended["say"] == ended["say_next"] == LABELS_FAILED_SAY
    assert ended["counts"] == {"expected": 20, "seen": 20, "damaged": 0, "good": 20}
    held[0]()
    assert _get(client, site, first["look_id"]) == ended


def test_m5_s01_a_claim_waits_for_the_final_look(client: TestClient, site: dict[str, Any], v: SimpleNamespace,
                                                 ai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /v1/claims on a look still reading labels -> 409 FIELD-CLM-409-LOOK-PENDING (nothing is made); once the
    look is final the claim is made from its final state (2 damaged, 2 packs of 10 not 12)."""
    v.add_case_line(site, "grocery", ppu=12)
    double = v.VisionDouble(boxes=v.grid_boxes(20), labels=C1_LABELS)
    first, held = _deferred(client, site, v, v.ports_for(double), "two-step-claim")
    r = client.post("/v1/claims", json={"look_id": first["look_id"]}, headers=v.h(site["dev"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-CLM-409-LOOK-PENDING"
    held[0]()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")  # the claim text from the template, no model call
    made = client.post("/v1/claims", json={"look_id": first["look_id"]}, headers=v.h(site["dev"]))
    assert made.status_code == 201, made.text
    reasons = {ln["reason"] for ln in made.json()["lines"]}
    assert reasons == {"damaged", "pack_size"}


def test_m5_s01_first_and_next_say_are_number_checked() -> None:
    exp = Expectation(case="grocery", object_noun="pack", expected_units=20)
    assert first_say(8, 20, exp) == "8 of 20 packs. Reading the labels."
    assert first_say(1, None, exp) == "1 pack. Reading the labels."
    assert first_say(3, None, Expectation(case="pharmacy", object_noun="box")) == "3 boxes. Reading the labels."
    first = first_say(20, 20, exp)
    assert next_say("20 of 20 packs. 2 damaged. Receive 18, flag 2?", first) == "2 damaged. Receive 18, flag 2?"
    assert next_say("20 seen. Receive 20, flag 0?", first) == "20 seen. Receive 20, flag 0?"  # not the same lead
    assert next_say(LABELS_FAILED_SAY, first) == LABELS_FAILED_SAY
    assert next_say("20 of 20 packs.", first) == "20 of 20 packs."  # nothing after the count: the whole say
    assert first.endswith(PENDING_SAY)
