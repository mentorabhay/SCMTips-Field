"""M5-P01: larger look photos (owner-approved 1 Nov 2026). The app sends a look photo of at most 1600 px on its long
side (was 640); the captures API keeps its 1 MB limit; SAM 3.1 gets the photo exactly as stored; each label crop is
cut from that full-size photo and scaled to at most 768 px; the evidence page shows the stored photo with outlines in
its own pixel space. Faces are pixelated on the phone on the full photo before upload (the server refuses a capture
without blur_applied, so no model ever sees an unblurred photo)."""

from __future__ import annotations

import base64
import io
import json
import os
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.crops import MAX_CROP_BYTES
from field_api.evidence.page import render
from field_api.vision.image import CROP_MAX_SIDE, CROP_PAD, padded
from field_api.vision.service import get_vision_ports
from PIL import Image

pytestmark = pytest.mark.unit


def _post(client: TestClient, s: dict[str, Any], v: SimpleNamespace, double: Any, cap: str) -> dict[str, Any]:
    app.dependency_overrides[get_vision_ports] = lambda: v.ports_for(double)
    try:
        r = client.post("/v1/vision/looks", json={"task_id": s["receive"], "line_id": s["line"], "capture_id": cap,
                                                   "case": "grocery"}, headers=v.h(s["dev"]))
    finally:
        app.dependency_overrides.pop(get_vision_ports, None)
    assert r.status_code == 200, r.text
    look = dict(r.json())
    if look.get("final") is False:  # M5-S01: the label read finishes after the first answer
        got = client.get(f"/v1/vision/looks/{look['look_id']}", headers={"Authorization": f"Bearer {s['dev']}"})
        assert got.status_code == 200
        look = dict(got.json())
    return look


def _images(url_parts: list[str]) -> list[Image.Image]:
    out = []
    for u in url_parts:
        assert u.startswith("data:image/jpeg;base64,")
        out.append(Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))))
    return out


def _crop_urls(double: Any) -> list[str]:
    return [p["image_url"]["url"] for r in double.requests if r.get("model") == "muse-spark-1.3"
            for p in r["messages"][-1]["content"] if p.get("type") == "image_url"]


def test_m5_p01_1600_px_photo_goes_whole_to_sam_and_label_crops_are_cut_full_size(
        client: TestClient, site: dict[str, Any], v: SimpleNamespace, ai_on: None) -> None:
    """A 1600 x 1200 look photo is accepted by the captures API; SAM's input image is byte-for-byte the stored photo
    (1600 x 1200, not scaled down); every label crop is the padded instance box cut from the full-size photo (its
    size equals the padded box when that is under 768 px), never from a 640 px copy."""
    v.add_case_line(site, "grocery", ppu=12)
    boxes = v.grid_boxes(8, cols=4, width=1600, height=1200)
    double = v.VisionDouble(boxes=boxes, width=1600, height=1200,
                            labels={n: {"pieces_per_unit": 12} for n in range(1, 9)})
    jpeg = v.photo(boxes, width=1600, height=1200)
    assert len(jpeg) <= MAX_CROP_BYTES
    cap = v.upload_capture(client, site, jpeg)
    look = _post(client, site, v, double, cap)
    assert look["image"]["width"] == 1600 and look["image"]["height"] == 1200
    assert look["counts"]["seen"] == 8 and look["source"] == "model"
    sam_req = next(r for r in double.requests if r["model"] == "sam-3.1")
    sam_url = sam_req["input"][0]["content"][1]["image_url"]
    assert base64.b64decode(sam_url.split(",", 1)[1]) == jpeg  # the stored photo, unchanged
    crops = _images(_crop_urls(double))
    assert len(crops) == 8  # one crop per instance: the count does not depend on the photo size
    by_n = {i["n"]: tuple(i["box"]) for i in look["instances"]}
    for n, crop in enumerate(crops, start=1):
        x0, y0, x1, y1 = padded(by_n[n], 1600, 1200, CROP_PAD)
        assert max(x1 - x0, y1 - y0) < CROP_MAX_SIDE  # these instances fit: no scaling
        assert crop.size == (x1 - x0, y1 - y0)
        assert max(crop.size) > 640 * (y1 - y0) / 1200  # far larger than the same box in a 640 px photo


