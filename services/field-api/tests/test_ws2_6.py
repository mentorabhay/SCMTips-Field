"""WS2.6 device, consent, capture, voice and confirm-gate APIs on Postgres (T2.047-T2.055).

C4 rewrite: the previous file drove in-process stores (and mutated them directly). These tests use
the real tables with RLS, a real crop store (tmp dir), device-bound tokens and the live channel.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token
from field_api.routes.voice import staged_hash
from field_worker.retention.job import RetentionCleanerJob

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
JPEG = b"\xff\xd8\xff\xe0" + b"SCMTIPS-test-crop" * 20 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def _crop_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CROP_DIR", str(tmp_path / "crops"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def env() -> dict[str, Any]:
    tenant, site, task, line = (str(uuid.uuid4()) for _ in range(4))
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, status) VALUES (%s,%s,'WS26','DC','warehouse','active')",
                    (site, tenant))
        cur.execute("INSERT INTO field.material (id, tenant_id, erp_material_no, plant, description, base_uom, gtin)"
                    " VALUES (%s, %s, 'MAT-26', '1000', 'carton', 'EA', '09506000134352')", (str(uuid.uuid4()), tenant))
        cur.execute("INSERT INTO field.task (id, tenant_id, site_id, type, status, title, ref_doc_no)"
                    " VALUES (%s, %s, %s, 'receive', 'pending', 'IBD', '180000999')", (task, tenant, site))
        cur.execute("INSERT INTO field.task_line (id, tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom, sscc)"
                    " SELECT %s, %s, %s, %s, 10, id, 12, 'EA', '003012345678901232' FROM field.material WHERE tenant_id = %s",
                    (line, tenant, site, task, tenant))
    return {"tenant": tenant, "site": site, "task": task, "line": line}


def _user(env: dict[str, Any], roles: list[str], device: str | None = None, sub: str = "op-26") -> dict[str, str]:
    tok = create_dev_token(sub, env["tenant"], roles, site_ids=[env["site"]], device_id=device)
    return {"Authorization": f"Bearer {tok}"}


def _phone_and_glasses(client: TestClient, env: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    admin = _user(env, ["field.operator"])
    phone = client.post("/v1/devices", json={"kind": "phone", "serial_no": f"P-{uuid.uuid4()}", "model": "Pixel"},
                        headers=admin).json()["id"]
    r = client.post("/v1/devices", json={"kind": "glasses", "serial_no": f"G-{uuid.uuid4()}",
                                         "model": "ray-ban-meta-gen2", "paired_with": phone}, headers=admin)
    assert r.status_code == 201, r.text
    return phone, r.json()["id"], _user(env, ["field.operator"], device=phone)


def test_t2_047_device_registration_and_pairing(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.103: register phone, pair glasses; a second pairing needs replace=true."""
    phone, glasses, dev = _phone_and_glasses(client, env)
    r = client.get(f"/v1/devices/{glasses}", headers=dev)
    assert r.status_code == 200 and r.json()["paired_with"] == phone and r.json()["status"] == "active"
    op = _user(env, ["field.operator"])
    body = {"kind": "glasses", "serial_no": f"G-{uuid.uuid4()}", "model": "ray-ban-meta-gen2", "paired_with": phone}
    assert client.post("/v1/devices", json=body, headers=op).status_code == 409
    r = client.post("/v1/devices", json={**body, "replace": True}, headers=op)
    assert r.status_code == 201 and r.json()["pairing_id"]
    assert client.post("/v1/devices", json={"kind": "phone", "serial_no": "x", "model": "m"},
                       headers=_user(env, ["field.viewer"])).status_code == 403


def test_t2_047_device_heartbeat_and_config(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.163: heartbeat stores metrics; config has ETag and answers 304 on If-None-Match."""
    phone, _g, dev = _phone_and_glasses(client, env)
    r = client.post(f"/v1/devices/{phone}/heartbeat", json={"battery_pct": 64, "queue_depth": 3,
                                                            "glasses_state": "connected"}, headers=dev)
    assert r.status_code == 200 and r.json()["config_version"] >= 1
    d = client.get(f"/v1/devices/{phone}", headers=dev).json()
    assert d["battery_pct"] == 64 and d["queue_depth"] == 3 and d["is_stale"] is False
    c1 = client.get(f"/v1/devices/{phone}/config", headers=dev)
    assert c1.status_code == 200 and c1.json()["audio_only_prompts"] is True and c1.json()["voice_conf_floor"] == 0.8
    c2 = client.get(f"/v1/devices/{phone}/config", headers={**dev, "If-None-Match": c1.headers["ETag"]})
    assert c2.status_code == 304


def test_t2_047_device_revocation_stops_session(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.102 / T1.038: revoke needs If-Match; afterwards the device token is refused everywhere."""
    phone, _g, dev = _phone_and_glasses(client, env)
    sup = _user(env, ["field.supervisor"], sub="sup-26")
    etag = client.get(f"/v1/devices/{phone}", headers=sup).headers["ETag"]
    assert client.post(f"/v1/devices/{phone}/revoke", json={"reason": "lost"}, headers=sup).status_code == 428
    r = client.post(f"/v1/devices/{phone}/revoke", json={"reason": "lost"}, headers={**sup, "If-Match": etag})
    assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["revoked_at"]
    assert client.post(f"/v1/devices/{phone}/heartbeat", json={}, headers=dev).status_code == 403
    assert client.get("/v1/tasks", headers=dev).status_code == 403  # FIELD-AUTH-403-DEVICE-REVOKED
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (env["tenant"],))
        cur.execute("SELECT tick_type FROM field.device_notification WHERE device_id = %s", (phone,))
        assert ("device.revoked",) in cur.fetchall()


