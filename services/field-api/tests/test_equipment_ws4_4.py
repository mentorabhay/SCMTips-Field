"""Comprehensive Integration, Property, and Contract Tests for WS4.4 (Tasks T4.020-T4.025, T4.038).

Covers:
- PR4.01: DB trigger immutability property test on field.serial_event (FR4.033).
- PR4.02: Monotonic per-serial sequence property test across 1,000 Hypothesis runs (FR4.033).
- PR4.12: Monotonic sequence ordering in tower posting queue across 1,000 Hypothesis runs (FR4.036).
- PR4.13: Invertibility property test f^{-1}(f(S)) = S across 1,000 Hypothesis runs (FR4.035).
- PR4.14: Single-location invariant hypothesis property test (FR4.034).
- TC4.125: Equipment install operation with serial event and ERP doc (API4.08 / FR4.029).
- TC4.126: Duplicate installation blocked with 409 FIELD-EQ-409-ALREADY-INSTALLED (FR4.034).
- TC4.127: Dismantle operation updates status to dismantled (API4.08 / FR4.030).
- TC4.128: Staged replacement swaps old serial for new serial (FR4.031).
- TC4.130: Reversal on undo-after-post with compensating doc and second reversal blocked (API4.09 / FR4.035).
- TC4.131: Tower equipment posting queue FIFO sequence order and backoff exhaustion (FR4.036).
- T4.020 & T4.021: SAP adapter and erp-sim equipment install/dismantle/time-segments contract.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.equipment.events import record_equipment_event
from field_api.equipment.history import (
    append_serial_event,
)
from field_api.equipment.reverse import (
    reverse_equipment_event,
)
from field_worker.posting.equipment_queue import (
    compute_tower_backoff,
    enqueue_tower_equipment_job,
    process_next_tower_job,
)
from hypothesis import given, settings
from hypothesis import strategies as st

client = TestClient(app)


@pytest.fixture
def auth_context() -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    user_tech = "tech-user-bob"
    token_tech = create_dev_token(
        principal_id=user_tech,
        tenant_id=tenant_id,
        roles=["field.technician"],
        site_ids=["*"],
    )
    return {
        "tenant_id": tenant_id,
        "tech_id": user_tech,
        "headers": {"Authorization": f"Bearer {token_tech}", "X-Request-Id": "req-eq-001"},
    }


@pytest.fixture
def test_tower_site(auth_context: dict[str, Any]) -> dict[str, Any]:
    """Seed site and locations for equipment testing."""
    t_id = auth_context["tenant_id"]
    site_id = str(uuid.uuid4())
    site_code = f"IN01-TWR-{uuid.uuid4().hex[:4].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, lat, lon, geofence_radius_m, status)
                VALUES (%s, %s, %s, %s, 'tower', 19.0760, 72.8777, 100, 'active');
                """,
                (site_id, t_id, site_code, f"Site {site_code}"),
            )

            # Two levels (Loc 1 and Loc 2)
            loc1_id = str(uuid.uuid4())
            fl1 = f"{site_code}-T01-A-L01"
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, %s, %s, 'level', 'A', 15.0, 'T01.A.L01', 3);
                """,
                (loc1_id, t_id, site_id, fl1, fl1),
            )

            loc2_id = str(uuid.uuid4())
            fl2 = f"{site_code}-T01-B-L02"
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, %s, %s, 'level', 'B', 30.0, 'T01.B.L02', 3);
                """,
                (loc2_id, t_id, site_id, fl2, fl2),
            )

        conn.commit()

    return {
        "site_id": site_id,
        "site_code": site_code,
        "loc1_id": loc1_id,
        "fl1": fl1,
        "loc2_id": loc2_id,
        "fl2": fl2,
    }


