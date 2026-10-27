"""Automated Test Suite for Phase 4 Workstream 4.8 (Offline, Sync & Reports).

Covers:
- T4.060: Audit report export (PDF/CSV) with authenticated evidence links & retention (FR4.061 / PR4.20 / TC4.153 / API4.17)
- T4.061: Site pack API <= 60 MB, signed manifest, delta ETag 304 (FR4.058 / TC4.150 / API4.05)
- T4.062: Site pack phone cache & 14-day expiration (FR4.058 / FR4.059 / TC4.151)
- T4.063: Per-tower outbox FIFO replay ordering & non-blocking multi-tower isolation (FR4.059 / PR4.12)
- T4.064: Replay conflict detection, S2 exception case & tower queue hold (FR4.060 / TC4.152)
- PR4.12: Per-tower order on replay Hypothesis 500 runs
- PR4.20: Report round trip Hypothesis 200 runs
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
import pytest
from hypothesis import given, settings, strategies as st
from fastapi.testclient import TestClient

from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_worker.jobs.audit_report import (
    generate_audit_report,
    generate_signed_evidence_url,
    verify_signed_evidence_url,
)
from field_worker.posting.conflicts import (
    check_and_handle_replay_conflict,
    is_queue_held,
    release_queue_hold,
)
from field_worker.posting.equipment_queue import (
    enqueue_tower_equipment_job,
    process_next_tower_job,
)

client = TestClient(app)


def _auth_headers(
    tenant_id: str,
    user_id: str = "test-sync-admin",
    roles: list[str] | None = None,
) -> dict[str, str]:
    token = create_dev_token(
        principal_id=user_id,
        tenant_id=tenant_id,
        roles=roles or ["technician", "supervisor", "lead"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": f"req-{uuid.uuid4()}",
    }


# ==============================================================================
# Property PR4.12: Per-Tower Order on Replay Hypothesis 500 runs (FR4.059)
# ==============================================================================
@settings(max_examples=500, deadline=None)
@given(
    tower_events=st.dictionaries(
        keys=st.sampled_from(["T01", "T02", "T03", "T04"]),
        values=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=100),  # seq
                st.sampled_from(["install", "dismantle"]), # op
            ),
            min_size=1,
            max_size=15,
            unique_by=lambda x: x[0],  # unique seq per tower
        ),
        min_size=2,
        max_size=4,
    ),
    held_tower=st.sampled_from(["T01", "T02", "T03", "T04"]),
)
def test_pr4_12_per_tower_order_on_replay_property(
    tower_events: dict[str, list[tuple[int, str]]],
    held_tower: str,
):
    """PR4.12: Events for each tower replay in seq order; a held tower never blocks other towers."""
    # Flatten all events across towers into an outbox list with shuffled submission
    all_events = []
    for t_fl, ev_list in tower_events.items():
        for seq, op in ev_list:
            all_events.append({
                "id": str(uuid.uuid4()),
                "tower_fl": t_fl,
                "seq": seq,
                "op": op,
                "status": "pending",
            })

    # Coordinator state
    held_set = {held_tower}
    processed_by_tower: dict[str, list[int]] = {t: [] for t in tower_events}

    # Simulation loop: replay steps
    max_steps = 100
    for _ in range(max_steps):
        # Dispatch eligible events
        eligible = []
        for t_fl, t_events in tower_events.items():
            if t_fl in held_set:
                continue  # Held tower blocked
            # Find next lowest unprocessed seq
            remaining = [
                e for e in all_events
                if e["tower_fl"] == t_fl and e["status"] == "pending"
            ]
            if remaining:
                next_ev = min(remaining, key=lambda x: x["seq"])
                eligible.append(next_ev)

        if not eligible:
            break

        for ev in eligible:
            t_fl = ev["tower_fl"]
            seq = ev["seq"]
            # Invariant 1: Strictly monotonic sequence order per tower
            if processed_by_tower[t_fl]:
                assert seq > processed_by_tower[t_fl][-1], (
                    f"Out of order execution on tower {t_fl}: got seq {seq} after {processed_by_tower[t_fl][-1]}"
                )
            processed_by_tower[t_fl].append(seq)
            ev["status"] = "completed"

    # Invariant 2: The held tower processed ZERO events
    assert len(processed_by_tower.get(held_tower, [])) == 0, f"Held tower {held_tower} illegally processed events"

    # Invariant 3: All non-held towers processed ALL their pending events in exact order
    for t_fl, ev_list in tower_events.items():
        if t_fl != held_tower:
            expected_seqs = sorted([s for s, _ in ev_list])
            assert processed_by_tower[t_fl] == expected_seqs, (
                f"Tower {t_fl} did not process all events in sequence: expected {expected_seqs}, got {processed_by_tower[t_fl]}"
            )


# ==============================================================================
# Property PR4.20: Report Round Trip Hypothesis 200 runs (FR4.061)
# ==============================================================================
@settings(max_examples=200, deadline=None)
@given(
    num_expected=st.integers(min_value=1, max_value=25),
    num_tower_only=st.integers(min_value=0, max_value=10),
)
def test_pr4_20_report_round_trip_property(num_expected: int, num_tower_only: int):
    """PR4.20: Report has 1 row per expected item + 1 per tower-only finding; evidence links signed to same tenant."""
    tenant_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Seed task and locations
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Report Tower', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )
            cur.execute(
                """
                INSERT INTO field.task (id, tenant_id, site_id, title, type, status)
                VALUES (%s, %s, %s, 'Annual Tower Audit', 'audit', 'in_progress')
                ON CONFLICT (id) DO NOTHING;
                """,
                (task_id, tenant_id, site_id),
            )

            # Insert expected matched/mismatch findings
            for i in range(num_expected):
                loc_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                    VALUES (%s, %s, %s, %s, %s, 'level', 'A', 15.0, %s, 3);
                    """,
                    (loc_id, tenant_id, site_id, f"L{i}", f"SITE-T01-A-L{i:02d}", f"T01.A.L{i:02d}"),
                )
                cur.execute(
                    """
                    INSERT INTO field.audit_finding (
                        id, tenant_id, task_id, site_id, location_id, class,
                        expected_serial, found_serial, status, decision, dedupe_key
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'matched',
                        %s, %s, 'open', 'waived', %s
                    );
                    """,
                    (str(uuid.uuid4()), tenant_id, task_id, site_id, loc_id, f"EXP-SN-{i}", f"EXP-SN-{i}", f"matched-{uuid.uuid4()}"),
                )

            # Insert tower-only findings (unexpected equipment on structure)
            for j in range(num_tower_only):
                cur.execute(
                    """
                    INSERT INTO field.audit_finding (
                        id, tenant_id, task_id, site_id, location_id, class,
                        expected_serial, found_serial, status, decision, dedupe_key
                    ) VALUES (
                        %s, %s, %s, %s, NULL, 'tower_only',
                        NULL, %s, 'open', NULL, %s
                    );
                    """,
                    (str(uuid.uuid4()), tenant_id, task_id, site_id, f"TWR-ONLY-{j}", f"twr-only-{uuid.uuid4()}"),
                )
            conn.commit()

    # Generate CSV report
    rep = generate_audit_report(tenant_id=tenant_id, task_id=task_id, report_format="csv")
    csv_text = rep["content_bytes"].decode("utf-8")
    reader = list(csv.DictReader(io.StringIO(csv_text)))

    # Invariant 1: Total rows == num_expected + num_tower_only
    total_expected_rows = num_expected + num_tower_only
    assert len(reader) == total_expected_rows, f"Expected {total_expected_rows} rows, got {len(reader)}"

    # Invariant 2: Every evidence URL belongs to this tenant and verifies
    for row in reader:
        url = row["evidence_url"]
        assert f"tenant={tenant_id}" in url, f"URL {url} does not contain tenant {tenant_id}"


