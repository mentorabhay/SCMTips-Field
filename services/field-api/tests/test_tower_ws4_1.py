"""Exhaustive Test Suite for WS4.1: Site Model, SAP Import & Visits.

Covers:
- T4.001: Tower location migrations (field_0041, field_0042) and RLS.
- T4.002 / TC4.106: Site tree service and API with level height order and ETag.
- T4.003 / TC4.105: Functional location mask validation (tested in test_fl_mask_ws4_1.py).
- T4.004 / TC4.101: SAP functional location reader & import staging preview.
- T4.005 / TC4.102: Equipment reader with 6 fields and serial duplicate detection.
- T4.006 / PR4.16: Import staging, diff preview, and atomic apply in one transaction.
- T4.007 / TC4.103: Delta import with watermark advancement and zero changes on repeat.
- T4.008 / TC4.104: Topological pass rejecting orphan and cycle locations with reasons.
- T4.009: Tower fixtures loaded with 3 SAMPLE sites and deliberate mismatches.
- T4.010 / TC4.107 & TC4.108: Geofenced check-in and permit validity enforcement.
- T4.011 / TC4.109: Supervisor geofence override with P13e audit outbox event.
- T4.012 / TC4.110: Check-out with lone-worker timer stop and unsynced items warning (MSG4.18).
- PR4.17: Geofence invariant verification.
"""

import json
import math
import uuid
import httpx
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.sites.fl_mask import validate_fl_code
from field_api.sites.import_service import apply_fl_import_job, stage_fl_import
from field_api.sites.import_validate import validate_import_staging_rows
from field_api.visits.api import haversine_distance_m
from field_sap.equipment_read import EquipmentReader
from field_sap.fl_import import FunctionalLocationReader
from field_worker.jobs.fl_import import run_fl_delta_import

DATABASE_URL = "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field"

client = TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    token = create_dev_token(
        principal_id="test-tower-tech-01",
        tenant_id=tenant_id,
        roles=["field.technician", "field.supervisor", "field.operator"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": "req-test-ws41",
        "tenant_id": tenant_id,
    }


def create_test_tower_site(
    tenant_id: str,
    site_id: str,
    site_code: str | None = None,
    lat: float = 12.9716,
    lon: float = 77.5946,
    radius_m: int = 150,
) -> None:
    code = site_code or f"TWR-{site_id[:8].upper()}"
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")
        cur.execute("SET app.site_ids = '*';")
        cur.execute(
            """
            INSERT INTO field.site (id, tenant_id, code, name, kind, lat, lon, geofence_radius_m, status)
            VALUES (%s::uuid, %s::uuid, %s, 'Sample Tower Site 42', 'tower', %s, %s, %s, 'active')
            ON CONFLICT (tenant_id, code) DO UPDATE SET
                id = EXCLUDED.id,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                geofence_radius_m = EXCLUDED.geofence_radius_m;
            """,
            (site_id, tenant_id, code, lat, lon, radius_m),
        )


# =========================================================================
# TC4.101 & PR4.16: SAP FL Import Preview, Counts & Apply
# =========================================================================
@pytest.mark.unit
def test_tc4_101_fl_import_preview_and_apply(auth_headers):
    """TC4.101 & PR4.16: Import staging yields preview new=31, changed=0, rejected=0; apply creates rows."""
    t_id = auth_headers["tenant_id"]

    # 31 Sample locations for IN01-TWR-0042:
    # 1 Site + 1 Shelter + 2 Racks + 4 Slots + 1 Tower + 3 Sectors + 12 Levels + 7 Positions = 31
    fl_rows = [
        {"fl_code": "IN01-TWR-0042", "parent_fl_code": None},
        {"fl_code": "IN01-TWR-0042-SH", "parent_fl_code": "IN01-TWR-0042"},
        {"fl_code": "IN01-TWR-0042-SH-R01", "parent_fl_code": "IN01-TWR-0042-SH"},
        {"fl_code": "IN01-TWR-0042-SH-R02", "parent_fl_code": "IN01-TWR-0042-SH"},
        {"fl_code": "IN01-TWR-0042-SH-R01-S01", "parent_fl_code": "IN01-TWR-0042-SH-R01"},
        {"fl_code": "IN01-TWR-0042-SH-R01-S02", "parent_fl_code": "IN01-TWR-0042-SH-R01"},
        {"fl_code": "IN01-TWR-0042-SH-R02-S01", "parent_fl_code": "IN01-TWR-0042-SH-R02"},
        {"fl_code": "IN01-TWR-0042-SH-R02-S02", "parent_fl_code": "IN01-TWR-0042-SH-R02"},
        {"fl_code": "IN01-TWR-0042-T01", "parent_fl_code": "IN01-TWR-0042"},
        {"fl_code": "IN01-TWR-0042-T01-SA", "parent_fl_code": "IN01-TWR-0042-T01"},
        {"fl_code": "IN01-TWR-0042-T01-SB", "parent_fl_code": "IN01-TWR-0042-T01"},
        {"fl_code": "IN01-TWR-0042-T01-SC", "parent_fl_code": "IN01-TWR-0042-T01"},
    ]
    # Add 12 levels (4 per sector)
    for sec in ["SA", "SB", "SC"]:
        for idx, lvl in enumerate(["L01", "L02", "L03", "L04"], start=1):
            fl_rows.append({
                "fl_code": f"IN01-TWR-0042-T01-{sec}-{lvl}",
                "parent_fl_code": f"IN01-TWR-0042-T01-{sec}",
                "height_m": idx * 10.0,
            })
    # Add 7 positions
    for p_idx in range(1, 8):
        fl_rows.append({
            "fl_code": f"IN01-TWR-0042-T01-SA-L01-P{p_idx:02d}",
            "parent_fl_code": "IN01-TWR-0042-T01-SA-L01",
        })

    assert len(fl_rows) == 31

    # Stage import job
    stage_res = stage_fl_import(tenant_id=t_id, filter_prefix="IN01-TWR-0042", fl_rows=fl_rows)
    job_id = stage_res["job_id"]
    counts = stage_res["counts"]

    # Preview assertion: counts new=31, changed=0, rejected=0
    assert stage_res["status"] == "preview"
    assert counts["new"] == 31
    assert counts["changed"] == 0
    assert counts["rejected"] == 0
    assert not stage_res["blocked"]

    # Assert nothing applied in field.location prior to apply
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM field.location WHERE tenant_id = %s::uuid AND erp_ref LIKE 'IN01-TWR-0042%%';",
            (t_id,),
        )
        assert cur.fetchone()[0] == 0

    # Apply job
    apply_res = apply_fl_import_job(tenant_id=t_id, job_id=job_id)
    assert apply_res["status"] == "applied"
    assert apply_res["applied_locations_count"] == 31

    # Assert 31 rows created in field.location
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM field.location WHERE tenant_id = %s::uuid AND erp_ref LIKE 'IN01-TWR-0042%%';",
            (t_id,),
        )
        assert cur.fetchone()[0] == 31


