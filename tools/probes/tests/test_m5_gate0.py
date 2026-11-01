"""tools/probes/m5_gate0.py (M5-V09) against an httpx test double of the Meta Model API (test code only): both probes
use field-api's own adapters through the real budget guard; the output and the evidence file carry shapes, never the
key, the image or label text; placeholder prices are refused without --allow-unconfirmed-prices."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from field_api.ai.budget import BudgetGuard, Price
from PIL import Image

from tools.probes.m5_gate0 import main, shape

pytestmark = pytest.mark.unit
KEY = "probe-key-" + "z" * 24  # a marker, not a credential


def _photo(tmp_path: Path) -> Path:
    p = tmp_path / "shelf.png"
    Image.new("RGB", (3200, 2400), (200, 120, 60)).save(p)
    return p


def _api(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/responses"):
            ev = [{"type": "response.output_text.delta",
                   "delta": "<0f>0<|box;x1=10;y1=10;x2=99;y2=99;w=1600;h=1200;c=0.88|><|mask;data=1,1,~!|>"},
                  {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 2}}}]
            return httpx.Response(200, content="".join(f"data: {json.dumps(e)}\n\n" for e in ev).encode(),
                                  headers={"content-type": "text/event-stream"})
        content = json.dumps({"items": [{"n": 1, "label_readable": True, "pieces_per_unit": 6, "batch": "B7",
                                         "expiry": "2027-05", "damaged": False, "damage_note": None,
                                         "label_text": "BrandName biscuits 6 x 25 g"}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                                         "usage": {"prompt_tokens": 1900, "completion_tokens": 700,
                                                   "completion_tokens_details": {"reasoning_tokens": 600}}})

    return httpx.MockTransport(handler)


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    monkeypatch.setenv("AI_BUDGET_META_USD", str(Decimal(usage["providers"]["meta"]["spent_usd"]) + 5))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + 5))
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    monkeypatch.delenv("AI_ALLOW_UNCONFIRMED_PRICES", raising=False)


def test_m5_v09_probe_runs_both_and_writes_redacted_evidence(tmp_path: Path, ai: None,
                                                            capsys: pytest.CaptureFixture[str],
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {
        "sam-3.1": Price(Decimal(0), Decimal(0), per_image_usd=Decimal("0.005"), confirmed=False),
        "muse-spark-1.3": Price(Decimal("1.25"), Decimal("4.25"), image_input_confirmed=False)}})
    rc = main(["--photo", str(_photo(tmp_path)), "--allow-unconfirmed-prices"], transport=_api(seen), guard=guard,
              evidence_dir=tmp_path / "ev")
    monkeypatch.delenv("AI_ALLOW_UNCONFIRMED_PRICES", raising=False)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "G0-1 muse-spark-1.3: OK" in out and "G0-2 sam-3.1: OK" in out
    assert '"pieces_per_unit": 6' in out and '"instances": 1' in out and "reasoning_tokens" in out
    assert "<data url," in out and '"response_format"' in out  # the request shape, image replaced
    assert KEY not in out and "BrandName" not in out and "base64," not in out
    files = list((tmp_path / "ev").glob("*-m5-gate0-*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert KEY not in text and "BrandName" not in text and "label_text_chars" in text
    sent = json.loads(seen[0].content)
    img = sent["messages"][-1]["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(__import__("base64").b64decode(img.split(",", 1)[1]))) as im:
        assert max(im.size) == 1600  # scaled like a capture
    assert all(r.headers["authorization"] == f"Bearer {KEY}" for r in seen)


def test_m5_v09_probe_without_the_flag_is_blocked_and_calls_nothing(tmp_path: Path, ai: None,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    from field_api.ai.budget import load_prices

    seen: list[httpx.Request] = []
    rc = main(["--photo", str(_photo(tmp_path)), "--no-evidence"], transport=_api(seen),
              guard=BudgetGuard(prices=load_prices()), evidence_dir=tmp_path / "ev")
    out = capsys.readouterr().out
    assert rc == 1 and seen == [] and out.count("BLOCKED AI_PRICE_UNCONFIRMED") == 2
    assert "--allow-unconfirmed-prices" in out and not (tmp_path / "ev").exists()


def test_m5_v09_shapes_keep_keys_and_drop_values() -> None:
    assert shape({"a": "secret", "b": [1, 2, 3], "c": {"d": None, "e": True}, "img": "data:image/jpeg;base64,xx"}) == {
        "a": "<str 6>", "b": ["int", "... 3 items"], "c": {"d": None, "e": True}, "img": "<data url, 25 chars>"}