def _capture(env: dict[str, Any], device: str, code: str, **kw: Any) -> dict[str, Any]:
    return {"device_id": device, "task_id": env["task"], "site_id": env["site"], "shutter_timestamp": 1,
            "blur_applied": True, "code_type": "sscc", "code_value": code, "readability": 0.9, **kw}


def test_t2_048_consent_gate_and_withdrawal(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.154: ingest refused without consent (403), allowed after consent, refused after withdrawal."""
    phone, _g, dev = _phone_and_glasses(client, env)
    assert client.post("/v1/captures", json=_capture(env, phone, "A1"), headers=dev).status_code == 403
    assert client.post("/v1/consents", json={"site_id": env["site"], "device_id": phone, "consent_version": "nope"},
                       headers=dev).status_code == 422
    r = client.post("/v1/consents", json={"site_id": env["site"], "device_id": phone}, headers=dev)
    assert r.status_code == 201 and r.json()["user_id"] == "op-26"  # from the token, not the body
    assert client.post("/v1/captures", json=_capture(env, phone, "A1"), headers=dev).status_code == 201
    client.post("/v1/consents", json={"site_id": env["site"], "device_id": phone, "granted": False}, headers=dev)
    assert client.post("/v1/captures", json=_capture(env, phone, "A2"), headers=dev).status_code == 403
    assert client.post("/v1/captures", json=_capture(env, phone, "A3", blur_applied=False),
                       headers=dev).status_code == 422


def _consented(client: TestClient, env: dict[str, Any]) -> tuple[str, dict[str, str]]:
    phone, _g, dev = _phone_and_glasses(client, env)
    client.post("/v1/consents", json={"site_id": env["site"], "device_id": phone}, headers=dev)
    return phone, dev


def test_t2_049_upload_put_and_crop_roundtrip(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.140, TC2.146: upload slot -> PUT bytes (sha256 verified) -> capture -> crop served; outbox event."""
    phone, dev = _consented(client, env)
    sha = hashlib.sha256(JPEG).hexdigest()
    big = client.post("/v1/captures/uploads", json={"device_id": phone, "sha256": sha, "bytes": 2_000_000},
                      headers=dev)
    assert big.status_code == 413
    up = client.post("/v1/captures/uploads", json={"device_id": phone, "sha256": sha, "bytes": len(JPEG)},
                     headers=dev).json()
    assert client.put(up["put_url"], content=JPEG[:-1], headers=dev).status_code == 422  # sha mismatch
    assert client.put(up["put_url"], content=JPEG, headers=dev).status_code == 204
    r = client.post("/v1/captures", json=_capture(env, phone, "003012345678901232", crop_upload_id=up["upload_id"]),
                    headers=dev)
    assert r.status_code == 201, r.text
    cap = r.json()
    assert cap["on_task"] is True and cap["task_line_id"] == env["line"]  # matched by SSCC (TC2.142)
    reader = _user(env, ["field.supervisor"], sub="sup-26")
    crop = client.get(f"/v1/captures/{cap['id']}/crop", headers=reader)
    assert crop.status_code == 200 and crop.content == JPEG
    assert client.get(f"/v1/captures/{cap['id']}/crop", headers=dev).status_code == 403  # operators lack evidence.read
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (env["tenant"],))
        cur.execute("SELECT payload FROM field.outbox WHERE aggregate_id = %s AND event_type = 'capture.created'",
                    (cap["id"],))
        assert cur.fetchone()[0]["data"]["task_line_id"] == env["line"]  # type: ignore[index]
        cur.execute("SELECT sha256_hash FROM field.capture_evidence WHERE capture_id = %s", (cap["id"],))
        assert cur.fetchone()[0] == sha  # type: ignore[index]