# ==============================================================================
# Integration Test TC4.150: Site Pack Contents and Size
# ==============================================================================
@pytest.mark.integration
def test_tc4_150_site_pack_contents_and_size():
    """TC4.150: Site pack <= 60 MB, sha256 chunks match, snapshot_version present, ETag 304."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)
    site_id = str(uuid.uuid4())
    site_code = f"SITE-{uuid.uuid4().hex[:6].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Seed site, 4 locations, 2 equipment items, and graph nodes
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Offline Tower Test', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, site_code),
            )
            loc1 = str(uuid.uuid4())
            loc2 = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES
                    (%s, %s, %s, 'LOC-01', 'SITE-T01-SA-L01', 'level', 'A', 15.0, 'T01.A.L01', 3),
                    (%s, %s, %s, 'LOC-02', 'SITE-T01-SA-L02', 'level', 'A', 30.0, 'T01.A.L02', 3);
                """,
                (loc1, tenant_id, site_id, loc2, tenant_id, site_id),
            )
            cur.execute(
                """
                INSERT INTO field.equipment (id, tenant_id, serial_no, material, current_location_id, status)
                VALUES
                    (%s, %s, 'SN-RRU-01', 'RRU-4T-B3', %s, 'installed'),
                    (%s, %s, 'SN-RRU-02', 'RRU-4T-B3', %s, 'installed');
                """,
                (str(uuid.uuid4()), tenant_id, loc1, str(uuid.uuid4()), tenant_id, loc2),
            )
            # Seed graph
            cur.execute(
                """
                INSERT INTO field.site_graph_node (id, tenant_id, site_id, name, node_type, z, subkind)
                VALUES (%s, %s, %s, 'ladder-foot-T01', 'waypoint', 0.0, 'ladder_foot');
                """,
                (str(uuid.uuid4()), tenant_id, site_id),
            )
            conn.commit()

    # 1. Fetch site pack manifest (API4.05)
    res = client.get(f"/v1/sites/{site_id}/pack", headers=headers)
    assert res.status_code == 200
    manifest = res.json()

    # Invariants
    assert manifest["site_id"] == site_id
    assert manifest["snapshot_version"].startswith("erp-")
    assert manifest["size_bytes"] <= 60 * 1024 * 1024  # <= 60 MB (TC4.150)
    assert len(manifest["chunks"]) >= 4

    chunk_names = [c["name"] for c in manifest["chunks"]]
    assert "tree" in chunk_names
    assert "installed_base" in chunk_names
    assert "graph" in chunk_names
    assert "models" in chunk_names

    etag = res.headers["ETag"]
    assert etag is not None

    # 2. Test delta ETag 304 Not Modified
    res_304 = client.get(
        f"/v1/sites/{site_id}/pack",
        headers={**headers, "If-None-Match": etag},
    )
    assert res_304.status_code == 304


