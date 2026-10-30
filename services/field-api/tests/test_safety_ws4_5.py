"""Comprehensive Integration, Property, and Contract Tests for WS4.5 (Tasks T4.039-T4.047, T4.049).

The on-device safety logic (climb state, prompt gate, harness check, rest platforms, climb-safe,
lone-worker timer: TC4.133/134/136/137/138/141) used to be tested here against Python
re-implementations of the Kotlin classes. That coverage moved to JUnit tests that drive the
production classes in apps/field-android/core-safety/src/test/kotlin/. This file keeps only the
server-side tests:
- TC4.139: Escalation sweep on visit > 25 min without heartbeat (FR4.044).
- TC4.141: Automatic climb-safe activation at baseline + 2.0m (FR4.045).
- API4.15: Telemetry event upload with sequence gap detection (409 FIELD-SAFE-409-SEQ-GAP) and deduplication.
- SCR4.13: Active visits monitoring and supervisor escalation acknowledgment (field.visit.ack).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.safety.lone_worker import (
    run_lone_worker_escalation_sweep,
)

client = TestClient(app)


# =========================================================================
# Fixtures
# =========================================================================
@pytest.fixture
def auth_context() -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = create_dev_token(
        principal_id=user_id,
        tenant_id=tenant_id,
        roles=["field.technician", "field.supervisor"],
        site_ids=["*"],
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "headers": {"Authorization": f"Bearer {token}", "X-Request-Id": "req-safe-001"},
    }


@pytest.fixture
def active_site_visit(auth_context: dict[str, Any]) -> dict[str, Any]:
    t_id = auth_context["tenant_id"]
    u_id = auth_context["user_id"]
    site_id = str(uuid.uuid4())
    visit_id = str(uuid.uuid4())
    site_code = f"IN01-TWR-{uuid.uuid4().hex[:4].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, lat, lon, geofence_radius_m, status)
                VALUES (%s, %s, %s, %s, 'tower', 19.0760, 72.8777, 150, 'active');
                """,
                (site_id, t_id, site_code, f"Site {site_code}"),
            )

            cur.execute(
                """
                INSERT INTO field.site_visit (
                    id, tenant_id, site_id, user_id, permit_ref, permit_valid_until,
                    checkin_lat, checkin_lon, checkin_accuracy_m, status, timer_interval_min,
                    last_heartbeat_at, last_altitude_m, last_tower_fl
                ) VALUES (
                    %s, %s, %s, %s, 'PERMIT-2026-SAFE', NOW() + interval '8 hours',
                    19.0760, 72.8777, 10.0, 'on_structure', 20,
                    NOW(), 25.0, %s
                );
                """,
                (visit_id, t_id, site_id, u_id, f"{site_code}-T01"),
            )
        conn.commit()

    return {
        "site_id": site_id,
        "site_code": site_code,
        "visit_id": visit_id,
        "user_id": u_id,
    }


# =========================================================================
# TC4.139: Escalation Sweep on Visit > 25 min Without Heartbeat
# =========================================================================
def test_tc4_139_escalation_sweep(auth_context: dict[str, Any], active_site_visit: dict[str, Any]):
    """TC4.139 / FR4.044: Visit with last heartbeat 26 min ago transitions to 'escalated' and emits event."""
    t_id = auth_context["tenant_id"]
    v_id = active_site_visit["visit_id"]

    # Backdate last_heartbeat_at to 26 minutes ago
    backdate = datetime.now(UTC) - timedelta(minutes=26)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute(
                "UPDATE field.site_visit SET last_heartbeat_at = %s, status = 'on_structure' WHERE id = %s;",
                (backdate, v_id),
            )
        conn.commit()

    # Trigger escalation sweep
    transitions = run_lone_worker_escalation_sweep(tenant_id=t_id)
    assert len(transitions) >= 1
    match = next((tr for tr in transitions if tr["visit_id"] == v_id), None)
    assert match is not None
    assert match["new_status"] == "escalated"

    # Verify visit is now 'escalated' in DB and outbox event emitted
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT status FROM field.site_visit WHERE id = %s;", (v_id,))
            assert cur.fetchone()[0] == "escalated"

            cur.execute(
                "SELECT event_type, payload FROM field.outbox WHERE tenant_id = %s AND aggregate_id = %s;",
                (t_id, v_id),
            )
            outbox_row = cur.fetchone()
            assert outbox_row is not None
            assert outbox_row[0] == "field.visit.escalated"
            payload = json.loads(outbox_row[1]) if isinstance(outbox_row[1], str) else outbox_row[1]
            assert "Overdue check-in" in payload["message"]





