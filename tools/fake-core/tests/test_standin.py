"""Stand-in core (dev double of the SCMTIPS core contract, M4 contract section 3).

Every call goes through the real fake-core app over HTTP (TestClient); shapes are checked against the handover
(01, 01a) and the ported ARO client (api/Models.kt, OkHttpScmtipsApiTest.kt).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fake_core.app import app
from fake_core.standin.decisions import check_brief, normalize, parse, sample_decisions
from fake_core.standin.keys import KID_PREFIX
from fake_core.standin.state import DEFAULT_BACKUP_CODE, StandInState
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

client = TestClient(app)
STATE: StandInState = app.state.standin
LR = {"X-Requested-With": "lr"}
APPROVER, OPERATOR = "approver@demo.scmtips.test", "operator@demo.scmtips.test"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    STATE.reset_decisions()
    STATE.failed.clear()
    monkeypatch.setattr(STATE, "strict", False)
    yield
    STATE.reset_decisions()


def sign_in(email: str = APPROVER, device: str | None = None, **extra: Any) -> dict[str, Any]:
    body = {"email": email, "password": STATE.password, "device_id": device or f"dev-{uuid.uuid4().hex[:12]}",
            "device_model": "RAYBAN_META_GEN2", "display_capable": False, "client": "scmtips-field", **extra}
    r = client.post("/v1/auth/app/token", json=body, headers=LR)
    assert r.status_code == 200, r.text
    return dict(r.json())


def spoken(decision_id: str) -> str:
    d = STATE.decision(decision_id)
    assert d is not None
    return d.spoken


def wh(signed: dict[str, Any]) -> dict[str, str]:
    w = signed["wearable"]
    return {"Authorization": f"Bearer {w['token']}", "X-Device-Id": w["device_id"], **LR}


def test_m4_c02_app_sign_in_shape_and_core_claims() -> None:
    s = sign_in()
    assert set(s) >= {"access_token", "token_type", "expires_in", "claims", "wearable", "user", "capabilities"}
    assert s["token_type"] == "Bearer" and s["expires_in"] == 3600
    assert s["capabilities"] == {"approve_decisions": True, "field_operator": False}
    assert s["user"]["email"] == APPROVER and uuid.UUID(s["user"]["id"])
    assert set(s["wearable"]) == {"session_id", "token", "expires_at", "device_id"}
    head = jwt.get_unverified_header(s["access_token"])
    assert head["alg"] == "EdDSA" and head["kid"].startswith(KID_PREFIX)
    jwks = client.get("/v1/core/jwks.json").json()["keys"]
    key = next(k for k in jwks if k["kid"] == head["kid"])
    pub: Any = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(key["x"] + "=="))  # stubs: RSA only
    claims = jwt.decode(s["access_token"], pub, algorithms=["EdDSA"], audience="scmtips-core", issuer="scmtips-core")
    assert claims["permissions"] == ["voice.approve", "decisions.read", "evidence.upload"]
    assert claims["email"] == APPROVER and claims["device_id"] == s["wearable"]["device_id"]
    assert {"sub", "tenant_id", "roles", "sites", "iat", "exp", "jti", "device_binding"} <= set(claims)
    # the core JWKS also carries the legacy dev key, so dev QR tokens keep exchanging against the core path
    assert {k["kid"] for k in client.get("/.well-known/jwks.json").json()["keys"]} < {k["kid"] for k in jwks}
    assert sign_in(OPERATOR)["capabilities"] == {"approve_decisions": False, "field_operator": True}


def test_m4_c02_sign_in_refusals() -> None:
    base = {"email": APPROVER, "password": "wrong", "device_id": "dev-refusal-01", "device_model": "PHONE_ONLY"}
    r = client.post("/v1/auth/app/token", json={**base, "password": STATE.password})
    assert r.status_code == 403 and r.json()["code"] == "missing_requested_with"
    r = client.post("/v1/auth/app/token", json=base, headers=LR)
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    assert client.post("/v1/auth/app/token", json={**base, "device_id": "short"}, headers=LR).status_code == 422
    assert client.post("/v1/auth/app/token", json={**base, "device_model": "X"}, headers=LR).status_code == 422
    for _ in range(4):
        client.post("/v1/auth/app/token", json=base, headers=LR)
    r = client.post("/v1/auth/app/token", json={**base, "password": STATE.password}, headers=LR)
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"
    STATE.strict = True
    r = client.post("/v1/auth/app/token", json={**base, "email": OPERATOR, "password": STATE.password}, headers=LR)
    assert r.status_code == 403 and r.json()["code"] == "pairing_required"


def test_m4_c02_pairing_code_sign_in_and_aro_pairing() -> None:
    STATE.strict = True
    code = client.post("/_standin/pairing-codes", json={"email": OPERATOR}).json()["pairing_code"]
    body = {"pairing_code": code, "device_id": "dev-pairing-01", "device_model": "PHONE_ONLY"}
    r = client.post("/v1/auth/app/token", json=body, headers=LR)
    assert r.status_code == 200 and r.json()["user"]["email"] == OPERATOR
    assert client.post("/v1/auth/app/token", json=body, headers=LR).status_code == 401  # single use
    code2 = client.post("/_standin/pairing-codes", json={"email": APPROVER}).json()["pairing_code"]
    r = client.post("/v1/wearable/sessions", headers=LR, json={
        "pairing_code": code2, "device_id": "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f",
        "device_model": "META_RAYBAN_DISPLAY", "display_capable": True})
    assert r.status_code == 201, r.text
    assert set(r.json()) == {"session_id", "token", "expires_at", "device_id", "user_display_name"}
    assert r.json()["token"].startswith("scmw_")


def test_m4_c02_device_status_at_the_core_path() -> None:
    s = sign_in(OPERATOR)
    dev, tenant = s["wearable"]["device_id"], s["claims"]["tenant_id"]
    ok = client.get(f"/v1/core/devices/{dev}/status", params={"tenant_id": tenant}).json()
    assert ok["status"] == "active" and ok["device_id"] == dev and ok["fingerprint"] and ok["last_seen_at"]
    assert client.get(f"/v1/core/devices/{dev}/status", params={"tenant_id": str(uuid.uuid4())}).json()["status"] == "revoked"
    assert client.get("/v1/core/devices/never-seen-1/status", params={"tenant_id": tenant}).json()["status"] == "revoked"
    client.post(f"/_standin/devices/{dev}/revoke")
    assert client.get(f"/v1/core/devices/{dev}/status", params={"tenant_id": tenant}).json()["status"] == "revoked"
    assert client.get("/v1/wearable/next", headers=wh(s)).status_code == 401  # its sessions end too


def test_m4_c02_wearable_guard() -> None:
    s = sign_in()
    assert client.get("/v1/wearable/next").status_code == 401
    bad = {**wh(s), "X-Device-Id": "another-device"}
    r = client.get("/v1/wearable/next", headers=bad)
    assert r.status_code == 401 and r.json()["code"] == "device_mismatch"
    sessions = client.get("/v1/wearable/sessions", headers=wh(s)).json()["items"]
    mine = next(x for x in sessions if x["current"])
    assert mine["session_id"] == s["wearable"]["session_id"]
    assert client.delete(f"/v1/wearable/sessions/{mine['session_id']}", headers=wh(s)).status_code == 204
    r = client.get("/v1/wearable/next", headers=wh(s))
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_m4_c02_sample_decisions_next_and_briefs() -> None:
    for d in sample_decisions():
        assert len(d.card) <= 240, d.card
        assert 40 <= len(d.spoken.split()) <= 75  # about 20 seconds spoken
        assert d.title.startswith("SAMPLE")
    s = sign_in()
    item = client.get("/v1/wearable/next", headers=wh(s)).json()["item"]
    assert item["band"]["step_up"] is True and item["waiting"] == 2
    assert [o["letter"] for o in item["options"]] == ["A", "B"]
    assert set(item) >= {"decision_id", "title", "card", "spoken", "options", "band", "deadline_at", "waiting"}
    brief = client.get(f"/v1/briefs/decision/{item['decision_id']}", headers=wh(s)).json()
    assert brief["template_text"] == item["spoken"]
    assert client.get("/v1/wearable/next", headers=wh(sign_in(OPERATOR))).json() == {"item": None}


def test_m4_c02_brief_check() -> None:
    s = sign_in()
    did = client.get("/v1/wearable/next", headers=wh(s)).json()["item"]["decision_id"]
    tpl = spoken(did)
    ok = client.post(f"/v1/briefs/decision/{did}/check", json={"text": tpl}, headers=wh(s)).json()
    assert ok == {"accepted": True, "reasons": [], "template_text": tpl}
    bad = client.post(f"/v1/briefs/decision/{did}/check", headers=wh(s),
                      json={"text": "Air freight costs USD 52,000 and takes four days."}).json()
    assert bad["accepted"] is False and len(bad["reasons"]) == 2 and bad["template_text"] == tpl


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(["9", "1,200", "48,000", "4", "18,500", "14"]), max_size=6),
       st.integers(min_value=15, max_value=10**7))
def test_m4_c02_property_check_accepts_template_numbers_only(picked: list[str], foreign: int) -> None:
    """Every number of the template may be used in any order; any other number is refused."""
    tpl = sample_decisions()[0].spoken
    text = "Brief: " + ", then ".join(picked)
    assert check_brief(text, tpl)[0] is True
    if str(foreign) not in {"1200", "48000", "18500"}:
        accepted, reasons = check_brief(text + f" and {foreign}.", tpl)
        assert accepted is False and reasons


def test_m4_c02_grammar() -> None:
    assert parse("Approve option two").letter == "B" and parse("approve option B.").intent == "approve"
    assert parse("option a").letter == "A" and parse("go with option 2").letter == "B"
    assert parse("Confirm").intent == "confirm" and parse("cancel").intent == "cancel"
    assert parse("repeat please").intent == "repeat"
    r = parse("reject because too expensive")
    assert (r.intent, r.reason) == ("reject", "too expensive")
    assert parse("details option b").letter == "B" and parse("what is the weather").intent == "unknown"
    assert normalize("  Approve, Option-Two! ") == "approve option two"


def _cmd(s: dict[str, Any], nonce: str, text: str, key: str | None = None) -> Any:
    return client.post("/v1/voice/commands", json={"nonce": nonce, "transcript": text},
                       headers={**wh(s), "Idempotency-Key": key or str(uuid.uuid4())})


def test_m4_c02_voice_approve_confirm_step_up_committed() -> None:
    s = sign_in()
    item = client.get("/v1/wearable/next", headers=wh(s)).json()["item"]
    ch = client.post("/v1/voice/challenges", json={"decision_id": item["decision_id"]}, headers=wh(s))
    assert ch.status_code == 201
    c = ch.json()
    assert c["turn"] == 1 and c["step_up_fresh"] is False and c["confidence_floor"] == 0.6
    assert {"letter", "option_id", "title", "cost_total", "committed_spend", "band", "details"} <= set(c["options"][0])
    r1 = _cmd(s, c["nonce"], "approve option two").json()
    assert r1["outcome"] == "readback" and r1["step_up_required"] is True and r1["pending"]["option"] == "B"
    assert r1["parsed"]["intent"] == "approve" and r1["parsed"]["slots"] == {"option": "B"}
    reused = _cmd(s, c["nonce"], "approve option two")
    assert reused.status_code == 409 and reused.json()["code"] == "challenge_expired"  # single use
    r2 = _cmd(s, r1["next"]["nonce"], "confirm").json()  # no step-up yet: nothing commits
    assert r2["outcome"] == "readback" and r2["step_up_required"] is True
    assert client.get("/v1/auth/step-up", headers=wh(s)).json() == {
        "fresh": False, "method": None, "verified_at": None, "waived": False}
    wrong = client.post("/v1/auth/step-up", json={"method": "totp", "code": "000000"}, headers=wh(s))
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_code"
    ok = client.post("/v1/auth/step-up", json={"method": "totp", "code": STATE.step_up_code}, headers=wh(s)).json()
    assert ok["fresh"] is True and ok["method"] == "totp"
    key = str(uuid.uuid4())
    r3 = _cmd(s, r2["next"]["nonce"], "confirm", key).json()
    assert r3["outcome"] == "executed" and r3["approval_id"] and r3["next"] is None
    assert r3["decision"]["status"] == "approved"
    assert _cmd(s, r2["next"]["nonce"], "confirm", key).json() == r3  # Idempotency-Key replays the answer
    nxt = client.get("/v1/wearable/next", headers=wh(s)).json()["item"]
    assert nxt["decision_id"] != item["decision_id"] and nxt["waiting"] == 1
    closed = client.post("/v1/voice/challenges", json={"decision_id": item["decision_id"]}, headers=wh(s))
    assert closed.status_code == 409 and closed.json()["code"] == "decision_closed"


def test_m4_c02_voice_other_turns_and_backup_code() -> None:
    s = sign_in()
    d2 = sample_decisions()[1].decision_id
    c = client.post("/v1/voice/challenges", json={"decision_id": d2}, headers=wh(s)).json()
    rep = _cmd(s, c["nonce"], "repeat").json()
    assert rep["outcome"] == "repeat" and rep["say"] == spoken(d2)
    cl = _cmd(s, rep["next"]["nonce"], "what time is it").json()
    assert cl["outcome"] == "clarify"
    nothing = _cmd(s, cl["next"]["nonce"], "confirm").json()
    assert nothing["outcome"] == "clarify"
    det = _cmd(s, nothing["next"]["nonce"], "details option a").json()
    assert det["outcome"] == "details" and det["say"].startswith("Option A")
    rb = _cmd(s, det["next"]["nonce"], "approve option A").json()
    assert rb["step_up_required"] is False  # band under USD 10,000
    assert _cmd(s, rb["next"]["nonce"], "cancel").json()["outcome"] == "cancelled"
    op = sign_in(OPERATOR)
    assert client.post("/v1/voice/challenges", json={"decision_id": d2}, headers=wh(op)).status_code == 403
    ok = client.post("/v1/auth/step-up", json={"method": "backup_code", "code": DEFAULT_BACKUP_CODE.lower()},
                     headers=wh(s)).json()
    assert ok["fresh"] is True


def test_m4_c02_evidence_photo() -> None:
    s = sign_in()
    files = {"image": ("evidence.jpg", b"\xff\xd8\xff\x01\x02", "image/jpeg")}
    data = {"subject_kind": "recovery_plan", "subject_id": str(uuid.uuid4()), "label": "damaged shipment",
            "consent": "true", "segment_prompt": "pallet"}
    r = client.post("/v1/evidence/photos", files=files, data=data, headers=wh(s))
    assert r.status_code == 201, r.text
    assert set(r.json()) == {"id", "subject_kind", "subject_id", "label", "faces_blurred", "mask", "created_at"}
    assert client.post("/v1/evidence/photos", files=files, data={**data, "consent": "false"},
                       headers=wh(s)).status_code == 422
    big = {"image": ("e.gif", b"GIF89a", "image/gif")}
    assert client.post("/v1/evidence/photos", files=big, data=data, headers=wh(s)).status_code == 422


def _signed(secret: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    t = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-SCMTIPS-Timestamp": str(t), "X-SCMTIPS-Signature": f"sha256={sig}"}


def test_m4_c02_feed_receiver_verifies_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(STATE.feeds, "t-inv", ("inventory", "s3cret-inv"))
    monkeypatch.setitem(STATE.feeds, "t-sup", ("open_supply", "s3cret-sup"))
    item = f"RM-{uuid.uuid4().hex[:5].upper()}"
    inv = json.dumps([{"item_code": item, "location_code": "PLANT-GOA", "as_of": "2026-11-03",
                       "on_hand_qty": 420}]).encode()
    r = client.post("/v1/inbound/feeds/t-inv", content=inv, headers=_signed("s3cret-inv", inv))
    assert r.status_code == 200 and r.json() == {"accepted": True, "rows": 1, "duplicate": False}
    again = client.post("/v1/inbound/feeds/t-inv", content=inv, headers=_signed("s3cret-inv", inv))
    assert again.json()["duplicate"] is True
    sup = json.dumps([{"kind": "PO", "ref": "4500001234-10", "item_code": item, "location_code": "PLANT-GOA",
                       "qty": 120, "due_date": "2026-11-03", "status": "received"}]).encode()
    assert client.post("/v1/inbound/feeds/t-sup", content=sup, headers=_signed("s3cret-sup", sup)).status_code == 200
    pushes = client.get("/_standin/feeds/pushes", params={"feed_id": "t-inv"}).json()["items"]
    assert pushes[-1]["rows"][0]["item_code"] == item and pushes[-1]["signature"] == "verified"
    state = client.get("/_standin/feeds/state").json()
    assert any(r["item_code"] == item and r["on_hand_qty"] == 420 for r in state["inventory"])
    assert any(r["ref"] == "4500001234-10" and r["status"] == "received" for r in state["open_supply"])
    # refusals: wrong secret, stale or missing timestamp, unknown feed, bad rows
    r = client.post("/v1/inbound/feeds/t-inv", content=inv, headers=_signed("wrong", inv))
    assert r.status_code == 401 and r.json()["code"] == "bad_signature"
    r = client.post("/v1/inbound/feeds/t-inv", content=inv, headers=_signed("s3cret-inv", inv, int(time.time()) - 301))
    assert r.status_code == 401 and r.json()["code"] == "stale_timestamp"
    h = _signed("s3cret-inv", inv)
    del h["X-SCMTIPS-Timestamp"]
    assert client.post("/v1/inbound/feeds/t-inv", content=inv, headers=h).json()["code"] == "bad_timestamp"
    assert client.post("/v1/inbound/feeds/nope", content=inv, headers=_signed("x", inv)).status_code == 404
    tampered = inv.replace(b"420", b"999")
    assert client.post("/v1/inbound/feeds/t-inv", content=tampered, headers=_signed("s3cret-inv", inv)).status_code == 401
    rows = json.dumps([{"item_code": item, "location_code": "PLANT-GOA", "on_hand_qty": -1}]).encode()
    r = client.post("/v1/inbound/feeds/t-inv", content=rows, headers=_signed("s3cret-inv", rows))
    assert r.status_code == 422 and r.json()["code"] == "invalid_rows"