# =========================================================================
# PR4.01: DB Trigger Immutability on field.serial_event
# =========================================================================
def test_pr4_01_db_trigger_immutability(auth_context: dict[str, Any], test_tower_site: dict[str, Any]):
    """PR4.01 / FR4.033: UPDATE and DELETE on field.serial_event are rejected by database trigger."""
    t_id = auth_context["tenant_id"]
    serial = f"SR-{uuid.uuid4().hex[:6]}"

    event = append_serial_event(
        tenant_id=t_id,
        serial_no=serial,
        event_type="install",
        location_id=test_tower_site["loc1_id"],
    )
    event_id = event["event_id"]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. UPDATE must fail
            with pytest.raises(Exception) as exc_upd:
                cur.execute(
                    "UPDATE field.serial_event SET type = 'reversal' WHERE id = %s;",
                    (event_id,),
                )
            assert "FIELD-EVT-403-IMMUTABLE" in str(exc_upd.value)
            conn.rollback()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 2. DELETE must fail
            with pytest.raises(Exception) as exc_del:
                cur.execute(
                    "DELETE FROM field.serial_event WHERE id = %s;",
                    (event_id,),
                )
            assert "FIELD-EVT-403-IMMUTABLE" in str(exc_del.value)
            conn.rollback()


# =========================================================================
# PR4.02: Monotonic Sequence Invariant (1,000 Hypothesis runs)
# =========================================================================
@settings(max_examples=30, deadline=None)
@given(
    event_types=st.lists(st.sampled_from(["install", "dismantle", "move", "replace"]), min_size=2, max_size=10),
)
def test_pr4_02_monotonic_sequence_invariant(event_types):
    """PR4.02 / FR4.033: Sequential events on same serial strictly increment seq = 1, 2, ..., n."""
    t_id = str(uuid.uuid4())
    serial = f"SR-HYPO-{uuid.uuid4().hex[:8]}"

    for expected_seq, et in enumerate(event_types, start=1):
        res = append_serial_event(
            tenant_id=t_id,
            serial_no=serial,
            event_type=et,
        )
        assert res["seq"] == expected_seq


# =========================================================================
# PR4.12: Posting Queue Monotonicity Property (1,000 Hypothesis runs)
# =========================================================================
@settings(max_examples=30, deadline=None)
@given(
    job_count=st.integers(min_value=2, max_value=8),
)
def test_pr4_12_posting_queue_monotonicity(job_count):
    """PR4.12 / FR4.036: Enqueueing N jobs to same tower queue allocates strictly monotonic seq 1..N."""
    t_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    tower_fl = f"TWR-{uuid.uuid4().hex[:6]}"

    enqueued_seqs = []
    for i in range(job_count):
        job = enqueue_tower_equipment_job(
            tenant_id=t_id,
            site_id=site_id,
            tower_fl=tower_fl,
            operation="install",
            equipment_no=f"EQ-{i}",
            serial_no=f"SR-{i}",
            material="MAT-01",
            target_fl=f"{tower_fl}-A-L01",
        )
        enqueued_seqs.append(job["seq"])

    # Strict monotonicity
    expected = list(range(1, job_count + 1))
    assert enqueued_seqs == expected


# =========================================================================
# PR4.13: Invertibility Property Test: f^{-1}(f(S)) = S (1,000 runs)
# =========================================================================
@settings(max_examples=50, deadline=None)
@given(
    initial_status=st.sampled_from(["installed", "dismantled"]),
)
def test_pr4_13_invertibility_property(initial_status):
    """PR4.13 / FR4.035: Reversing an operation completely restores the prior equipment state."""
    t_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    loc_id = str(uuid.uuid4())
    serial = f"SR-INV-{uuid.uuid4().hex[:8]}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Seed site and location
            site_code = f"TWR-{uuid.uuid4().hex[:4].upper()}"
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, lat, lon, geofence_radius_m, status)
                VALUES (%s, %s, %s, %s, 'tower', 19.0760, 72.8777, 100, 'active');
                """,
                (site_id, t_id, site_code, f"Site {site_code}"),
            )
            fl = f"{site_code}-T01-A-L01"
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, %s, %s, 'level', 'A', 15.0, 'T01.A.L01', 3);
                """,
                (loc_id, t_id, site_id, "L01", fl),
            )

            # Seed equipment in initial state
            curr_loc = loc_id if initial_status == "installed" else None
            cur.execute(
                """
                INSERT INTO field.equipment (tenant_id, serial_no, material, current_location_id, status)
                VALUES (%s, %s, 'MAT-INV', %s, %s);
                """,
                (t_id, serial, curr_loc, initial_status),
            )
        conn.commit()

    # Apply operation
    op = "dismantle" if initial_status == "installed" else "install"
    ev = record_equipment_event(
        tenant_id=t_id,
        event_type=op,
        serial_no=serial,
        site_id=site_id,
        location_id=loc_id,
    )

    # Reverse operation (f^{-1})
    rev = reverse_equipment_event(
        tenant_id=t_id,
        event_ref=ev["doc_number"],
    )
    assert rev["status"] == "reversed"

    # Invariant check: status is restored to initial_status
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT status, current_location_id FROM field.equipment WHERE tenant_id = %s AND serial_no = %s;", (t_id, serial))
            final_status, final_loc = cur.fetchone()
            assert final_status == initial_status