def test_m5_p01_label_crops_are_capped_at_768_px(client: TestClient, site: dict[str, Any], v: SimpleNamespace,
                                                 ai_on: None) -> None:
    """Two instances that fill most of a 1600 px photo: their crops are scaled to exactly 768 px on the long side
    (aspect kept); the evidence page embeds the stored photo itself with the outlines in its 1600 x 1200 space."""
    boxes = [(20, 20, 790, 1180), (810, 20, 1580, 1180)]
    double = v.VisionDouble(boxes=boxes, width=1600, height=1200, labels={1: {"pieces_per_unit": 12},
                                                                          2: {"pieces_per_unit": 12}})
    jpeg = v.photo(boxes, width=1600, height=1200)
    look = _post(client, site, v, double, v.upload_capture(client, site, jpeg))
    crops = _images(_crop_urls(double))
    assert len(crops) == 2
    for crop, box in zip(crops, boxes, strict=True):
        x0, y0, x1, y1 = padded(box, 1600, 1200, CROP_PAD)
        assert max(crop.size) == CROP_MAX_SIDE == 768
        assert abs(crop.size[0] / crop.size[1] - (x1 - x0) / (y1 - y0)) < 0.01
    html = render({"look": look, "hashes": {"photo": "stored"}}, jpeg)
    assert f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}" in html  # the photo as stored
    assert 'viewBox="0 0 1600 1200"' in html


def test_m5_p01_same_layout_at_640_and_1600_px_sends_the_same_number_of_label_images(
        client: TestClient, site: dict[str, Any], v: SimpleNamespace, ai_on: None) -> None:
    """The budget guard reserves image tokens per input image (config/ai_pricing.yaml tokens_per_image, flat): the
    bigger photo does not change how many images a look sends, only how large each crop is (at most 768 px)."""
    counts = []
    for w, h in ((640, 480), (1600, 1200)):
        boxes = v.grid_boxes(10, cols=5, width=w, height=h)
        double = v.VisionDouble(boxes=boxes, width=w, height=h, labels={n: {"pieces_per_unit": 12} for n in range(1, 11)})
        _post(client, site, v, double, v.upload_capture(client, site, v.photo(boxes, width=w, height=h)))
        counts.append((len(_crop_urls(double)), sum(1 for r in double.requests if r.get("model") == "muse-spark-1.3")))
        assert all(max(c.size) <= CROP_MAX_SIDE for c in _images(_crop_urls(double)))
    assert counts[0] == counts[1] == (10, 2)  # 10 crops, VISION_CROPS_PER_CALL 8 -> 2 calls, at either size


def test_m5_p01_captures_api_keeps_its_1_mb_limit_and_its_blur_gate(client: TestClient, site: dict[str, Any],
                                                                    v: SimpleNamespace) -> None:
    """The larger photo does not lift the captures limits: above 1 MB is 413, and a photo the phone did not blur is
    refused (422) before it is stored, so no look (and no model) can ever use it."""
    meta = {"device_id": site["phone"], "task_id": site["receive"], "site_id": site["site"], "shutter_timestamp": 1,
            "blur_applied": True, "code_type": "photo", "code_value": f"look-{uuid.uuid4()}", "readability": 0.9}
    big = os.urandom(MAX_CROP_BYTES + 1)
    r = client.post("/v1/captures", data={"metadata": json.dumps(meta)}, files={"crop": ("look.jpg", big, "image/jpeg")},
                    headers=v.h(site["dev"]))
    assert r.status_code == 413 and r.json()["code"] == "FIELD-CAP-413-CROP-TOO-LARGE"
    up = client.post("/v1/captures/uploads", json={"device_id": site["phone"], "sha256": "0" * 64,
                                                    "bytes": MAX_CROP_BYTES + 1}, headers=v.h(site["dev"]))
    assert up.status_code == 413
    unblurred = {**meta, "blur_applied": False, "code_value": f"look-{uuid.uuid4()}"}
    jpeg = v.photo(v.grid_boxes(2, width=1600, height=1200), width=1600, height=1200)
    r = client.post("/v1/captures", data={"metadata": json.dumps(unblurred)},
                    files={"crop": ("look.jpg", jpeg, "image/jpeg")}, headers=v.h(site["dev"]))
    assert r.status_code == 422 and r.json()["code"] == "FIELD-CAP-422-BLUR-MISSING"