def test_t2_051_server_duplicates_and_task_matching(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.141, TC2.142: exact duplicate -> 409 duplicate_of; GTIN in a GS1 string matches the line material."""
    phone, dev = _consented(client, env)
    r1 = client.post("/v1/captures", json=_capture(env, phone, "(01)09506000134352(17)270101", code_type="gs1"),
                     headers=dev)
    assert r1.status_code == 201 and r1.json()["on_task"] is True
    r2 = client.post("/v1/captures", json=_capture(env, phone, "(01)09506000134352(17)270101", code_type="gs1"),
                     headers=dev)
    assert r2.status_code == 409 and r2.json()["errors"][0]["duplicate_of"] == r1.json()["id"]
    r3 = client.post("/v1/captures", json=_capture(env, phone, "SOMETHING-ELSE"), headers=dev)
    assert r3.status_code == 201 and r3.json()["on_task"] is False and r3.json()["task_line_id"] is None


def _voice(client: TestClient, env: dict[str, Any], phone: str, dev: dict[str, str], intent: str,
           at: datetime, conf: float = 0.93, accepted: bool = True) -> Any:
    return client.post("/v1/voice-events", json={"device_id": phone, "task_id": env["task"], "transcript": intent,
                                                 "confidence": conf, "intent": intent, "is_accepted": accepted,
                                                 "client_timestamp": at.isoformat()}, headers=dev)


def test_t2_052_voice_count_and_post_gate(client: TestClient, env: dict[str, Any]) -> None:
    """PR2.11, TC2.133, TC2.162: count by voice, then post only after a confirm turn within 10 s."""
    phone, dev = _consented(client, env)
    t0 = datetime.now(UTC)
    assert _voice(client, env, phone, dev, "count", t0, conf=0.79).status_code == 422  # accepted below floor
    v = _voice(client, env, phone, dev, "count", t0).json()["id"]
    r = client.post("/v1/count-records", json={"task_line_id": env["line"], "value": 12, "unit": "EA",
                                               "voice_event_id": v}, headers=dev)
    assert r.status_code == 201 and r.json()["counted_qty"] == 12
    good = staged_hash([(env["line"], Decimal(12))])
    post = _voice(client, env, phone, dev, "post", t0 + timedelta(seconds=1)).json()["id"]
    late = _voice(client, env, phone, dev, "confirm", t0 + timedelta(seconds=12)).json()["id"]
    body = {"lines": [env["line"]], "staged_hash": good, "post_voice_event_id": post, "confirm_voice_event_id": late}
    url = f"/v1/tasks/{env['task']}/post-requests"
    assert client.post(url, json=body, headers=dev).status_code == 422  # confirm > 10 s after post
    conf = _voice(client, env, phone, dev, "confirm", t0 + timedelta(seconds=4)).json()["id"]
    body["confirm_voice_event_id"] = conf
    assert client.post(url, json={**body, "staged_hash": "0" * 64}, headers=dev).status_code == 422  # wrong lines
    r = client.post(url, json=body, headers=dev)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued" and r.json()["queue_key"] == "IBD:180000999"
    assert client.post(url, json=body, headers=dev).status_code == 409  # one posting per confirm turn


def test_t2_053_live_channel_requires_auth_and_replays(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.144/TC2.145: SSE needs a token, a device reads only its own channel, events replay from the DB."""
    phone, dev = _consented(client, env)
    client.post("/v1/captures", json=_capture(env, phone, "LIVE-1"), headers=dev)
    assert client.get(f"/v1/devices/{phone}/events?once=true").status_code == 401
    other, _g, _ = _phone_and_glasses(client, env)
    assert client.get(f"/v1/devices/{other}/events?once=true", headers=dev).status_code == 403
    r = client.get(f"/v1/devices/{phone}/events?once=true", headers=dev)
    assert r.status_code == 200
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert any(e["kind"] == "received" for e in events)
    last = events[-1]["id"]
    r2 = client.get(f"/v1/devices/{phone}/events?once=true&last_event_id={last}", headers=dev)
    assert not [ln for ln in r2.text.splitlines() if ln.startswith("data: ")]


def test_t2_054_crop_retention_and_legal_hold() -> None:
    """TC2.143: 90-day retention deletes expired items unless is_legal_hold is true."""
    cleaner = RetentionCleanerJob(default_retention_days=90)
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
    records = [
        {"crop_s3_uri": "file://t1/a.jpg", "retention_until": (now - timedelta(days=1)).isoformat(), "is_legal_hold": False},
        {"crop_s3_uri": "file://t1/b.jpg", "retention_until": (now - timedelta(days=1)).isoformat(), "is_legal_hold": True},
        {"crop_s3_uri": "file://t1/c.jpg", "retention_until": (now + timedelta(days=30)).isoformat(), "is_legal_hold": False},
    ]
    deleted: list[str] = []
    audit = cleaner.sweep_evidence(records, now=now, s3_delete_fn=deleted.append)
    assert (audit["deleted_count"], audit["preserved_hold_count"], audit["active_count"]) == (1, 1, 1)
    assert deleted == ["file://t1/a.jpg"]


def test_t2_055_tenant_isolation(client: TestClient, env: dict[str, Any]) -> None:
    """TC2.160: device and capture reads across tenants return 404 (RLS)."""
    phone, dev = _consented(client, env)
    cap = client.post("/v1/captures", json=_capture(env, phone, "ISO-1"), headers=dev).json()["id"]
    stranger = {"Authorization": "Bearer " + create_dev_token("x", str(uuid.uuid4()), ["field.supervisor"],
                                                              site_ids=["*"])}
    assert client.get(f"/v1/devices/{phone}", headers=stranger).status_code == 404
    assert client.get(f"/v1/captures/{cap}", headers=stranger).status_code == 404