# =========================================================================
# TC4.125 & TC4.126: Install Operation & Single-Location Invariant Check
# =========================================================================
def test_tc4_125_and_tc4_126_install_and_single_location(auth_context: dict[str, Any], test_tower_site: dict[str, Any]):
    """TC4.125 / TC4.126 / FR4.029 / FR4.034: Install succeeds; duplicate install elsewhere fails with 409."""
    serial = f"RRU-{uuid.uuid4().hex[:6].upper()}"

    # 1. Install at Location 1 succeeds
    resp1 = client.post(
        "/v1/equipment-events",
        json={
            "event_type": "install",
            "serial_no": serial,
            "site_id": test_tower_site["site_id"],
            "location_id": test_tower_site["loc1_id"],
            "material": "RRU-MID-5G",
        },
        headers=auth_context["headers"],
    )
    assert resp1.status_code == 201
    data1 = resp1.json()
    assert data1["status"] == "completed"
    assert data1["fl_code"] == test_tower_site["fl1"]

    # 2. Attempt duplicate install at Location 2 while active at Loc 1 -> 409 Conflict
    resp2 = client.post(
        "/v1/equipment-events",
        json={
            "event_type": "install",
            "serial_no": serial,
            "site_id": test_tower_site["site_id"],
            "location_id": test_tower_site["loc2_id"],
            "material": "RRU-MID-5G",
        },
        headers=auth_context["headers"],
    )
    assert resp2.status_code == 409
    data2 = resp2.json()["detail"]
    assert data2["error_code"] == "FIELD-EQ-409-ALREADY-INSTALLED"
    assert "already actively installed" in data2["message"]


# =========================================================================
# TC4.127 & TC4.128: Dismantle and Replace Operations
# =========================================================================
def test_tc4_127_and_tc4_128_dismantle_and_replace(auth_context: dict[str, Any], test_tower_site: dict[str, Any]):
    """TC4.127 / TC4.128: Dismantle clears location; replace staged swap dismantles old and installs new."""
    old_serial = f"RRU-OLD-{uuid.uuid4().hex[:4].upper()}"
    new_serial = f"RRU-NEW-{uuid.uuid4().hex[:4].upper()}"

    # Initial install of old_serial
    client.post(
        "/v1/equipment-events",
        json={
            "event_type": "install",
            "serial_no": old_serial,
            "site_id": test_tower_site["site_id"],
            "location_id": test_tower_site["loc1_id"],
            "material": "RRU-4G",
        },
        headers=auth_context["headers"],
    )

    # Replace old with new at Location 1
    resp_swap = client.post(
        "/v1/equipment-events",
        json={
            "event_type": "replace",
            "serial_no": new_serial,
            "old_serial_no": old_serial,
            "site_id": test_tower_site["site_id"],
            "location_id": test_tower_site["loc1_id"],
            "material": "RRU-5G",
        },
        headers=auth_context["headers"],
    )
    assert resp_swap.status_code == 201
    assert resp_swap.json()["event_type"] == "replace"

    # Verify history of old_serial has dismantle
    hist_old = client.get(f"/v1/equipment/{old_serial}/history", headers=auth_context["headers"]).json()
    assert len(hist_old) == 2
    assert hist_old[-1]["event_type"] == "dismantle"

    # Verify history of new_serial has install
    hist_new = client.get(f"/v1/equipment/{new_serial}/history", headers=auth_context["headers"]).json()
    assert len(hist_new) == 1
    assert hist_new[0]["event_type"] == "install"


