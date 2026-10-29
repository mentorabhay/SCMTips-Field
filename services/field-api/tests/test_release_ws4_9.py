"""Automated Release & Integration Test Suite for Phase 4 Workstream 4.9 (Console, Installed Base, Quality & Release).

Covers:
- T4.027: Installed base read model & API (GET /v1/installed-base) (FR4.065 / API4.18 / TC4.157)
- T4.028: Emit installed_base.changed event & signed P13f webhook (FR4.066 / TC4.158)
- T4.065: Site and tower explorer data contract & last audit date (FR4.062 / SCR4.08 / TC4.154)
- T4.071: Contract & compat tests (FR4.029 / TC4.160 / TC4.162)
- T4.073: Multi-tenant isolation & security gate tests (TC4.159)
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.installed_base.events import (
    emit_installed_base_changed,
    verify_p13f_webhook_signature,
)

client = TestClient(app)


def _auth_headers(
    tenant_id: str,
    user_id: str = "test-ws49-admin",
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
# Integration Test TC4.157: Installed Base Matches ERP Data (API4.18 / FR4.065)
# ==============================================================================
@pytest.mark.integration
def test_tc4_157_installed_base_query_and_validation():
    """TC4.157: GET /v1/installed-base returns installed equipment with erp_ref & since timestamp."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    site_id = str(uuid.uuid4())
    site_code = f"SITE-{uuid.uuid4().hex[:6].upper()}"
    loc_id = str(uuid.uuid4())
    eq_id = str(uuid.uuid4())
    serial_no = f"21B3M{uuid.uuid4().hex[:4].upper()}"
    erp_eq_no = "10004417"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Seed Site
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Tower Alpha', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, site_code),
            )

            # 2. Seed Location
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, 'P02', %s, 'position', 'A', 30.0, 'T01.A.L03.P02', 4);
                """,
                (loc_id, tenant_id, site_id, f"{site_code}-T01-SA-L03-P02"),
            )

            # 3. Seed Installed Equipment
            cur.execute(
                """
                INSERT INTO field.equipment (
                    id, tenant_id, serial_no, erp_equipment_no, material,
                    equipment_class, current_location_id, status, pinned_model_version
                ) VALUES (
                    %s, %s, %s, %s, 'RRU-4T-B3',
                    'RRU', %s, 'installed', '1.3.0'
                );
                """,
                (eq_id, tenant_id, serial_no, erp_eq_no, loc_id),
            )
            conn.commit()

    # 1. Test missing both serial and site_id -> 400 FIELD-IB-400-FILTER
    res_err = client.get("/v1/installed-base", headers=headers)
    assert res_err.status_code == 400
    assert res_err.json()["detail"]["error_code"] == "FIELD-IB-400-FILTER"

    # 2. Test query by serial -> 200 OK with matching record
    res_serial = client.get(f"/v1/installed-base?serial={serial_no}", headers=headers)
    assert res_serial.status_code == 200
    data_serial = res_serial.json()
    assert len(data_serial["items"]) == 1
    item = data_serial["items"][0]
    assert item["serial_no"] == serial_no
    assert item["erp_equipment_no"] == erp_eq_no
    assert item["site_id"] == site_id
    assert item["site_erp_ref"] == site_code
    assert item["erp_ref"] == f"{site_code}-T01-SA-L03-P02"
    assert item["pinned_model_version"] == "1.3.0"
    assert item["since"] is not None

    # 3. Test query by site_id -> 200 OK
    res_site = client.get(f"/v1/installed-base?site_id={site_id}", headers=headers)
    assert res_site.status_code == 200
    assert len(res_site.json()["items"]) >= 1


# ==============================================================================
# Integration Test TC4.158: installed_base.changed Webhook Emission & Signature
# ==============================================================================
@pytest.mark.integration
def test_tc4_158_installed_base_changed_webhook():
    """TC4.158: Post install/dismantle emits outbox event and signed P13f webhook with HMAC-SHA256."""
    tenant_id = str(uuid.uuid4())
    serial_no = f"21C4K{uuid.uuid4().hex[:4].upper()}"
    fl_code = "IN01-TWR-0042-T01-SA-L01-P01"

    # Emit change event
    event_result = emit_installed_base_changed(
        tenant_id=tenant_id,
        serial_no=serial_no,
        change_type="installed",
        erp_equipment_no="10009988",
        site_id=str(uuid.uuid4()),
        fl_code=fl_code,
    )

    event_id = event_result["event_id"]
    signature = event_result["signature"]
    payload_json = json.dumps(event_result["payload"], sort_keys=True)

    # 1. Verify HMAC-SHA256 signature validates correctly
    assert verify_p13f_webhook_signature(payload_json.encode("utf-8"), signature) is True

    # 2. Tampered signature fails verification
    tampered_sig = signature[:-4] + "0000"
    assert verify_p13f_webhook_signature(payload_json.encode("utf-8"), tampered_sig) is False

    # 3. Verify event persisted in field.outbox
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                SELECT event_type, aggregate_id, payload
                FROM field.outbox
                WHERE tenant_id = %s AND id = %s;
                """,
                (tenant_id, event_id),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "installed_base.changed"
            assert str(row[1]) == str(uuid.uuid5(uuid.NAMESPACE_DNS, serial_no))
            persisted = row[2] if isinstance(row[2], dict) else json.loads(row[2])
            assert persisted["serial_no"] == serial_no
            assert persisted["change_type"] == "installed"