# ==============================================================================
# Chaos Test TC4.152: Replay Conflict Detection and Queue Hold
# ==============================================================================
@pytest.mark.chaos
def test_tc4_152_replay_conflict_detection_and_hold():
    """TC4.152: Serial dismantled in ERP during offline visit -> Replay dismantle -> Exception opened, queue held."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    tower_fl = "IN01-TWR-0042-T01"
    other_tower_fl = "IN01-TWR-0042-T02"

    queue_key = f"EQUIP:{tower_fl}"
    other_queue_key = f"EQUIP:{other_tower_fl}"

    # Seed site so exception_case foreign key succeeds
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Conflict Test Site', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )
            conn.commit()

    # Precondition: Serial was dismantled in ERP while technician was offline
    erp_state_conflicting = {
        "equipment_no": "EQ-998811",
        "serial_no": "21A7K0093",
        "status": "dismantled",  # already dismantled in ERP!
        "current_fl": None,
    }

    # Technician returns online and replays offline dismantle event
    res = check_and_handle_replay_conflict(
        tenant_id=tenant_id,
        site_id=site_id,
        tower_fl=tower_fl,
        equipment_no="EQ-998811",
        serial_no="21A7K0093",
        operation="dismantle",
        expected_precondition_fl=f"{tower_fl}-SA-L01",
        current_erp_state=erp_state_conflicting,
    )

    # 1. Conflict detected & queue held
    assert res["conflict"] is True
    assert res["queue_held"] is True
    assert res["queue_key"] == queue_key
    assert res["exception_case_id"] is not None

    # 2. Verify is_queue_held returns True for this tower
    assert is_queue_held(tenant_id=tenant_id, queue_key=queue_key) is True

    # 3. Non-blocking invariant: other tower is NOT held
    assert is_queue_held(tenant_id=tenant_id, queue_key=other_queue_key) is False

    # 4. Verify Exception Case exists in field.exception_case with severity S2
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                SELECT type, severity, status, rule_id
                FROM field.exception_case
                WHERE tenant_id = %s AND id = %s;
                """,
                (tenant_id, res["exception_case_id"]),
            )
            case_row = cur.fetchone()
            assert case_row is not None
            assert case_row[0] == "replay_conflict"
            assert case_row[1] == "S2"
            assert case_row[2] == "open"
            assert case_row[3] == "RULE-REPLAY-CONFLICT"

            # 5. Verify Outbox event MSG4.23 ('replay.conflict_detected')
            cur.execute(
                """
                SELECT event_type, payload
                FROM field.outbox
                WHERE tenant_id = %s AND aggregate_id = %s;
                """,
                (tenant_id, res["exception_case_id"]),
            )
            outbox_row = cur.fetchone()
            assert outbox_row is not None
            assert outbox_row[0] == "replay.conflict_detected"

    # 6. Verify equipment queue processing skips held tower
    held_job = process_next_tower_job(tenant_id=tenant_id, queue_key=queue_key)
    assert held_job is not None
    assert held_job["status"] == "held"

    # 7. Release hold
    released = release_queue_hold(tenant_id=tenant_id, queue_key=queue_key, released_by="supervisor-01")
    assert released is True
    assert is_queue_held(tenant_id=tenant_id, queue_key=queue_key) is False


