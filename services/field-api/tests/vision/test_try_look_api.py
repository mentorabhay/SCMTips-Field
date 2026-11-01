"""M5-W01: the console's "Try a look" page. POST /v1/try/looks runs the real look engine (SAM 3.1 instances, label
reads, deterministic reconcile, number-checked say, two steps) on an uploaded photo with no task, capture, posting or
claim; GET /v1/try/looks/{id} and /photo read the caller's own look. Server-enforced guard rails: field.try.use,
JPEG/PNG only (415), 5 MB (413), faces pixelated before storing and before any model call, 10 looks per principal per
rolling hour (429 + Retry-After), the try-scope daily budget cap (rules mode, never an error), 24 h photo retention.
On Postgres with RLS and the budget guard; the SAM 3.1 / Muse adapters over the test double of the Meta API (test
code only), scripted from the SAMPLE photos' own scene (tools.samples.try_photos)."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard, BudgetRefused, Price
from field_api.app import app
from field_api.assistant.model import ChatModel, ProviderConfig
from field_api.auth.jwt import create_dev_token, verify_token
from field_api.briefs.numbers import values
from field_api.vision.faces import HaarFaces, blur_faces, pixelate
from field_api.vision.labels import ChatLabelReader
from field_api.vision.ports import VisionPorts
from field_api.vision.sam import Sam31Instances
from field_api.vision.say import RULES_SAY
from field_api.vision.try_look import TryIn, create_try_look, get_try_vision_ports
from PIL import Image, ImageDraw, ImageFilter

pytestmark = pytest.mark.unit
TODAY = date(2026, 11, 1)
C1 = {"case": "grocery", "expected_units": 8, "pieces_per_unit": 6}
C2 = {"case": "pharmacy", "expected_units": 5, "window_days": 90}


def _admin() -> str:
    return os.environ["FIELD_ADMIN_DATABASE_URL"]


def _samples() -> Any:
    """tools.samples.try_photos (the SAMPLE photos and their scene), importable when this file runs on its own."""
    root = str(Path(__file__).resolve().parents[4])
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools.samples import try_photos

    return try_photos


def grocery() -> Any:
    return _samples().grocery()


def pharmacy() -> Any:
    return _samples().pharmacy()


@pytest.fixture(autouse=True)
def _try_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_TRY_PHOTO_DIR", str(tmp_path / "try-photos"))
    monkeypatch.delenv("FIELD_TRY_LOOKS_PER_HOUR", raising=False)
    monkeypatch.delenv("AI_TRY_DAILY_CAP_USD", raising=False)


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")


@pytest.fixture
def judges() -> dict[str, Any]:
    """One tenant, no site or task: tokens for every role (the viewer scoped to one site, to prove the try policy)."""
    tenant = str(uuid.uuid4())

    def tok(pid: str, role: str, sites: list[str] | None = None) -> str:
        return create_dev_token(pid, tenant, [role], site_ids=sites or ["*"])

    return {"tenant": tenant, "op": tok("judge-op", "field.operator", [str(uuid.uuid4())]),
            "sup": tok("judge-sup", "field.supervisor"), "viewer": tok("judge-viewer", "field.viewer", [str(uuid.uuid4())]),
            "tech": tok("judge-tech", "field.technician"), "ctrl": tok("judge-ctrl", "inventory.controller"),
            "integ": tok("judge-int", "field.integration"), "op2": tok("judge-op-2", "field.operator"),
            "stranger": create_dev_token("judge-op", str(uuid.uuid4()), ["field.operator"], site_ids=["*"])}


def _auth(token: str, key: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid.uuid4())}


def post_try(client: TestClient, token: str, photo: bytes, look: dict[str, Any], key: str | None = None,
             name: str = "photo.jpg", ctype: str = "image/jpeg") -> Any:
    return client.post("/v1/try/looks", files={"photo": (name, photo, ctype)}, data={"look": json.dumps(look)},
                       headers=_auth(token, key))


def small_jpeg(color: tuple[int, int, int] = (200, 190, 170), size: tuple[int, int] = (400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def drawn_face(size: int) -> Image.Image:
    """A frontal face drawn with Pillow (skin oval, eyes, brows, nose, mouth, hair): Haar's frontal cascades find it."""
    img = Image.new("RGB", (size * 2, size * 2), (120, 130, 140))
    d = ImageDraw.Draw(img)
    cx, cy, s = size, size, size / 2
    d.ellipse((cx - s * 0.75, cy - s, cx + s * 0.75, cy + s), fill=(225, 185, 160))
    for ex in (-0.32, 0.32):
        d.ellipse((cx + ex * s - s * 0.16, cy - s * 0.28, cx + ex * s + s * 0.16, cy - s * 0.12), fill=(40, 30, 30))
        d.rectangle((cx + ex * s - s * 0.2, cy - s * 0.45, cx + ex * s + s * 0.2, cy - s * 0.38), fill=(70, 50, 40))
    d.polygon([(cx, cy - s * 0.1), (cx - s * 0.1, cy + s * 0.25), (cx + s * 0.1, cy + s * 0.25)], fill=(190, 145, 125))
    d.ellipse((cx - s * 0.28, cy + s * 0.4, cx + s * 0.28, cy + s * 0.55), fill=(150, 70, 70))
    d.rectangle((cx - s * 0.8, cy - s * 1.1, cx + s * 0.8, cy - s * 0.7), fill=(50, 35, 25))
    return img.filter(ImageFilter.GaussianBlur(size / 60))