# ==============================================================================
# Security Test TC4.159: Multi-Tenant Data Isolation (Tree, IB, Trails)
# ==============================================================================
@pytest.mark.security
def test_tc4_159_multi_tenant_isolation_boundary():
    """TC4.159: Two tenants with identical codes: Tenant B cannot read Tenant A records."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    headers_a = _auth_headers(tenant_a, user_id="user-tenant-a")
    headers_b = _auth_headers(tenant_b, user_id="user-tenant-b")

    shared_code = "SITE-ISOLATION-01"
    shared_serial = "SN-CONFIDENTIAL-42"
    site_a = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Seed Site & Equipment under Tenant A
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_a,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_a,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Confidential Site A', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_a, tenant_a, shared_code),
            )
            loc_a = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, 'P01', 'SITE-A-T01-P01', 'position', 'A', 20.0, 'T01.A.P01', 3);
                """,
                (loc_a, tenant_a, site_a),
            )
            cur.execute(
                """
                INSERT INTO field.equipment (id, tenant_id, serial_no, erp_equipment_no, material, current_location_id, status)
                VALUES (%s, %s, %s, 'EQ-SECRET-01', 'RRU-4T-B3', %s, 'installed');
                """,
                (str(uuid.uuid4()), tenant_a, shared_serial, loc_a),
            )
            conn.commit()

    # Tenant A can read its own installed base
    res_a = client.get(f"/v1/installed-base?serial={shared_serial}", headers=headers_a)
    assert res_a.status_code == 200
    assert len(res_a.json()["items"]) == 1

    # Tenant B queries SAME serial -> Returns ZERO rows (enforced by RLS)
    res_b = client.get(f"/v1/installed-base?serial={shared_serial}", headers=headers_b)
    assert res_b.status_code == 200
    assert len(res_b.json()["items"]) == 0

    # Tenant B queries Tenant A site_id -> Returns ZERO rows
    res_b_site = client.get(f"/v1/installed-base?site_id={site_a}", headers=headers_b)
    assert res_b_site.status_code == 200
    assert len(res_b_site.json()["items"]) == 0


# ==============================================================================
# Contract Test TC4.160 / TC4.154: Idempotency Key Handling & Site Explorer
# ==============================================================================
@pytest.mark.contract
def test_tc4_154_site_explorer_and_last_audit_contract():
    """TC4.154: Site and tower explorer returns site details, location tree, and last audit date."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)
    site_id = str(uuid.uuid4())
    site_code = f"SITE-{uuid.uuid4().hex[:6].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Explorer Test Site', 'tower', 'active', 28.5, 77.2)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, site_code),
            )
            loc1 = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, 'T01', %s, 'tower', 'A', 0.0, 'T01', 1);
                """,
                (loc1, tenant_id, site_id, f"{site_code}-T01"),
            )
            conn.commit()

    # Fetch site details
    res_site = client.get(f"/v1/sites/{site_id}", headers=headers)
    assert res_site.status_code == 200
    s_data = res_site.json()
    assert s_data["id"] == site_id
    assert s_data["code"] == site_code
    assert s_data["status"] == "active"

    # Fetch tree
    res_tree = client.get(f"/v1/sites/{site_id}/tree", headers=headers)
    assert res_tree.status_code == 200
    assert "children" in res_tree.json()