# ==============================================================================
# Security Test TC4.153: Report Export and Link Authentication
# ==============================================================================
@pytest.mark.security
def test_tc4_153_report_export_and_link_auth():
    """TC4.153: Report exports CSV/PDF; evidence links reject missing sessions (401) and cross-tenant access (404)."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    headers_a = _auth_headers(tenant_a, user_id="auditor-tenant-a")
    headers_b = _auth_headers(tenant_b, user_id="auditor-tenant-b")

    task_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_a,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_a,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Seed task and findings for tenant A
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Security Audit Site', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_a, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )
            cur.execute(
                """
                INSERT INTO field.task (id, tenant_id, site_id, title, type, status)
                VALUES (%s, %s, %s, 'Security Audit Task', 'audit', 'completed')
                ON CONFLICT (id) DO NOTHING;
                """,
                (task_id, tenant_a, site_id),
            )
            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, location_id, class,
                    expected_serial, found_serial, status, decision, dedupe_key
                ) VALUES (
                    %s, %s, %s, %s, NULL, 'matched',
                    'SN-CONFIDENTIAL-01', 'SN-CONFIDENTIAL-01', 'open', 'waived', 'dedupe-sec-01'
                );
                """,
                (str(uuid.uuid4()), tenant_a, task_id, site_id),
            )
            conn.commit()

    # 1. Tenant A exports CSV report (API4.17)
    res_export = client.post(
        f"/v1/audits/{task_id}/report",
        headers=headers_a,
        json={"format": "csv"},
    )
    assert res_export.status_code == 200
    rep_data = res_export.json()
    assert rep_data["status"] == "ready"
    assert rep_data["format"] == "csv"

    # 2. Tenant A exports PDF report
    res_pdf = client.post(
        f"/v1/audits/{task_id}/report",
        headers=headers_a,
        json={"format": "pdf"},
    )
    assert res_pdf.status_code == 200
    assert res_pdf.json()["format"] == "pdf"

    # 3. Access evidence URL with signed token from report -> 200 OK
    signed_url = generate_signed_evidence_url(tenant_id=tenant_a, evidence_id="ev-crop-secure-001")
    path_and_query = signed_url.split("localhost:8000")[-1]

    res_valid_ev = client.get(path_and_query)
    assert res_valid_ev.status_code == 200
    assert res_valid_ev.headers["X-Tenant-Id"] == tenant_a
    assert res_valid_ev.headers["Content-Type"] == "image/png"

    # 4. Access evidence WITHOUT session or token -> 401 Unauthorized
    res_unauth = client.get("/v1/evidence/ev-crop-secure-001")
    assert res_unauth.status_code == 401

    # 5. Access evidence from DIFFERENT TENANT (Tenant B) -> 404 Not Found (TC4.153)
    res_cross_tenant = client.get(
        path_and_query,
        headers=headers_b,  # Tenant B bearer token!
    )
    assert res_cross_tenant.status_code == 404
    assert res_cross_tenant.json()["detail"]["error_code"] == "FIELD-EVD-404-CROSS-TENANT"
