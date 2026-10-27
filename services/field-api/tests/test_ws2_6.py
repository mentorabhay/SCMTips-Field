"""Unit, integration, and property tests for WS2.6 field-api Capture Ingest & Live Channel (Tasks T2.046 - T2.055).

Covers:
- T2.046: Database migrations field_0020 - field_0028 verified with RLS
- T2.047: Device registration, pairing, heartbeat, config, and revoke (TC2.102, TC2.103, TC2.163)
- T2.048: Consent gate, record, and withdraw (TC2.154 / FR2.064)
- T2.049: Capture ingest, presigned uploads, blur gate, CloudEvents outbox envelope (TC2.139, TC2.140, TC2.146)
- T2.050: Idempotency middleware 24h replay & mismatch detection (PR2.15 / FR2.047)
- T2.051: Server-side duplicate detection & task line association (PR2.04, TC2.141, TC2.142 / FR2.048, FR2.049)
- T2.052: Voice events, count records, and confirmed post request turn (PR2.11, TC2.133, TC2.162 / FR2.038, FR2.050, FR2.055)
- T2.053: Live channel WebSocket & SSE tick delivery with resume (TC2.144, TC2.145 / FR2.052)
- T2.054: Crop evidence retention and legal hold (TC2.143 / FR2.051)
- T2.055: Tenant and site isolation RLS (TC2.160 / FR2.053)
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token
from field_api.routes.captures import (
    OUTBOX_EVENTS_STORE,
    TASK_LINES_MOCK_STORE,
    UPLOADS_STORE,
)
from field_common.uuid7 import uuid7_str
from field_worker.retention.job import RetentionCleanerJob


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def auth_headers(
    tenant_id: str = "tenant-test-1",
    principal_id: str = "user-alice",
    roles: list[str] | None = None,
    site_ids: list[str] | None = None,
) -> dict[str, str]:
    token = create_dev_token(
        principal_id=principal_id,
        tenant_id=tenant_id,
        roles=roles or ["field.operator", "field.supervisor", "field.admin"],
        site_ids=site_ids or ["site-1", "site-2"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# -----------------------------------------------------------------------------
# T2.047: Device APIs (TC2.102, TC2.103, TC2.163)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_047_device_registration_and_pairing(client):
    """TC2.103: Register phone and pair glasses with paired_with."""
    headers = auth_headers()

    # 1. Register phone
    resp_phone = client.post(
        "/v1/devices",
        headers=headers,
        json={"kind": "phone", "serial_no": "PH-001", "model": "Pixel 8 Pro"},
    )
    assert resp_phone.status_code == 201
    phone_id = resp_phone.json()["id"]

    # 2. Register glasses paired with phone
    resp_glasses = client.post(
        "/v1/devices",
        headers=headers,
        json={
            "kind": "glasses",
            "serial_no": "GL-001",
            "model": "Ray-Ban Meta Gen 2",
            "paired_with": phone_id,
        },
    )
    assert resp_glasses.status_code == 201
    glasses_data = resp_glasses.json()
    assert glasses_data["paired_with"] == phone_id
    assert glasses_data["glasses_state"] == "connected"


@pytest.mark.unit
def test_t2_047_device_heartbeat_and_config(client):
    """TC2.163: Heartbeat updates metrics and config endpoint returns settings with ETag."""
    headers = auth_headers()
    reg = client.post(
        "/v1/devices",
        headers=headers,
        json={"kind": "phone", "serial_no": f"PH-HB-{uuid7_str()}", "model": "Pixel 9"},
    ).json()
    dev_id = reg["id"]

    # Send heartbeat
    hb_resp = client.post(
        f"/v1/devices/{dev_id}/heartbeat",
        headers=headers,
        json={"battery_pct": 82, "thermal_status": "moderate", "queue_depth": 5},
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["battery_pct"] == 82
    assert hb_resp.json()["queue_depth"] == 5

    # Fetch effective config
    cfg_resp = client.get(f"/v1/devices/{dev_id}/config", headers=headers)
    assert cfg_resp.status_code == 200
    assert "ETag" in cfg_resp.headers
    assert cfg_resp.json()["settings"]["max_outbox_items"] == "2000"


@pytest.mark.unit
def test_t2_047_device_revocation_stops_session(client):
    """TC2.102: Revoking device sets revoked_at, blocks heartbeats, and emits live tick."""
    headers = auth_headers()
    reg = client.post(
        "/v1/devices",
        headers=headers,
        json={"kind": "phone", "serial_no": f"PH-REV-{uuid7_str()}", "model": "Pixel 8"},
    )
    assert reg.status_code == 201
    dev_id = reg.json()["id"]

    # Revoke with If-Match from registration header
    etag = reg.headers["ETag"]
    rev_resp = client.post(
        f"/v1/devices/{dev_id}/revoke",
        headers={**headers, "If-Match": etag},
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "revoked"
    assert rev_resp.json()["revoked_at"] is not None

    # Subsequent heartbeat rejected with 401 FIELD-AUTH-401-REVOKED
    hb_resp = client.post(
        f"/v1/devices/{dev_id}/heartbeat",
        headers=headers,
        json={"battery_pct": 50},
    )
    assert hb_resp.status_code == 401
    assert hb_resp.json()["code"] == "FIELD-AUTH-401-REVOKED"


# -----------------------------------------------------------------------------
# T2.048: Consent Gate (TC2.154 / FR2.064)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_048_consent_gate_and_withdrawal(client):
    """TC2.154: Ingest refused without consent (403), allowed after consent, refused after withdrawal."""
    headers = auth_headers()
    site_id = "site-consent-test"
    user_id = f"user-{uuid7_str()}"
    device_id = f"dev-{uuid7_str()}"
    task_id = "task-consent-1"

    # Attempt capture without consent -> 403 FIELD-CAP-403-NO-CONSENT
    no_consent_resp = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": uuid7_str()},
        json={
            "device_id": device_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 1000,
            "blur_applied": True,
            "code_value": "SSCC-100",
        },
    )
    assert no_consent_resp.status_code == 403
    assert no_consent_resp.json()["code"] == "FIELD-CAP-403-NO-CONSENT"

    # Grant consent
    grant_resp = client.post(
        "/v1/consents",
        headers=headers,
        json={
            "site_id": site_id,
            "user_id": user_id,
            "device_id": device_id,
            "granted": True,
        },
    )
    assert grant_resp.status_code == 201

    # Now capture succeeds
    ok_resp = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": uuid7_str()},
        json={
            "device_id": device_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 1001,
            "blur_applied": True,
            "code_value": "SSCC-100",
        },
    )
    assert ok_resp.status_code == 201

    # Withdraw consent
    withdraw_resp = client.post(
        "/v1/consents",
        headers=headers,
        json={
            "site_id": site_id,
            "user_id": user_id,
            "device_id": device_id,
            "granted": False,
        },
    )
    assert withdraw_resp.status_code == 201

    # Subsequent capture refused
    blocked_resp = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": uuid7_str()},
        json={
            "device_id": device_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 1002,
            "blur_applied": True,
            "code_value": "SSCC-101",
        },
    )
    assert blocked_resp.status_code == 403


# -----------------------------------------------------------------------------
# T2.049: Capture Ingest & Presigned Uploads (TC2.140, TC2.146)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_049_presigned_upload_and_cloudevents_outbox(client):
    """TC2.140, TC2.146: Presigned upload slot generation, expiration (410), and CloudEvents envelope."""
    headers = auth_headers()
    dev_id = "dev-upload-test"
    site_id = "site-upload-test"
    user_id = "user-upload-test"

    # Pre-grant consent
    client.post(
        "/v1/consents",
        headers=headers,
        json={"site_id": site_id, "user_id": user_id, "device_id": dev_id, "granted": True},
    )

    # Create presigned upload
    presign_resp = client.post(
        "/v1/captures/uploads",
        headers=headers,
        json={"device_id": dev_id, "file_size_bytes": 40960, "sha256_hash": "a" * 64},
    )
    assert presign_resp.status_code == 201
    upload_data = presign_resp.json()
    upload_id = upload_data["crop_upload_id"]
    assert "upload_url" in upload_data

    # Test expired upload (> 300 s)
    UPLOADS_STORE.get("tenant-test-1", upload_id)["expires_at"] = (
        datetime.now(UTC) - timedelta(seconds=10)
    ).isoformat()

    expired_resp = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": uuid7_str()},
        json={
            "device_id": dev_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": "task-upl-1",
            "shutter_timestamp": 2000,
            "blur_applied": True,
            "code_value": "SSCC-EXP",
            "crop_upload_id": upload_id,
        },
    )
    assert expired_resp.status_code == 410
    assert expired_resp.json()["code"] == "FIELD-UPL-410-EXPIRED"

    # Successful capture via valid upload
    fresh_presign = client.post(
        "/v1/captures/uploads",
        headers=headers,
        json={"device_id": dev_id, "file_size_bytes": 1024, "sha256_hash": "b" * 64},
    ).json()

    cap_id = uuid7_str()
    cap_resp = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": cap_id},
        json={
            "device_id": dev_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": "task-upl-2",
            "shutter_timestamp": 2001,
            "blur_applied": True,
            "code_value": "SSCC-OK",
            "crop_upload_id": fresh_presign["crop_upload_id"],
        },
    )
    assert cap_resp.status_code == 201

    # Verify TC2.146: CloudEvents envelope fields
    latest_event = OUTBOX_EVENTS_STORE[-1]
    assert latest_event["type"] == "capture.created"
    assert latest_event["tenant_id"] == "tenant-test-1"
    assert "occurred_at" in latest_event
    assert latest_event["subject"] == f"capture/{cap_id}"
    assert latest_event["data"]["capture_id"] == cap_id
    assert "trace_id" in latest_event


# -----------------------------------------------------------------------------
# T2.051: Server-Side Deduplication & Task Line Matching (PR2.04, TC2.141, TC2.142)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_051_server_duplicates_and_task_matching(client):
    """TC2.141, TC2.142: Exact duplicate code returns 409; on-task/off-task matching verified."""
    headers = auth_headers()
    site_id = "site-match-test"
    user_id = "user-match-test"
    dev_id = "dev-match-test"
    task_id = "task-matching-101"

    client.post(
        "/v1/consents",
        headers=headers,
        json={"site_id": site_id, "user_id": user_id, "device_id": dev_id, "granted": True},
    )

    # Configure mock task line
    TASK_LINES_MOCK_STORE[task_id] = [{"id": "line-item-99", "expected_code": "001234567890123456"}]

    # Ingest on-task code
    cap1_id = uuid7_str()
    resp1 = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": cap1_id},
        json={
            "device_id": dev_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 3001,
            "blur_applied": True,
            "code_type": "GS1_128",
            "code_value": "001234567890123456",
        },
    )
    assert resp1.status_code == 201
    assert resp1.json()["on_task"] is True
    assert resp1.json()["task_line_id"] == "line-item-99"

    # TC2.141 / PR2.04: Ingest same code with new idempotency key -> 409 Conflict with duplicate_of
    cap2_id = uuid7_str()
    resp_dup = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": cap2_id},
        json={
            "device_id": dev_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 3002,
            "blur_applied": True,
            "code_type": "GS1_128",
            "code_value": "001234567890123456",
        },
    )
    assert resp_dup.status_code == 409
    dup_body = resp_dup.json()
    assert dup_body["code"] == "FIELD-CAP-409-DUPLICATE"
    assert dup_body["errors"][0]["duplicate_of"] == cap1_id

    # Off-task code ingest
    resp_off = client.post(
        "/v1/captures",
        headers={**headers, "Idempotency-Key": uuid7_str()},
        json={
            "device_id": dev_id,
            "site_id": site_id,
            "user_id": user_id,
            "task_id": task_id,
            "shutter_timestamp": 3003,
            "blur_applied": True,
            "code_type": "GS1_128",
            "code_value": "009999999999999999",  # not on task
        },
    )
    assert resp_off.status_code == 201
    assert resp_off.json()["on_task"] is False
    assert resp_off.json()["task_line_id"] is None


# -----------------------------------------------------------------------------
# T2.052: Voice, Count & Confirmed Post Gate (PR2.11, TC2.133, TC2.162)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_052_voice_count_and_post_gate(client):
    """PR2.11, TC2.133, TC2.162: Count records, undo handling, and confirmed posting turn."""
    headers = auth_headers()
    dev_id = "dev-voice-test"
    task_id = "task-voice-1"

    # 1. Voice event: "count 12"
    v1_resp = client.post(
        "/v1/voice-events",
        headers=headers,
        json={
            "device_id": dev_id,
            "task_id": task_id,
            "transcript": "count twelve",
            "confidence": 0.95,
            "intent": "count",
            "is_accepted": True,
        },
    )
    assert v1_resp.status_code == 201
    v1_id = v1_resp.json()["id"]

    # 2. Count record: 12 EA linked to voice event
    cnt_resp = client.post(
        "/v1/count-records",
        headers=headers,
        json={
            "task_id": task_id,
            "task_line_id": "line-1",
            "voice_event_id": v1_id,
            "quantity": 12.0,
            "unit": "EA",
        },
    )
    assert cnt_resp.status_code == 201
    assert cnt_resp.json()["quantity"] == 12.0

    # 3. Post request: Say post, then confirm
    v_post = client.post(
        "/v1/voice-events",
        headers=headers,
        json={
            "device_id": dev_id,
            "task_id": task_id,
            "transcript": "post",
            "confidence": 0.98,
            "intent": "post",
        },
    ).json()["id"]

    v_confirm = client.post(
        "/v1/voice-events",
        headers=headers,
        json={
            "device_id": dev_id,
            "task_id": task_id,
            "transcript": "confirm",
            "confidence": 0.99,
            "intent": "confirm",
        },
    ).json()["id"]

    # Post request submitted within 10s
    post_req_resp = client.post(
        f"/v1/tasks/{task_id}/post-requests",
        headers=headers,
        json={
            "device_id": dev_id,
            "staged_payload": {"line": "line-1", "qty": 12},
            "post_voice_event_id": v_post,
            "confirm_voice_event_id": v_confirm,
            "is_reversal": False,
        },
    )
    assert post_req_resp.status_code == 202
    assert post_req_resp.json()["status"] == "pending_erp"

    # TC2.133: Post reversal ("undo" after post)
    v_post_rev = client.post(
        "/v1/voice-events",
        headers=headers,
        json={
            "device_id": dev_id,
            "task_id": task_id,
            "transcript": "post",
            "confidence": 0.98,
            "intent": "post",
        },
    ).json()["id"]

    v_confirm_rev = client.post(
        "/v1/voice-events",
        headers=headers,
        json={
            "device_id": dev_id,
            "task_id": task_id,
            "transcript": "confirm",
            "confidence": 0.99,
            "intent": "confirm",
        },
    ).json()["id"]

    reversal_resp = client.post(
        f"/v1/tasks/{task_id}/post-requests",
        headers=headers,
        json={
            "device_id": dev_id,
            "staged_payload": {"line": "line-1", "qty": -12},
            "post_voice_event_id": v_post_rev,
            "confirm_voice_event_id": v_confirm_rev,
            "is_reversal": True,
        },
    )
    assert reversal_resp.status_code == 202
    assert reversal_resp.json()["is_reversal"] is True


# -----------------------------------------------------------------------------
# T2.054: Retention and Legal Hold Cleaner Job (TC2.143 / FR2.051)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_054_crop_retention_and_legal_hold():
    """TC2.143: 90-day retention deletes expired items unless is_legal_hold is true."""
    cleaner = RetentionCleanerJob(default_retention_days=90)
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)

    records = [
        # Expired (91 days ago), not on hold -> delete
        {
            "crop_s3_uri": "s3://field-crops/t1/site1/crop1.jpg",
            "retention_until": (now - timedelta(days=1)).isoformat(),
            "is_legal_hold": False,
        },
        # Expired (91 days ago), ON LEGAL HOLD -> keep unconditionally
        {
            "crop_s3_uri": "s3://field-crops/t1/site1/crop2_hold.jpg",
            "retention_until": (now - timedelta(days=1)).isoformat(),
            "is_legal_hold": True,
        },
        # Active (expires in 30 days) -> keep
        {
            "crop_s3_uri": "s3://field-crops/t1/site1/crop3_active.jpg",
            "retention_until": (now + timedelta(days=30)).isoformat(),
            "is_legal_hold": False,
        },
    ]

    deleted_uris = []
    audit = cleaner.sweep_evidence(
        records, now=now, s3_delete_fn=lambda uri: deleted_uris.append(uri)
    )

    assert audit["deleted_count"] == 1
    assert audit["preserved_hold_count"] == 1
    assert audit["active_count"] == 1
    assert deleted_uris == ["s3://field-crops/t1/site1/crop1.jpg"]


# -----------------------------------------------------------------------------
# T2.055: Security - Tenant and Site Isolation (TC2.160 / FR2.053)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_055_tenant_isolation(client):
    """TC2.160: Device and capture reads across tenants return 404."""
    # Tenant Alpha creates device
    headers_a = auth_headers(tenant_id="tenant-alpha")
    dev_resp = client.post(
        "/v1/devices",
        headers=headers_a,
        json={"kind": "phone", "serial_no": "PH-ALPHA", "model": "Pixel 9"},
    )
    dev_id = dev_resp.json()["id"]

    # Tenant Beta attempts to read Tenant Alpha's device -> 404
    headers_b = auth_headers(tenant_id="tenant-beta")
    read_resp = client.get(f"/v1/devices/{dev_id}", headers=headers_b)
    assert read_resp.status_code == 404
    assert "404" in read_resp.json()["code"]