# =========================================================================
# API4.15: Climb Session Telemetry Upload & Sequence Gap Detection
# =========================================================================
def test_api4_15_climb_session_telemetry_and_seq_gap(
    auth_context: dict[str, Any], active_site_visit: dict[str, Any]
):
    """API4.15 / FR4.067: Telemetry upload enforces sequence; gap returns 409 FIELD-SAFE-409-SEQ-GAP."""
    v_id = active_site_visit["visit_id"]
    headers = dict(auth_context["headers"])
    headers["Idempotency-Key"] = f"idem-telemetry-{uuid.uuid4().hex[:6]}"

    now = datetime.now(UTC)

    # 1. Upload initial events 1, 2, 3 -> Accepted
    resp1 = client.post(
        f"/v1/climb-sessions/{v_id}/events",
        json={
            "events": [
                {
                    "device_seq": 1,
                    "type": "climb_safe_activated",
                    "altitude_m": 2.5,
                    "occurred_at": (now + timedelta(seconds=1)).isoformat(),
                },
                {
                    "device_seq": 2,
                    "type": "checkpoint_reached",
                    "altitude_m": 15.0,
                    "occurred_at": (now + timedelta(seconds=10)).isoformat(),
                },
                {
                    "device_seq": 3,
                    "type": "harness_confirmed",
                    "altitude_m": 15.0,
                    "occurred_at": (now + timedelta(seconds=12)).isoformat(),
                },
            ]
        },
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] == 3
    assert resp1.json()["duplicates"] == 0

    # 2. Upload duplicate event 3 -> Duplicates = 1
    headers["Idempotency-Key"] = f"idem-telemetry-{uuid.uuid4().hex[:6]}"
    resp_dupe = client.post(
        f"/v1/climb-sessions/{v_id}/events",
        json={
            "events": [
                {
                    "device_seq": 3,
                    "type": "harness_confirmed",
                    "altitude_m": 15.0,
                    "occurred_at": (now + timedelta(seconds=12)).isoformat(),
                },
            ]
        },
        headers=headers,
    )
    assert resp_dupe.status_code == 200
    assert resp_dupe.json()["duplicates"] == 1

    # 3. Gap attempt: next expected is 4, but client sends 6 -> 409 Conflict FIELD-SAFE-409-SEQ-GAP
    headers["Idempotency-Key"] = f"idem-telemetry-{uuid.uuid4().hex[:6]}"
    resp_gap = client.post(
        f"/v1/climb-sessions/{v_id}/events",
        json={
            "events": [
                {
                    "device_seq": 6,
                    "type": "check_in",
                    "altitude_m": 20.0,
                    "occurred_at": (now + timedelta(seconds=30)).isoformat(),
                },
            ]
        },
        headers=headers,
    )
    assert resp_gap.status_code == 409
    err = resp_gap.json()["detail"]
    assert err["error_code"] == "FIELD-SAFE-409-SEQ-GAP"
    assert err["expected_seq"] == 4
    assert err["received_min_seq"] == 6


# =========================================================================
# SCR4.13: Active Safety Visits Query and Supervisor Acknowledgment
# =========================================================================
def test_scr4_13_active_visits_and_ack(
    auth_context: dict[str, Any], active_site_visit: dict[str, Any]
):
    """SCR4.13 / FR4.044: Active visits monitor lists visits; supervisor acknowledge updates status and emits event."""
    v_id = active_site_visit["visit_id"]
    headers = auth_context["headers"]

    # 1. Query active safety visits
    resp_active = client.get("/v1/safety/active-visits", headers=headers)
    assert resp_active.status_code == 200
    data = resp_active.json()
    assert data["total_active"] >= 1
    visit_data = next((v for v in data["visits"] if v["visit_id"] == v_id), None)
    assert visit_data is not None
    assert visit_data["status"] == "on_structure"
    assert visit_data["last_altitude_m"] == 25.0

    # 2. Supervisor Acknowledge
    resp_ack = client.post(
        f"/v1/safety/visits/{v_id}/ack",
        json={"notes": "All clear, climber confirmed on radio"},
        headers=headers,
    )
    assert resp_ack.status_code == 200
    assert resp_ack.json()["acknowledged_by"] == auth_context["user_id"]
    assert resp_ack.json()["acked_at"] is not None

    # 3. Technician Check-In
    resp_checkin = client.post(
        f"/v1/safety/visits/{v_id}/check-in",
        json={"altitude_m": 28.0, "tower_fl": f"{active_site_visit['site_code']}-T01"},
        headers=headers,
    )
    assert resp_checkin.status_code == 200
    assert resp_checkin.json()["timer_interval_min"] == 20