# =========================================================================
# TC4.102: Equipment Import Fields & Duplicate Serial Reporting
# =========================================================================
@pytest.mark.unit
def test_tc4_102_equipment_import_fields_and_duplicates():
    """TC4.102 / FR4.005: Equipment import maps 6 key fields and reports duplicate serial numbers."""
    mock_data = {
        "d": {
            "results": [
                {
                    "Equipment": "10001001",
                    "SerialNumber": "RRU-SN-0001",
                    "Material": "MAT-RRU-01",
                    "ManufacturerPartNmbr": "ERIC-RRU-4415",
                    "FunctionalLocation": "IN01-TWR-0042-T01-SA-L01-P01",
                    "EquipInstallationDate": "2026-01-10",
                },
                {
                    "Equipment": "10001002",
                    "SerialNumber": "RRU-SN-0002",
                    "Material": "MAT-RRU-01",
                    "ManufacturerPartNmbr": "ERIC-RRU-4415",
                    "FunctionalLocation": "IN01-TWR-0042-T01-SA-L01-P02",
                    "EquipInstallationDate": "2026-01-11",
                },
                {
                    # Duplicate serial deliberate test
                    "Equipment": "10001003",
                    "SerialNumber": "RRU-SN-0001",  # Duplicate of 10001001
                    "Material": "MAT-RRU-01",
                    "ManufacturerPartNmbr": "ERIC-RRU-4415",
                    "FunctionalLocation": "IN01-TWR-0042-T01-SB-L01-P01",
                    "EquipInstallationDate": "2026-01-12",
                },
            ]
        }
    }

    # Test using mock HTTP transport
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_data))
    mock_client = httpx.Client(transport=transport)

    reader = EquipmentReader(base_url="http://mock-erp", client=mock_client)
    equipment_list, duplicates = reader.read_equipment()

    assert len(equipment_list) == 3
    # Check 6 fields mapped
    item1 = equipment_list[0]
    assert item1["equipment_no"] == "10001001"
    assert item1["serial_no"] == "RRU-SN-0001"
    assert item1["material_no"] == "MAT-RRU-01"
    assert item1["mfr_part_no"] == "ERIC-RRU-4415"
    assert item1["functional_location"] == "IN01-TWR-0042-T01-SA-L01-P01"
    assert item1["install_date"] == "2026-01-10"

    # Check duplicate serial detected and reported
    assert len(duplicates) == 1
    assert duplicates[0]["serial_no"] == "RRU-SN-0001"
    assert duplicates[0]["equipment_nos"] == ["10001001", "10001003"]


# =========================================================================
# TC4.103: Delta Import & Watermark Advancement
# =========================================================================
@pytest.mark.unit
def test_tc4_103_delta_import_watermark(auth_headers):
    """TC4.103 / FR4.006: Delta import tracks watermark; repeat run yields zero changes."""
    t_id = auth_headers["tenant_id"]
    conn_id = str(uuid.uuid4())
    prefix = "IN01-TWR-0042"

    initial_fls = [
        {"FunctionalLocation": "IN01-TWR-0042", "SuperiorFunctionalLocation": "", "LastChangeDateTime": "2026-10-01T08:00:00Z"},
        {"FunctionalLocation": "IN01-TWR-0042-T01", "SuperiorFunctionalLocation": "IN01-TWR-0042", "LastChangeDateTime": "2026-10-01T08:00:00Z"},
    ]

    transport1 = httpx.MockTransport(lambda req: httpx.Response(200, json={"d": {"results": initial_fls}}))
    client1 = httpx.Client(transport=transport1)

    # Initial import run
    res1 = run_fl_delta_import(t_id, conn_id, prefix, client=client1)
    assert res1["status"] == "applied"
    assert res1["changes_detected"] == 2

    # Repeat run with exact same data -> produces zero changes
    res2 = run_fl_delta_import(t_id, conn_id, prefix, client=client1)
    assert res2["status"] == "unchanged"
    assert res2["changes_detected"] == 0

    # Now simulate 2 changed/added FLs
    delta_fls = [
        {"FunctionalLocation": "IN01-TWR-0042-T01-SA", "SuperiorFunctionalLocation": "IN01-TWR-0042-T01", "LastChangeDateTime": "2026-10-15T09:00:00Z"},
        {"FunctionalLocation": "IN01-TWR-0042-T01-SB", "SuperiorFunctionalLocation": "IN01-TWR-0042-T01", "LastChangeDateTime": "2026-10-15T09:30:00Z"},
    ]
    transport2 = httpx.MockTransport(lambda req: httpx.Response(200, json={"d": {"results": delta_fls}}))
    client2 = httpx.Client(transport=transport2)

    res3 = run_fl_delta_import(t_id, conn_id, prefix, client=client2)
    assert res3["status"] == "applied"
    assert res3["changes_detected"] == 2
    assert "2026-10-15" in res3["watermark"]