def double_for(v: SimpleNamespace, sample: Any, **kw: Any) -> Any:
    return v.VisionDouble(boxes=sample.boxes, width=sample.width, height=sample.height, labels=sample.labels, **kw)


def try_ports(v: SimpleNamespace, double: Any) -> VisionPorts:
    """The adapters of get_try_vision_ports (the budget guard with the try scope) over the Meta API double."""
    guard = BudgetGuard(prices=v.PRICES, scope="try")
    return VisionPorts(Sam31Instances("https://api.meta.ai/v1", "sam-3.1", guard, double.transport),
                       (ChatLabelReader(ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.3",
                                                                 "MODEL_API_KEY"), guard, double.transport)),))


def sam_image(double: Any) -> Image.Image:
    """The image the SAM 3.1 double was sent (the data URL of the first /responses request)."""
    body = next(r for r in double.requests if "input" in r)
    url = next(p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def held_look(token: str, photo: bytes, look: dict[str, Any], ports: Any, key: str | None = None
              ) -> tuple[dict[str, Any], list[Callable[[], None]]]:
    held: list[Callable[[], None]] = []
    first = create_try_look(verify_token(token), TryIn.model_validate(look), photo, key or str(uuid.uuid4()), ports,
                            today=lambda: TODAY, defer=held.append)
    return first, held


def _get(client: TestClient, token: str, look_id: str) -> Any:
    return client.get(f"/v1/try/looks/{look_id}", headers={"Authorization": f"Bearer {token}"})


# --------------------------------------------------------------------------- the engine without a task
def test_m5_w01_c1_sample_two_step_look_without_task_capture_or_posting(client: TestClient, judges: dict[str, Any],
                                                                        v: SimpleNamespace, ai_on: None) -> None:
    """The C1 SAMPLE (8 packs, pack 3 torn, pack 6 holds 4): the first answer counts and outlines (final false, say
    the count then "Reading the labels."); after the label read, GET answers the final look with the pack-size and
    damage findings, the proposal and say_next. No task, line, capture or document; every spoken number checked."""
    sample = grocery()
    double = double_for(v, sample)
    first, held = held_look(judges["op"], sample.jpeg, C1, try_ports(v, double))
    assert first["kind"] == "try" and first["try"]["sample"] is True and first["try"]["posts"] is False
    assert first["task_id"] is None and first["capture_id"] is None and first["line_id"] is None
    assert first["erp_document_id"] is None and first["image"]["capture_id"] is None
    assert first["image"] == {"capture_id": None, "width": 1280, "height": 960, "faces_blurred": 0}
    assert first["final"] is False and first["source"] == "partial"
    assert first["counts"] == {"expected": 8, "seen": 8, "damaged": None, "good": None}
    assert first["say"] == "8 of 8 packs. Reading the labels."
    assert [i["n"] for i in first["instances"]] == list(range(1, 9))
    assert [tuple(i["box"]) for i in first["instances"]] == [tuple(b) for b in sample.boxes]
    assert first["try"]["photo_url"] == f"/v1/try/looks/{first['look_id']}/photo"
    assert first["try"]["photo_kept_hours"] == 24 and len(held) == 1
    held[0]()
    final = _get(client, judges["op"], first["look_id"]).json()
    assert final["final"] is True and final["source"] == "model"
    assert final["counts"] == {"expected": 8, "seen": 8, "damaged": 1, "good": 7}
    assert final["pack"]["expected_pieces_per_unit"] == 6
    assert final["pack"]["mismatches"] == [{"n": 6, "pieces_per_unit": 4}]
    assert final["pack"]["pieces_difference"] == -2
    damaged = [i["n"] for i in final["instances"] if i["damaged"]]
    assert damaged == [3] and all(i["label"]["read"] for i in final["instances"])
    assert final["proposal"]["receive"] + final["proposal"]["flag"] == 8
    assert final["say"].startswith("8 of 8 packs. 1 damaged.") and final["say_next"].startswith("1 damaged.")
    allowed = {Decimal(n) for n in (8, 1, 7, 6, 4, 2, final["proposal"]["receive"], final["proposal"]["flag"])}
    assert values(final["say"]) <= allowed and values(final["say_next"]) <= allowed
    assert {m["purpose"] for m in final["models"]} == {"instances", "labels"}
    with psycopg.connect(_admin()) as c, c.cursor() as cur:
        cur.execute("SELECT kind, site_id, task_id, capture_id, photo_uri IS NOT NULL, photo_expires_at > NOW()"
                    " + interval '23 hours' FROM field.vision_look WHERE id = %s", (first["look_id"],))
        assert cur.fetchone() == ("try", None, None, None, True, True)
        cur.execute("SELECT DISTINCT purpose FROM ops.ai_usage WHERE tenant_id = %s", (judges["tenant"],))
        assert {r[0] for r in cur.fetchall()} == {"try:vision"}  # the try scope of the budget guard


def test_m5_w01_c2_sample_expiry_window_and_batches(client: TestClient, judges: dict[str, Any], v: SimpleNamespace,
                                                    ai_on: None) -> None:
    """The C2 SAMPLE (5 boxes, box 2 dented, box 4 EXP 2026-12): within the user's 90-day window from 1 Nov 2026 box 4
    is near expiry; two batches. With the user's window set to 30 days box 4 is no longer flagged."""
    sample = pharmacy()
    first, held = held_look(judges["sup"], sample.jpeg, C2, try_ports(v, double_for(v, sample)))
    assert first["say"] == "5 of 5 boxes. Reading the labels."
    held[0]()
    final = _get(client, judges["sup"], first["look_id"]).json()
    assert final["final"] is True and final["counts"]["seen"] == 5 and final["counts"]["damaged"] == 1
    assert final["expiry"]["window_days"] == 90 and sorted(final["expiry"]["batches"]) == ["B1", "B2"]
    assert [f["n"] for f in final["expiry"]["flagged"]] == [4] and final["expiry"]["flagged"][0]["reason"] == "near"
    assert final["pack"] is None
    shorter, held30 = held_look(judges["sup"], sample.jpeg, {**C2, "window_days": 30},
                                try_ports(v, double_for(v, sample)))  # the user's window: 30 days
    held30[0]()
    short = _get(client, judges["sup"], shorter["look_id"]).json()
    assert short["expiry"]["window_days"] == 30 and short["expiry"]["flagged"] == []


def test_m5_w01_route_answers_first_then_get_is_final_and_replay_is_stored(client: TestClient, judges: dict[str, Any],
                                                                           v: SimpleNamespace, ai_on: None) -> None:
    """Through POST: the first answer (final false); the label read ran as the request's background task, so GET
    is final. The same Idempotency-Key again (a multipart body has a new boundary, so the middleware's fingerprint
    differs: 422 KEY-REUSED) makes no second look and calls no model; the service replays a key's stored answer."""
    sample = grocery()
    double = double_for(v, sample)
    app.dependency_overrides[get_try_vision_ports] = lambda: try_ports(v, double)
    key = str(uuid.uuid4())
    try:
        r = post_try(client, judges["viewer"], sample.jpeg, C1, key=key)
        calls = len(double.requests)
        again = post_try(client, judges["viewer"], sample.jpeg, C1, key=key)
    finally:
        app.dependency_overrides.pop(get_try_vision_ports, None)
    assert r.status_code == 200, r.text
    assert r.json()["final"] is False and r.json()["say"] == "8 of 8 packs. Reading the labels."
    assert again.status_code == 422 and again.json()["code"] == "FIELD-IDEM-422-KEY-REUSED"
    assert len(double.requests) == calls
    final = _get(client, judges["viewer"], r.json()["look_id"])
    assert final.status_code == 200 and final.json()["final"] is True and final.json()["counts"]["damaged"] == 1
    replay = create_try_look(verify_token(judges["viewer"]), TryIn.model_validate(C1), sample.jpeg, key,
                             try_ports(v, double))
    assert replay == final.json() and len(double.requests) == calls
    with psycopg.connect(_admin()) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM field.vision_look WHERE tenant_id = %s", (judges["tenant"],))
        assert cur.fetchone() == (1,)
        cur.execute("SELECT count(*) FROM field.try_look_slot WHERE tenant_id = %s", (judges["tenant"],))
        assert cur.fetchone() == (1,)
    production = get_try_vision_ports()  # the route's own dependency: SAM and Muse over the try-scoped guard
    assert isinstance(production.instances, Sam31Instances) and production.instances.guard.scope == "try"


def test_m5_w01_rules_mode_when_the_model_is_off(client: TestClient, judges: dict[str, Any], ai_off: None) -> None:
    """AI off: one step, final, source rules, no instances, say asks for a spoken count; the reason says why."""
    r = post_try(client, judges["op"], grocery().jpeg, C1)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["final"] is True and b["source"] == "rules" and b["instances"] == [] and b["say"] == RULES_SAY
    assert b["counts"]["seen"] is None and b["counts"]["expected"] == 8
    assert "instances:sam-3.1:AI_CLOUD_DISABLED" in b["reasons"]


# --------------------------------------------------------------------------- the daily try cap
def test_m5_w01_try_daily_cap_degrades_to_rules(client: TestClient, judges: dict[str, Any], v: SimpleNamespace,
                                                ai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """AI_TRY_DAILY_CAP_USD below one SAM image (0.005): the budget guard refuses the try call; the look answers in
    rules mode with reason AI_TRY_DAILY_CAP, nothing is reserved, and no model is called."""
    monkeypatch.setenv("AI_TRY_DAILY_CAP_USD", "0.001")
    sample = grocery()
    double = double_for(v, sample)
    first, held = held_look(judges["op"], sample.jpeg, C1, try_ports(v, double))
    assert first["final"] is True and first["source"] == "rules" and held == []
    assert first["reasons"] == ["instances:sam-3.1:AI_TRY_DAILY_CAP"] and double.requests == []
    assert first["models"] == [{"model": "sam-3.1", "purpose": "instances", "latency_ms": 0, "cost_usd": 0.0,
                                "outcome": "AI_TRY_DAILY_CAP"}]


def test_m5_w01_budget_guard_try_scope_is_per_tenant_and_extra(ai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Today's try spend of the tenant + the call must stay within AI_TRY_DAILY_CAP_USD (default 3); another tenant
    and a guard without the scope are not limited by it; a reserved try call is recorded as ``try:<purpose>``."""
    prices = {"llama": {}, "baseten": {}, "meta": {"sam-3.1": Price(Decimal(0), Decimal(0),
                                                                     per_image_usd=Decimal("0.005"))}}
    tenant, other = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(_admin()) as c, c.cursor() as cur:
        cur.execute("INSERT INTO ops.ai_usage (provider, model, purpose, status, reserved_usd, cost_usd, tenant_id)"
                    " VALUES ('meta', 'sam-3.1', 'try:vision', 'settled', 2.998, 2.998, %s)", (tenant,))
        c.commit()
    try_guard, plain = BudgetGuard(prices=prices, scope="try"), BudgetGuard(prices=prices)
    with pytest.raises(BudgetRefused) as e:
        try_guard.reserve("meta", "sam-3.1", input_tokens=0, max_output_tokens=1, purpose="vision", tenant_id=tenant,
                          images=1)
    assert e.value.code == "AI_TRY_DAILY_CAP"
    plain.fail(plain.reserve("meta", "sam-3.1", input_tokens=0, max_output_tokens=1, purpose="vision",
                             tenant_id=tenant, images=1))
    r = try_guard.reserve("meta", "sam-3.1", input_tokens=0, max_output_tokens=1, purpose="vision", tenant_id=other,
                          images=1)
    try_guard.fail(r)
    with psycopg.connect(_admin()) as c, c.cursor() as cur:
        cur.execute("SELECT purpose FROM ops.ai_usage WHERE id = %s", (r.id,))
        assert cur.fetchone() == ("try:vision",)
    monkeypatch.setenv("AI_TRY_DAILY_CAP_USD", "10")  # raised: the same tenant fits again
    try_guard.fail(try_guard.reserve("meta", "sam-3.1", input_tokens=0, max_output_tokens=1, purpose="vision",
                                     tenant_id=tenant, images=1))
    with pytest.raises(ValueError):
        BudgetGuard(scope="everything")


# --------------------------------------------------------------------------- rate limit
def test_m5_w01_ten_try_looks_per_principal_per_rolling_hour(client: TestClient, judges: dict[str, Any],
                                                             ai_off: None) -> None:
    """The 11th try look in an hour is 429 FIELD-TRY-429-RATE with Retry-After (seconds, <= 3600); a refused repeat of
    a key takes no slot; another principal of the tenant is not limited by it."""
    photo = small_jpeg()
    keys = [str(uuid.uuid4()) for _ in range(10)]
    for i, key in enumerate(keys[:9]):
        assert post_try(client, judges["op"], photo, C1, key=key).status_code == 200, i
    assert post_try(client, judges["op"], photo, C1, key=keys[0]).status_code == 422  # a repeated key: no slot
    assert post_try(client, judges["op"], photo, C1, key=keys[9]).status_code == 200  # the 10th
    r = post_try(client, judges["op"], photo, C1)
    assert r.status_code == 429 and r.json()["code"] == "FIELD-TRY-429-RATE"
    assert 1 <= int(r.headers["Retry-After"]) <= 3600
    assert post_try(client, judges["op2"], photo, C1).status_code == 200


# --------------------------------------------------------------------------- size, type, fields
def test_m5_w01_size_type_and_fields_are_refused(client: TestClient, judges: dict[str, Any], ai_off: None) -> None:
    big = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 - 2)  # 5 MB + 1 byte
    r = post_try(client, judges["op"], big, C1)
    assert r.status_code == 413 and r.json()["code"] == "FIELD-TRY-413-SIZE"
    huge = b"\xff\xd8\xff" + b"\x00" * (6 * 1024 * 1024)  # refused from Content-Length before the body is read
    assert post_try(client, judges["op"], huge, C1).status_code == 413
    gif = b"GIF89a" + b"\x00" * 64
    r = post_try(client, judges["op"], gif, C1, name="x.gif", ctype="image/gif")
    assert r.status_code == 415 and r.json()["code"] == "FIELD-TRY-415-TYPE"
    text = post_try(client, judges["op"], b"not an image at all", C1, name="x.jpg", ctype="image/jpeg")
    assert text.status_code == 415  # the declared type is not trusted
    broken = post_try(client, judges["op"], b"\xff\xd8\xff\xe0" + b"garbage" * 50, C1)
    assert broken.status_code == 422 and broken.json()["code"] == "FIELD-TRY-422-PHOTO"
    for bad in ({"case": "bakery", "expected_units": 8}, {"case": "grocery", "expected_units": 0},
                {"case": "pharmacy", "expected_units": 5, "window_days": -1}):
        r = post_try(client, judges["op"], small_jpeg(), bad)
        assert r.status_code == 422 and r.json()["code"] == "FIELD-TRY-422-FIELDS", bad
    no_photo = client.post("/v1/try/looks", data={"look": json.dumps(C1)}, files={"other": ("a", b"x", "text/plain")},
                           headers=_auth(judges["op"]))
    assert no_photo.status_code == 422
    with psycopg.connect(_admin()) as c, c.cursor() as cur:  # nothing refused took a rate slot
        cur.execute("SELECT count(*) FROM field.try_look_slot WHERE tenant_id = %s", (judges["tenant"],))
        assert cur.fetchone() == (0,)


def test_m5_w01_png_is_accepted_flattened_and_scaled_to_1600(client: TestClient, judges: dict[str, Any],
                                                             ai_off: None) -> None:
    buf = io.BytesIO()
    Image.new("RGBA", (2400, 1800), (10, 120, 200, 128)).save(buf, format="PNG")
    r = post_try(client, judges["op"], buf.getvalue(), C2, name="p.png", ctype="image/png")
    assert r.status_code == 200, r.text
    assert r.json()["image"]["width"] == 1600 and r.json()["image"]["height"] == 1200
    photo = client.get(r.json()["try"]["photo_url"], headers={"Authorization": f"Bearer {judges['op']}"})
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(photo.content)).size == (1600, 1200)


# --------------------------------------------------------------------------- faces
def test_m5_w01_faces_are_pixelated_before_storing_and_before_any_model_call(client: TestClient, judges: dict[str, Any],
                                                                              v: SimpleNamespace, ai_on: None) -> None:
    """A face in an uploaded photo is found server-side and pixelated: the photo SAM 3.1 receives and the stored photo
    show no face any more, and the body says how many were blurred. The SAMPLE photos have none (labels stay sharp)."""
    sample = pharmacy()
    img = Image.open(io.BytesIO(sample.jpeg)).convert("RGB")
    img.paste(drawn_face(120), (40, 420))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    assert HaarFaces().find(img)  # the drawn face is a face to the detector
    double = double_for(v, sample)
    first, held = held_look(judges["op"], buf.getvalue(), C2, try_ports(v, double))
    assert first["image"]["faces_blurred"] >= 1
    seen_by_sam = sam_image(double)
    assert HaarFaces().find(seen_by_sam) == [] and seen_by_sam.size == (1280, 960)
    stored = client.get(first["try"]["photo_url"], headers={"Authorization": f"Bearer {judges['op']}"})
    assert stored.status_code == 200 and HaarFaces().find(Image.open(io.BytesIO(stored.content))) == []
    held[0]()
    for s in (grocery(), pharmacy()):
        assert HaarFaces().find(Image.open(io.BytesIO(s.jpeg))) == []


def test_m5_w01_pixelate_removes_detail_inside_the_face_box_only() -> None:
    img = drawn_face(100)
    out, n = blur_faces(img)
    assert n >= 1 and HaarFaces().find(out) == []
    same = pixelate(img, [])
    assert same.tobytes() == img.convert("RGB").tobytes()
    corner = (0, 0, 20, 20)
    assert out.crop(corner).tobytes() == img.convert("RGB").crop(corner).tobytes()


# --------------------------------------------------------------------------- who may read what
@pytest.mark.parametrize("role", ["op", "sup", "viewer"])
def test_m5_w01_roles_with_field_try_use(client: TestClient, judges: dict[str, Any], ai_off: None, role: str) -> None:
    r = post_try(client, judges[role], small_jpeg(), C1)
    assert r.status_code == 200, r.text
    assert _get(client, judges[role], r.json()["look_id"]).status_code == 200


@pytest.mark.parametrize("role", ["tech", "ctrl", "integ"])
def test_m5_w01_roles_without_field_try_use_get_403(client: TestClient, judges: dict[str, Any], ai_off: None,
                                                    role: str) -> None:
    mine = post_try(client, judges["op"], small_jpeg(), C1).json()["look_id"]
    assert post_try(client, judges[role], small_jpeg(), C1).status_code == 403
    assert _get(client, judges[role], mine).status_code == 403
    assert client.get(f"/v1/try/looks/{mine}/photo",
                      headers={"Authorization": f"Bearer {judges[role]}"}).status_code == 403


def test_m5_w01_a_try_look_is_its_owners_only_and_never_a_task_look(client: TestClient, judges: dict[str, Any],
                                                                     ai_off: None) -> None:
    """Another principal, another tenant and an unknown id get 404; the vision look API and claims do not see a try
    look; the database refuses linking an ERP document to one."""
    look_id = post_try(client, judges["op"], small_jpeg(), C1).json()["look_id"]
    for who in ("op2", "sup", "stranger"):
        assert _get(client, judges[who], look_id).status_code == 404, who
    assert _get(client, judges["op"], "not-a-uuid").status_code == 404
    assert _get(client, judges["op"], str(uuid.uuid4())).status_code == 404
    vis = client.get(f"/v1/vision/looks/{look_id}", headers={"Authorization": f"Bearer {judges['sup']}"})
    assert vis.status_code == 404
    claim = client.post("/v1/claims", json={"look_id": look_id}, headers=_auth(judges["sup"]))
    assert claim.status_code == 404
    with psycopg.connect(_admin()) as c, c.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute("UPDATE field.vision_look SET task_id = (SELECT id FROM field.task LIMIT 1) WHERE id = %s",
                    (look_id,))


def test_m5_w01_photo_is_gone_after_24_hours(client: TestClient, judges: dict[str, Any], ai_off: None) -> None:
    b = post_try(client, judges["op"], small_jpeg(), C1).json()
    h = {"Authorization": f"Bearer {judges['op']}"}
    assert client.get(b["try"]["photo_url"], headers=h).status_code == 200
    with psycopg.connect(_admin()) as c, c.cursor() as cur:
        cur.execute("UPDATE field.vision_look SET photo_expires_at = NOW() - interval '1 minute' WHERE id = %s",
                    (b["look_id"],))
    gone = client.get(f"/v1/try/looks/{b['look_id']}/photo", headers=h)
    assert gone.status_code == 410 and gone.json()["code"] == "FIELD-TRY-410-PHOTO-EXPIRED"
    assert _get(client, judges["op"], b["look_id"]).json()["try"]["photo_url"] is None
