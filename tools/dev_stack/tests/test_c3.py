"""C3 on the dev stack (M5-T06, M5-T07): the stand-in's seal answer, the smoke photo, the `c3` and `smoke --c3`
commands."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from field_api.authenticity.seal import SEAL_SCHEMA_NAME, response_format
from PIL import Image

from tools.dev_stack import c3, model_standin, stack


def test_m5_t07_standin_answers_the_seal_check_from_the_scene() -> None:
    assert model_standin.SEAL_SCHEMA == SEAL_SCHEMA_NAME
    api = TestClient(model_standin.app)
    try:
        api.post("/_standin/scene", json={"boxes": [c3.SEAL_BOX], "width": c3.W, "height": c3.H,
                                          "seal": {"seal_visible": True, "signs": ["tape_over_seal"]}})
        body = {"model": "muse-spark-1.3", "response_format": response_format(),
                "messages": [{"role": "system", "content": "seal"}, {"role": "user", "content": [
                    {"type": "text", "text": "seal:"}, {"type": "image_url", "image_url": {"url": "data:x"}}]}]}
        out = api.post("/v1/chat/completions", json=body).json()
        assert out["choices"][0]["message"]["content"] == '{"seal_visible": true, "signs": ["tape_over_seal"]}'
        labels = {**body, "response_format": None}
        assert '"items"' in api.post("/v1/chat/completions", json=labels).json()["choices"][0]["message"]["content"]
    finally:
        api.post("/_standin/scene", json={"boxes": [], "width": 1, "height": 1})
    assert model_standin.SCENE["seal"] == {"seal_visible": True, "signs": []}


def test_m5_t07_smoke_photo_is_a_capture_sized_jpeg_with_the_seal_box() -> None:
    data = c3.seal_jpeg()
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "JPEG" and img.size == (c3.W, c3.H)
    assert len(data) < 1_000_000


def test_m5_t06_stack_has_the_c3_command_and_the_smoke_flag() -> None:
    assert "stack c3" in (stack.__doc__ or "") and "smoke --c3" in (stack.__doc__ or "")
    assert "OEMSIM_SIGNING_SEED" in stack.GENERATED_SECRETS
    assert str(c3.LABELS_OUT).replace("\\", "/") == "var/c3_labels.html"