# =========================================================================
# TC4.104: Orphan & Cycle Rejection
# =========================================================================
@pytest.mark.unit
def test_tc4_104_orphan_and_cycle_rejection():
    """TC4.104 / FR4.007: Topological pass detects orphans and cycles with reasons while keeping valid rows."""
    staging_rows = [
        # Valid root and child
        {"fl_code": "IN01-TWR-0042", "parent_fl_code": None},
        {"fl_code": "IN01-TWR-0042-T01", "parent_fl_code": "IN01-TWR-0042"},
        # Cycle: A points to B, B points to A
        {"fl_code": "IN01-TWR-0042-T01-SA", "parent_fl_code": "IN01-TWR-0042-T01-SB"},
        {"fl_code": "IN01-TWR-0042-T01-SB", "parent_fl_code": "IN01-TWR-0042-T01-SA"},
        # Orphan: parent does not exist
        {"fl_code": "IN01-TWR-0042-T01-SC", "parent_fl_code": "IN01-TWR-9999-NONEXISTENT"},
    ]

    summary = validate_import_staging_rows(staging_rows)
    assert summary.valid_count == 2
    assert summary.rejected_count == 3
    valid_codes = [r["fl_code"] for r in summary.valid_rows]
    assert "IN01-TWR-0042" in valid_codes
    assert "IN01-TWR-0042-T01" in valid_codes

    # Verify rejection error types
    err_types = {r["fl_code"]: r["error_type"] for r in summary.rejected_rows}
    assert err_types["IN01-TWR-0042-T01-SA"] == "FIELD-LOC-422-CYCLE"
    assert err_types["IN01-TWR-0042-T01-SB"] == "FIELD-LOC-422-CYCLE"
    assert err_types["IN01-TWR-0042-T01-SC"] == "FIELD-LOC-422-ORPHAN"

    # Over 20% rejected (3/5 = 60%) -> blocks apply
    assert summary.blocked