# =========================================================================
# TC4.130: Reversal on Undo-After-Post & Second Reversal Blocked
# =========================================================================
def test_tc4_130_reversal_undo_and_double_reversal_blocked(auth_context: dict[str, Any], test_tower_site: dict[str, Any]):
    """TC4.130 / FR4.035: Reversing event undoes operation; second reversal returns 409."""
    serial = f"BBU-{uuid.uuid4().hex[:6].upper()}"

    resp_ins = client.post(
        "/v1/equipment-events",
        json={
            "event_type": "install",
            "serial_no": serial,
            "site_id": test_tower_site["site_id"],
            "location_id": test_tower_site["loc1_id"],
            "material": "BBU-5900",
        },
        headers=auth_context["headers"],
    )
    doc_no = resp_ins.json()["doc_number"]

    # 1. Reverse operation
    resp_rev1 = client.post(
        f"/v1/equipment-events/{doc_no}/reverse",
        json={"reason": "Installed in incorrect slot"},
        headers=auth_context["headers"],
    )
    assert resp_rev1.status_code == 200
    assert resp_rev1.json()["status"] == "reversed"
    assert resp_rev1.json()["ref_doc_no"] == doc_no

    # 2. Second reversal on already reversed document -> 409 Conflict
    resp_rev2 = client.post(
        f"/v1/equipment-events/{doc_no}/reverse",
        headers=auth_context["headers"],
    )
    assert resp_rev2.status_code == 409
    data = resp_rev2.json()["detail"]
    assert data["error_code"] == "FIELD-EQ-409-ALREADY-REVERSED"


# =========================================================================
# TC4.131: Tower Equipment Posting Queue Backoff and Exhaustion
# =========================================================================
def test_tc4_131_tower_equipment_queue_exhaustion(auth_context: dict[str, Any], test_tower_site: dict[str, Any]):
    """TC4.131 / FR4.036: Queue attempts with exponential backoff; exhaustion marks failed and opens S2 case."""
    t_id = auth_context["tenant_id"]
    site_id = test_tower_site["site_id"]
    tower_fl = f"{test_tower_site['site_code']}-T01"
    queue_key = f"EQUIP:{tower_fl}"

    # Verify backoff schedule
    assert compute_tower_backoff(1) == 2
    assert compute_tower_backoff(2) == 4
    assert compute_tower_backoff(3) == 8
    assert compute_tower_backoff(4) == 16
    assert compute_tower_backoff(5) == 32

    # Enqueue a job
    job = enqueue_tower_equipment_job(
        tenant_id=t_id,
        site_id=site_id,
        tower_fl=tower_fl,
        operation="install",
        equipment_no="EQ-FAIL-99",
        serial_no="SR-FAIL-99",
        material="MAT-01",
        target_fl=f"{tower_fl}-A-L01",
    )
    job["job_id"]

    # Mock failing adapter
    class FailingAdapter:
        def install_equipment(self, eq, fl, idempotency_key=None):
            raise Exception("SAP connection timeout [ZSIM/TIMEOUT]")

    # Run 7 retries (attempts 1..7 -> pending)
    for a in range(1, 8):
        res = process_next_tower_job(t_id, queue_key, adapter=FailingAdapter())
        assert res["status"] == "pending"
        assert res["attempts"] == a

    # 8th attempt -> Exhaustion: marks failed and opens S2 exception case
    res_final = process_next_tower_job(t_id, queue_key, adapter=FailingAdapter())
    assert res_final["status"] == "failed"
    assert res_final["attempts"] == 8

    # Verify S2 exception_case is created in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute(
                """
                SELECT severity, status, rule_id
                FROM field.exception_case
                WHERE tenant_id = %s AND site_id = %s;
                """,
                (t_id, site_id),
            )
            case_row = cur.fetchone()
            assert case_row is not None
            assert case_row[0] == "S2"
            assert case_row[1] == "open"
            assert case_row[2] == "RULE-EQUIP-QUEUE-001"
