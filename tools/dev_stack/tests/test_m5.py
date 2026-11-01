"""M5 dev-stack pieces (M5-V07, M5-V08): the model stand-in serves the shapes field-api's adapters read, the smoke's
scenes give the proposals it checks on any day, the case labels, and the stack's new commands. The end-to-end proof
is `stack smoke --m5-look` on a running stack (docs/evidence run log); these tests prove the parts in CI."""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from field_api.vision.labels import parse_reads
from field_api.vision.reconcile import Expectation, Seen, reconcile
from field_api.vision.sam import parse_boxes
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image

from tools.dev_stack import m5, model_standin, stack

pytestmark = pytest.mark.unit


def test_m5_v08_standin_serves_sam_boxes_and_label_json() -> None:
    api = TestClient(model_standin.app)
    boxes = m5.grid(6, 3)
    assert api.post("/_standin/scene", json={"boxes": boxes, "width": 1000, "height": 800,
                                             "labels": {"2": {"pieces_per_unit": 10, "damaged": True}}}).json() == {
        "boxes": 6}
    r = api.post("/v1/responses", json={"model": "sam-3.1", "input": []})
    assert r.headers["content-type"].startswith("text/event-stream")
    text = "".join(json.loads(ln[6:])["delta"] for ln in r.text.splitlines()
                   if ln.startswith("data: {") and '"response.output_text.delta"' in ln)
    assert sorted(f.box for f in parse_boxes(text, 1000, 800)) == sorted(tuple(b) for b in boxes)
    r = api.post("/v1/chat/completions", json={"model": "muse-spark-1.3", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "pack 2:"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"}},
        {"type": "text", "text": "pack 3:"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"}}]}]})
    reads = parse_reads(r.json()["choices"][0]["message"]["content"], {2, 3})
    assert reads[2].pieces_per_unit == 10 and reads[2].damaged and reads[3].read is False
    seen = api.get("/_standin/requests").json()
    assert seen["responses"] >= 1 and seen["chat"] >= 1


@given(st.dates(date(2026, 1, 1), date(2030, 12, 31)))
def test_m5_v08_smoke_scenes_give_the_expected_proposals_on_any_day(today: date) -> None:
    for case, sc in m5.scenes(today).items():
        noun = "pack" if case == "grocery" else "box"
        seen = [Seen(n, damaged=bool(sc["labels"].get(str(n), {}).get("damaged")), read=True,
                     pieces_per_unit=sc["labels"].get(str(n), {}).get("pieces_per_unit"),
                     batch=sc["labels"].get(str(n), {}).get("batch"),
                     expiry=sc["labels"].get(str(n), {}).get("expiry")) for n in range(1, sc["n"] + 1)]
        c = reconcile(seen, Expectation(case, noun, sc["n"], 12 if case == "grocery" else None, 90), today)
        assert (c.proposal["receive"], c.proposal["flag"]) == (sc["receive"], sc["flag"])


def test_m5_v08_smoke_photo_is_a_capture_sized_jpeg() -> None:
    jpeg = m5.draw(m5.grid(20, 5), "pack")
    assert len(jpeg) < 1024 * 1024
    with Image.open(io.BytesIO(jpeg)) as img:
        assert img.size == (m5.W, m5.H) and img.format == "JPEG"


def test_m5_v07_case_labels_and_commands() -> None:
    cases = {"grocery": {"ref_doc_no": "1900000001", "expected_units": 20, "expected_pieces_per_unit": 12},
             "pharmacy": {"ref_doc_no": "1900000002", "expected_units": 10, "expiry_window_days": 90}}
    sections = m5.case_sections(cases)
    assert [t for t, _ in sections] == ["C1 grocery delivery 1900000001: 20 packs, 12 pieces each",
                                        "C2 pharmacy delivery 1900000002: 10 boxes, expiry window 90 days"]
    assert [c for _, codes in sections for c, _ in codes] == ["1900000001", "M5-C1-PACK", "1900000002", "M5-C2-BOX"]
    html = stack.render_labels(sections, "2026-11-01 10:00")
    assert html.count("<svg") == 4 and "biscuit pack" in html
    with pytest.raises(SystemExit):
        stack.main(["m5-cases", "--help"])
    with pytest.raises(SystemExit):
        stack.main(["smoke", "--m5-look", "--help"])


def test_m5_v08_model_standin_env_never_uses_the_real_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`up --model-standin` points field-api at the stand-in with a dev marker, never the owner's MODEL_API_KEY."""
    for name in ("META_MODEL_API_BASE_URL", "AI_CLOUD_ENABLED", "FIELD_AI_PRICING_FILE", "FIELD_STACK_MODEL_URL",
                 "AI_BUDGET_META_USD", "AI_DAILY_CAP_USD"):  # restored after the test (start_model_standin sets them)
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("MODEL_API_KEY", "the-owners-real-key")
    monkeypatch.setenv("FIELD_STACK_MODEL_PORT", "8999")
    monkeypatch.setattr(stack, "running", lambda name: 1)
    monkeypatch.setattr(stack, "start", lambda name, cmd: 4242)
    monkeypatch.setattr(stack, "wait_http", lambda url, timeout_s=30: True)
    assert stack.start_model_standin() is True
    import os

    assert os.environ["MODEL_API_KEY"] == stack.MODEL_STANDIN_KEY
    assert os.environ["META_MODEL_API_BASE_URL"] == "http://127.0.0.1:8999/v1"
    assert os.environ["FIELD_AI_PRICING_FILE"].endswith("model_standin_pricing.yaml")
    from field_api.ai.budget import load_prices

    prices = load_prices(stack.MODEL_STANDIN_PRICING)["meta"]
    assert all(p.confirmed and p.input_per_mtok == 0 and p.output_per_mtok == 0 and p.per_image_usd == 0
               for p in prices.values())