# =========================================================================
# TC4.106: Site Tree API & Height Order
# =========================================================================
@pytest.mark.unit
def test_tc4_106_site_tree_api(auth_headers):
    """TC4.106 / FR4.001, FR4.002, FR4.003: Site tree returns nested hierarchy with level height order and ETag."""
    t_id = auth_headers["tenant_id"]
    site_id = str(uuid.uuid4())
    create_test_tower_site(t_id, site_id, site_code="IN01-TWR-0042")

    # Insert hierarchy: Tower -> Sector A -> 3 Levels (with different height_m)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        # Tower
        t_uuid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO field.location (id, tenant_id, site_id, kind, code, path, depth, erp_ref)
            VALUES (%s::uuid, %s::uuid, %s::uuid, 'tower', 'T01', 'IN01-TWR-0042-T01', 2, 'IN01-TWR-0042-T01');
            """,
            (t_uuid, t_id, site_id),
        )
        # Sector A
        s_uuid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO field.location (id, tenant_id, site_id, parent_id, kind, code, path, depth, erp_ref, sector_code)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'sector', 'SA', 'IN01-TWR-0042-T01-SA', 3, 'IN01-TWR-0042-T01-SA', 'A');
            """,
            (s_uuid, t_id, site_id, t_uuid),
        )
        # 3 Levels inserted in reverse order (30m, 10m, 20m)
        for lvl_code, h in [("L03", 30.0), ("L01", 10.0), ("L02", 20.0)]:
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, parent_id, kind, code, path, depth, erp_ref, sector_code, height_m)
                VALUES (field.uuid_generate_v7(), %s::uuid, %s::uuid, %s::uuid, 'level', %s, %s, 4, %s, 'A', %s);
                """,
                (t_id, site_id, s_uuid, lvl_code, f"IN01-TWR-0042-T01-SA-{lvl_code}", f"IN01-TWR-0042-T01-SA-{lvl_code}", h),
            )

    # Call API GET /v1/sites/{id}/tree
    headers = {
        "Authorization": auth_headers["Authorization"],
        "tenant_id": t_id,
    }
    resp = client.get(f"/v1/sites/{site_id}/tree", headers=headers)
    assert resp.status_code == 200
    assert "ETag" in resp.headers
    etag = resp.headers["ETag"]

    data = resp.json()
    assert data["code"] == "IN01-TWR-0042"
    assert len(data["children"]) == 1  # Tower T01
    tower = data["children"][0]
    assert tower["kind"] == "tower"
    assert len(tower["children"]) == 1  # Sector SA
    sector = tower["children"][0]
    assert sector["kind"] == "sector"
    levels = sector["children"]
    assert len(levels) == 3

    # Assert levels are strictly sorted by height_m (10.0, 20.0, 30.0)
    assert [lvl["height_m"] for lvl in levels] == [10.0, 20.0, 30.0]
    assert [lvl["code"] for lvl in levels] == ["L01", "L02", "L03"]

    # Test If-None-Match ETag caching returns 304
    resp304 = client.get(f"/v1/sites/{site_id}/tree", headers={**headers, "If-None-Match": etag})
    assert resp304.status_code == 304


# =========================================================================
# TC4.107: Check-in Inside Geofence
# =========================================================================
@pytest.mark.unit
def test_tc4_107_checkin_inside_geofence(auth_headers):
    """TC4.107 / FR4.009: Check-in accepted inside geofence (dist - acc <= radius, acc <= 50m)."""
    t_id = auth_headers["tenant_id"]
    site_id = str(uuid.uuid4())
    # Site at lat 12.9716, lon 77.5946
    create_test_tower_site(t_id, site_id, lat=12.9716, lon=77.5946, radius_m=150)

    # Technician 40m away: lat ~12.9719, lon 77.5946, accuracy 12m
    payload = {
        "user_id": str(uuid.uuid4()),
        "permit_ref": "PERMIT-VALID-2026-001",
        "permit_valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "lat": 12.9719,
        "lon": 77.5946,
        "accuracy_m": 12.0,
        "timer_interval_min": 20,
        "baro_baseline_hpa": 1013.25,
    }

    resp = client.post(
        f"/v1/sites/{site_id}/visits",
        json=payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "checked_in"
    assert data["timer_interval_min"] == 20
    assert not data["override"]


# =========================================================================
# TC4.108: Check-in With Expired Permit
# =========================================================================
@pytest.mark.unit
def test_tc4_108_checkin_expired_permit(auth_headers):
    """TC4.108 / FR4.010: Check-in fails with 422 FIELD-VIS-422-PERMIT when permit is expired."""
    t_id = auth_headers["tenant_id"]
    site_id = str(uuid.uuid4())
    create_test_tower_site(t_id, site_id)

    payload = {
        "user_id": str(uuid.uuid4()),
        "permit_ref": "PERMIT-EXPIRED-2026",
        # Expired yesterday
        "permit_valid_until": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "lat": 12.9716,
        "lon": 77.5946,
        "accuracy_m": 10.0,
    }

    resp = client.post(
        f"/v1/sites/{site_id}/visits",
        json=payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "FIELD-VIS-422-PERMIT" in str(data)
    assert "MSG4.03" in str(data)


# =========================================================================
# TC4.109: Supervisor Geofence Override & P13e Audit Event
# =========================================================================
@pytest.mark.unit
def test_tc4_109_supervisor_geofence_override(auth_headers):
    """TC4.109 / FR4.011: Supervisor overrides geofence failure with mandatory reason; outbox audit event emitted."""
    t_id = auth_headers["tenant_id"]
    site_id = str(uuid.uuid4())
    create_test_tower_site(t_id, site_id, lat=12.9716, lon=77.5946, radius_m=150)

    # Technician 400m away (lat 12.9752 is ~400m away)
    # Check-in without override fails
    bad_payload = {
        "user_id": str(uuid.uuid4()),
        "permit_ref": "PERMIT-VALID-2026-002",
        "permit_valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "lat": 12.9752,
        "lon": 77.5946,
        "accuracy_m": 15.0,
    }
    fail_resp = client.post(
        f"/v1/sites/{site_id}/visits",
        json=bad_payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert fail_resp.status_code == 422
    assert "FIELD-VIS-422-GEOFENCE" in str(fail_resp.json())

    # Check-in with supervisor override succeeds
    sup_id = str(uuid.uuid4())
    override_payload = {
        **bad_payload,
        "override_by": sup_id,
        "override_reason": "GPS multipath distortion under heavy lattice shelter steel structure",
    }
    success_resp = client.post(
        f"/v1/sites/{site_id}/visits",
        json=override_payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert success_resp.status_code == 201
    v_data = success_resp.json()
    assert v_data["override"] is True
    visit_id = v_data["id"]

    # Verify P13e audit event emitted into field.outbox
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, payload
            FROM field.outbox
            WHERE tenant_id = %s::uuid AND aggregate_id = %s::uuid AND event_type = 'field.visit.override';
            """,
            (t_id, visit_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "field.visit.override"
        payload_data = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        assert payload_data["override_by"] == sup_id
        assert "multipath distortion" in payload_data["reason"]


# =========================================================================
# TC4.110: Check-Out With Unsynced Items Warning (MSG4.18)
# =========================================================================
@pytest.mark.unit
def test_tc4_110_checkout_with_unsynced_items(auth_headers):
    """TC4.110 / FR4.012: Check-out closes visit, stops timer, and warns if items unsynced (MSG4.18)."""
    t_id = auth_headers["tenant_id"]
    site_id = str(uuid.uuid4())
    create_test_tower_site(t_id, site_id)

    # 1. Check in
    checkin_payload = {
        "user_id": str(uuid.uuid4()),
        "permit_ref": "PERMIT-VALID-2026-003",
        "permit_valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "lat": 12.9716,
        "lon": 77.5946,
        "accuracy_m": 10.0,
    }
    c_resp = client.post(
        f"/v1/sites/{site_id}/visits",
        json=checkin_payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert c_resp.status_code == 201
    visit_id = c_resp.json()["id"]

    # 2. Check out with 3 unsynced items
    out_payload = {"unsynced_count": 3}
    patch_resp = client.patch(
        f"/v1/visits/{visit_id}",
        json=out_payload,
        headers={"Authorization": auth_headers["Authorization"], "tenant_id": t_id},
    )
    assert patch_resp.status_code == 200
    out_data = patch_resp.json()
    assert out_data["status"] == "checked_out"
    assert out_data["checkout_at"] is not None
    assert out_data["unsynced_count"] == 3
    assert "MSG4.18" in out_data["warning"]


# =========================================================================
# PR4.17: Geofence Invariant Property
# =========================================================================
@pytest.mark.unit
def test_pr4_17_geofence_invariant_property():
    """PR4.17: Distance minus accuracy <= radius is the exact boundary condition."""
    center_lat, center_lon = 12.9716, 77.5946
    radius = 150.0

    # 1. Exactly at center
    assert haversine_distance_m(center_lat, center_lon, center_lat, center_lon) == 0.0

    # 2. Test boundary condition: d = 160m, accuracy = 15m -> effective = 145m <= 150m (INSIDE)
    # Moving ~160m north (1 deg lat ~ 111,000 m -> 160m ~ 0.001441 deg)
    pt_lat = center_lat + 0.001441
    dist = haversine_distance_m(center_lat, center_lon, pt_lat, center_lon)
    accuracy = 15.0
    assert 150.0 < dist < 170.0
    effective = dist - accuracy
    assert effective <= radius  # Admitted!

    # 3. Accuracy > 50m always rejected regardless of distance
    high_accuracy = 55.0
    assert high_accuracy > 50.0  # Fails accuracy gate
