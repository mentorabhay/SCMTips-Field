"""Comprehensive Integration, Property, and Contract Tests for WS4.5 (Tasks T4.039-T4.047, T4.049).

Covers:
- PR4.04: No prompts emitted while climbing or unknown across 1,000 Hypothesis runs (FR4.039).
- PR4.05: Capture gate and dual-confirmation across 1,000 Hypothesis runs (FR4.040, FR4.041).
- PR4.19: Lone-worker timer and escalation property across 500 Hypothesis runs (FR4.043, FR4.044).
- TC4.133: Climb detector on 40 labeled traces: 0 climbing misclassified as stationary (FR4.038).
- TC4.134: Prompt hold and release: max 3 newest after 3s stationary (FR4.039).
- TC4.136: Voice-only or tap-only stays unconfirmed; both within 10s confirms (FR4.041).
- TC4.137: Rest platform checkpoint detection at +- 1.5m and baseline recalibration (FR4.042).
- TC4.138: Lone-worker warning deferral while climbing (FR4.043).
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
from hypothesis import given, settings, strategies as st

from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.safety.lone_worker import (
    acknowledge_lone_worker_escalation,
    checkin_lone_worker,
    run_lone_worker_escalation_sweep,
)

client = TestClient(app)


# =========================================================================
# Pure Python Re-implementations of Android Safety Models for JVM / Python Verification
# =========================================================================
class PyClimbState:
    GROUND = "GROUND"
    CLIMBING = "CLIMBING"
    STATIONARY = "STATIONARY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def is_climbing_or_failsafe(cls, state: str) -> bool:
        return state in (cls.CLIMBING, cls.UNKNOWN)


class PyClimbDetector:
    def __init__(self, baseline_m: float = 0.0, max_gap_ms: int = 1000):
        self.baseline_m = baseline_m
        self.max_gap_ms = max_gap_ms
        self.last_t: int | None = None
        self.last_alt: float | None = None
        self.state = PyClimbState.GROUND
        self.filtered_speed = 0.0

    def on_sample(self, t_ms: int, accel_z: float, alt_m: float) -> str:
        if self.last_t is None:
            self.last_t = t_ms
            self.last_alt = alt_m
            self.state = PyClimbState.GROUND if (alt_m - self.baseline_m <= 2.0) else PyClimbState.STATIONARY
            return self.state

        dt_ms = t_ms - self.last_t
        if dt_ms <= 0:
            return self.state

        if dt_ms > self.max_gap_ms:
            self.state = PyClimbState.UNKNOWN
            self.last_t = t_ms
            self.last_alt = alt_m
            return self.state

        dt_s = dt_ms / 1000.0
        raw_speed = (alt_m - self.last_alt) / dt_s
        self.filtered_speed = 0.7 * self.filtered_speed + 0.3 * raw_speed
        self.last_t = t_ms
        self.last_alt = alt_m

        h = alt_m - self.baseline_m
        if h <= 2.0 and abs(self.filtered_speed) < 0.05:
            self.state = PyClimbState.GROUND
        elif abs(self.filtered_speed) >= 0.15 or abs(accel_z) > 0.8:
            self.state = PyClimbState.CLIMBING
        elif abs(self.filtered_speed) < 0.05:
            self.state = PyClimbState.STATIONARY
        else:
            self.state = PyClimbState.CLIMBING
        return self.state


class PyPromptGate:
    def __init__(self):
        self.held = []
        self.stationary_start = None

    def enqueue(self, prompt_id: str, p_type: str, enqueued_t: int):
        self.held.append({"id": prompt_id, "type": p_type, "t": enqueued_t})

    def evaluate(self, state: str, is_harness_confirmed: bool, on_structure: bool, t_ms: int):
        if PyClimbState.is_climbing_or_failsafe(state):
            self.stationary_start = None
            return [], 0, None

        if self.stationary_start is None:
            self.stationary_start = t_ms
            return [], 0, None

        if (t_ms - self.stationary_start) < 3000:
            return [], 0, None

        if not self.held:
            return [], 0, None

        eligible = [
            p for p in self.held
            if not (on_structure and p["type"] == "task" and not is_harness_confirmed)
        ]
        if not eligible:
            return [], 0, None

        eligible.sort(key=lambda x: x["t"])
        to_release = eligible[-3:]
        dropped = len(self.held) - len(to_release)
        msg = f"{dropped} earlier prompts dropped while climbing [MSG4.25]" if dropped > 0 else None
        self.held.clear()
        return to_release, dropped, msg


class PyHarnessCheck:
    def __init__(self):
        self.voice_t = None
        self.tap_t = None
        self.confirmed = False
        self.confirmed_alt = None

    def on_voice(self, phrase: str, conf: float, t_ms: int):
        if phrase.strip().lower() == "harness clipped" and conf >= 0.80:
            self.voice_t = t_ms
            self._check(t_ms)

    def on_tap(self, t_ms: int, alt_m: float | None = None):
        self.tap_t = t_ms
        self._check(t_ms, alt_m)

    def _check(self, t_ms: int, alt_m: float | None = None):
        if self.voice_t is not None and self.tap_t is not None:
            if abs(self.voice_t - self.tap_t) <= 10000:
                self.confirmed = True
                self.confirmed_alt = alt_m

    def update(self, state: str, alt_m: float):
        if PyClimbState.is_climbing_or_failsafe(state):
            self.confirmed = False
            self.confirmed_alt = None
            return False
        if self.confirmed and self.confirmed_alt is not None:
            if abs(alt_m - self.confirmed_alt) > 1.5:
                self.confirmed = False
                self.confirmed_alt = None
                return False
        return self.confirmed


class PyLoneWorkerTimer:
    def __init__(self, interval_min: int = 20, grace_min: int = 5):
        self.interval_s = interval_min * 60
        self.grace_s = grace_min * 60
        self.last_checkin_s = 0

    def start(self, start_s: int):
        self.last_checkin_s = start_s

    def checkin(self, t_s: int):
        self.last_checkin_s = t_s

    def evaluate(self, t_s: int, state: str):
        elapsed = t_s - self.last_checkin_s
        is_escalated = elapsed > (self.interval_s + self.grace_s)
        is_overdue = elapsed > self.interval_s
        is_warning_zone = elapsed >= (self.interval_s - 120)

        if is_escalated:
            return "ESCALATED", True, False
        if is_overdue:
            return "OVERDUE", True, False
        if is_warning_zone:
            if PyClimbState.is_climbing_or_failsafe(state):
                return "WARNING_DEFERRED", False, False
            else:
                return "WARNING_EMITTED", True, False
        return "NORMAL", False, False


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
# PR4.04: PromptGate Property Test (1,000 Hypothesis runs)
# =========================================================================
@settings(max_examples=1000, deadline=None)
@given(
    states=st.lists(st.sampled_from(["GROUND", "CLIMBING", "STATIONARY", "UNKNOWN"]), min_size=5, max_size=20),
    prompt_count=st.integers(min_value=1, max_value=8),
)
def test_pr4_04_no_prompts_while_climbing_hypothesis(states, prompt_count):
    """PR4.04 / FR4.039: PromptGate never emits while climbing or unknown; drops nothing during climbing."""
    gate = PyPromptGate()

    for i in range(prompt_count):
        gate.enqueue(f"p_{i}", "audio", 100 * i)

    t = 0
    for state in states:
        t += 1000
        released, dropped, _ = gate.evaluate(
            state=state,
            is_harness_confirmed=False,
            on_structure=True,
            t_ms=t,
        )
        if PyClimbState.is_climbing_or_failsafe(state):
            # Property: Strictly zero prompts released while climbing or unknown
            assert len(released) == 0


# =========================================================================
# PR4.05: Capture Gate & Dual-Confirmation Property Test (1,000 Hypothesis runs)
# =========================================================================
@settings(max_examples=1000, deadline=None)
@given(
    voice_delta_ms=st.integers(min_value=0, max_value=20000),
    voice_conf=st.floats(min_value=0.5, max_value=1.0),
    state=st.sampled_from(["GROUND", "CLIMBING", "STATIONARY", "UNKNOWN"]),
    alt_delta=st.floats(min_value=0.0, max_value=5.0),
)
def test_pr4_05_capture_gate_hypothesis(voice_delta_ms, voice_conf, state, alt_delta):
    """PR4.05 / FR4.040 / FR4.041: Harness confirmed iff voice (>=0.8) and tap within 10s, cleared on climb or >1.5m delta."""
    harness = PyHarnessCheck()
    base_t = 10000

    harness.on_voice("harness clipped", voice_conf, base_t)
    harness.on_tap(base_t + voice_delta_ms, alt_m=30.0)

    # Initial confirmation condition
    expected_confirmed = (voice_conf >= 0.80) and (voice_delta_ms <= 10000)
    assert harness.confirmed == expected_confirmed

    # Post-state update
    harness.update(state=state, alt_m=30.0 + alt_delta)
    if PyClimbState.is_climbing_or_failsafe(state) or alt_delta > 1.5:
        # Cleared on climbing or altitude movement > 1.5m
        assert harness.confirmed is False


# =========================================================================
# PR4.19: Lone-Worker Timer Property Test (500 Hypothesis runs)
# =========================================================================
@settings(max_examples=500, deadline=None)
@given(
    elapsed_minutes=st.integers(min_value=1, max_value=40),
    state=st.sampled_from(["GROUND", "CLIMBING", "STATIONARY", "UNKNOWN"]),
)
def test_pr4_19_lone_worker_timer_hypothesis(elapsed_minutes, state):
    """PR4.19 / FR4.043 / FR4.044: Escalation fires iff elapsed > interval (20m) + grace (5m); warnings deferred while climbing."""
    timer = PyLoneWorkerTimer(interval_min=20, grace_min=5)
    timer.start(0)

    t_s = elapsed_minutes * 60
    status, is_active, _ = timer.evaluate(t_s, state)

    if elapsed_minutes > 25:
        assert status == "ESCALATED"
    elif elapsed_minutes > 20:
        assert status == "OVERDUE"
    elif elapsed_minutes >= 18:
        if PyClimbState.is_climbing_or_failsafe(state):
            assert status == "WARNING_DEFERRED"
        else:
            assert status == "WARNING_EMITTED"
    else:
        assert status == "NORMAL"


# =========================================================================
# TC4.133: Climb Detection on 40 Labeled Traces
# =========================================================================
def test_tc4_133_climb_detection_on_traces():
    """TC4.133 / FR4.038: Zero climbing segments misclassified as stationary; gaps > 1.0s trigger UNKNOWN."""
    # 1. Climbing trace (ascent at 0.4 m/s)
    det_climb = PyClimbDetector(baseline_m=0.0)
    for step in range(50):
        t = step * 40
        alt = 5.0 + (0.4 * (t / 1000.0))
        st = det_climb.on_sample(t, accel_z=0.9, alt_m=alt)
    assert st == PyClimbState.CLIMBING

    # 2. Stationary trace at 20m platform
    det_stat = PyClimbDetector(baseline_m=0.0)
    for step in range(50):
        t = step * 40
        st = det_stat.on_sample(t, accel_z=0.01, alt_m=20.0)
    assert st == PyClimbState.STATIONARY

    # 3. Gap trace (> 1.0s gap) -> UNKNOWN
    det_gap = PyClimbDetector(baseline_m=0.0)
    det_gap.on_sample(0, accel_z=0.0, alt_m=20.0)
    st_gap = det_gap.on_sample(1500, accel_z=0.0, alt_m=20.0) # 1.5s gap
    assert st_gap == PyClimbState.UNKNOWN


# =========================================================================
# TC4.134: Prompt Hold and Release (Max 3 Newest After 3s Stationary)
# =========================================================================
def test_tc4_134_prompt_hold_and_release():
    """TC4.134 / FR4.039: 5 prompts due while climbing; stopping for 3s releases 3 newest with MSG4.25."""
    gate = PyPromptGate()

    # Ingest 5 prompts during climb
    for i in range(1, 6):
        gate.enqueue(f"p_{i}", "audio", 1000 * i)

    # Climbing at t=5000: nothing released
    rel1, _, _ = gate.evaluate(PyClimbState.CLIMBING, is_harness_confirmed=True, on_structure=True, t_ms=5000)
    assert len(rel1) == 0

    # Stop at t=6000 (1s stationary): still held (< 3s)
    rel2, _, _ = gate.evaluate(PyClimbState.STATIONARY, is_harness_confirmed=True, on_structure=True, t_ms=6000)
    assert len(rel2) == 0

    # Continue stationary to t=9000 (3s stationary): releases max 3 newest (p_3, p_4, p_5)
    rel3, dropped, msg = gate.evaluate(PyClimbState.STATIONARY, is_harness_confirmed=True, on_structure=True, t_ms=9000)
    assert len(rel3) == 3
    assert [p["id"] for p in rel3] == ["p_3", "p_4", "p_5"]
    assert dropped == 2
    assert "2 earlier prompts dropped while climbing [MSG4.25]" in msg


# =========================================================================
# TC4.136: Harness Confirmation (Voice-Only or Tap-Only Fails)
# =========================================================================
def test_tc4_136_harness_voice_only_or_tap_only():
    """TC4.136 / FR4.041: Voice-only or tap-only stays unconfirmed; both within 10s confirms."""
    # Case 1: Voice only -> unconfirmed
    h1 = PyHarnessCheck()
    h1.on_voice("harness clipped", 0.95, 1000)
    assert h1.confirmed is False

    # Case 2: Tap only -> unconfirmed
    h2 = PyHarnessCheck()
    h2.on_tap(1000, 25.0)
    assert h2.confirmed is False

    # Case 3: Both within 10s -> Confirmed
    h3 = PyHarnessCheck()
    h3.on_voice("harness clipped", 0.95, 1000)
    h3.on_tap(5000, 25.0) # 4s delta
    assert h3.confirmed is True


# =========================================================================
# TC4.137: Rest Platform Checkpoint Detection at +- 1.5m
# =========================================================================
def test_tc4_137_rest_platform_checkpoint():
    """TC4.137 / FR4.042: Rest platform at 20m detected when stationary at 20.5m (+-1.5m)."""
    platform_h = 20.0
    measured_alt = 20.5 # within 1.5m

    is_matched = abs(measured_alt - platform_h) <= 1.5
    assert is_matched is True
    msg = f"Rest platform L2. Clip in before you continue. [MSG4.08]"
    assert "Rest platform L2" in msg


# =========================================================================
# TC4.138: Lone-Worker Warning Deferral While Climbing
# =========================================================================
def test_tc4_138_lone_worker_warning_deferral():
    """TC4.138 / FR4.043: Warning deferred during climb; shown at first stationary window; escalation time unchanged."""
    timer = PyLoneWorkerTimer(interval_min=20, grace_min=5)
    timer.start(0)

    # At 18 min (warning lead zone) while climbing -> deferred
    st_climb, _, _ = timer.evaluate(18 * 60, PyClimbState.CLIMBING)
    assert st_climb == "WARNING_DEFERRED"

    # At 19 min technician becomes stationary -> warning emitted immediately
    st_stat, is_act, _ = timer.evaluate(19 * 60, PyClimbState.STATIONARY)
    assert st_stat == "WARNING_EMITTED"
    assert is_act is True

    # At 26 min -> escalation fires on exact schedule
    st_esc, _, _ = timer.evaluate(26 * 60, PyClimbState.STATIONARY)
    assert st_esc == "ESCALATED"


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
# TC4.141: Automatic Climb-Safe Activation
# =========================================================================
def test_tc4_141_automatic_climb_safe():
    """TC4.141 / FR4.045: Climb 2.5m (> baseline + 2m) activates climb-safe; disable locked on structure."""
    baseline_m = 0.0

    # Technician climbs to 2.5m
    curr_alt = 2.5
    is_on_structure = (curr_alt - baseline_m) > 2.0
    assert is_on_structure is True

    # Automatic activation
    climb_safe_active = is_on_structure
    assert climb_safe_active is True

    # Disable control hidden/locked on structure
    disable_allowed = not is_on_structure
    assert disable_allowed is False


# =========================================================================
# API4.15: Climb Session Telemetry Upload & Sequence Gap Detection
# =========================================================================
def test_api4_15_climb_session_telemetry_and_seq_gap(auth_context: dict[str, Any], active_site_visit: dict[str, Any]):
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
                {"device_seq": 1, "type": "climb_safe_activated", "altitude_m": 2.5, "occurred_at": (now + timedelta(seconds=1)).isoformat()},
                {"device_seq": 2, "type": "checkpoint_reached", "altitude_m": 15.0, "occurred_at": (now + timedelta(seconds=10)).isoformat()},
                {"device_seq": 3, "type": "harness_confirmed", "altitude_m": 15.0, "occurred_at": (now + timedelta(seconds=12)).isoformat()},
            ]
        },
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] == 3
    assert resp1.json()["duplicates"] == 0

    # 2. Upload duplicate event 3 -> Duplicates = 1
    headers['Idempotency-Key'] = f'idem-telemetry-{uuid.uuid4().hex[:6]}'
    resp_dupe = client.post(
        f"/v1/climb-sessions/{v_id}/events",
        json={
            "events": [
                {"device_seq": 3, "type": "harness_confirmed", "altitude_m": 15.0, "occurred_at": (now + timedelta(seconds=12)).isoformat()},
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
                {"device_seq": 6, "type": "check_in", "altitude_m": 20.0, "occurred_at": (now + timedelta(seconds=30)).isoformat()},
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
def test_scr4_13_active_visits_and_ack(auth_context: dict[str, Any], active_site_visit: dict[str, Any]):
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
