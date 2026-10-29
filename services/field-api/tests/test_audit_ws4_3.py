"""Comprehensive Integration, Property, and Contract Tests for WS4.3 (Tasks T4.014-T4.019, T4.026, T4.066-T4.067).

Covers:
- PR4.03: Completeness bounded Hypothesis test (1,000 runs) (FR4.024).
- PR4.11: Mismatch symmetry Hypothesis test (1,000 runs) (FR4.025).
- TC4.122: Sign-off blocked on unresolved lines; 409 with MSG4.21 count; waiver succeeds (FR4.028).
- TC4.123: Update ERP decision with SoD; decider == capturer returns 403; SoD approval flow (FR4.027, FR4.067).
- TC4.124: Exception case deduplication; repeat reconcile keeps single open case (FR4.026).
- TC4.120 & TC4.121: Missing & unknown finding endpoints (FR4.022, FR4.023).
- API4.06, API4.07, API4.16: Reconcile, progress, and mismatch queue contract tests.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.audit.exceptions import open_and_deduplicate_exceptions
from field_api.audit.progress import calculate_completeness
from field_api.audit.reconcile import classify_sets_symmetric
from field_api.audit.signoff import AuditSignoffConflict, sign_off_audit_task
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from hypothesis import given, settings
from hypothesis import strategies as st

client = TestClient(app)


@pytest.fixture
def auth_context() -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    user_tech = "tech-user-alice"
    user_super = "supervisor-user-dan"

    token_tech = create_dev_token(
        principal_id=user_tech,
        tenant_id=tenant_id,
        roles=["field.technician"],
        site_ids=["*"],
    )
    token_super = create_dev_token(
        principal_id=user_super,
        tenant_id=tenant_id,
        roles=["field.supervisor", "field.operator"],
        site_ids=["*"],
    )

    return {
        "tenant_id": tenant_id,
        "tech_id": user_tech,
        "super_id": user_super,
        "headers_tech": {"Authorization": f"Bearer {token_tech}", "X-Request-Id": "req-tech"},
        "headers_super": {"Authorization": f"Bearer {token_super}", "X-Request-Id": "req-super"},
    }


@pytest.fixture
def test_audit_site(auth_context: dict[str, Any]) -> dict[str, Any]:
    """Seeds a site with an audit task and 4 expected task lines."""
    t_id = auth_context["tenant_id"]
    site_id = str(uuid.uuid4())
    site_code = f"IN01-TWR-{uuid.uuid4().hex[:4].upper()}"
    task_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Site
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, lat, lon, geofence_radius_m, status)
                VALUES (%s, %s, %s, %s, 'tower', 19.0760, 72.8777, 100, 'active');
                """,
                (site_id, t_id, site_code, f"Site {site_code}"),
            )

            # Location (Level 1 in Sector A)
            loc_id = str(uuid.uuid4())
            fl_code = f"{site_code}-T01-A-L01"
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, %s, %s, 'level', 'A', 15.0, 'T01.A.L01', 3);
                """,
                (loc_id, t_id, site_id, fl_code, fl_code),
            )

            # Audit Task
            cur.execute(
                """
                INSERT INTO field.task (id, tenant_id, site_id, type, status, priority, title, snapshot_version, version)
                VALUES (%s, %s, %s, 'audit', 'pending', 'medium', %s, 'erp-snapshot#01', 1);
                """,
                (task_id, t_id, site_id, f"Audit - {site_code}"),
            )

            # 4 Expected Task Lines
            serials = ["RRU-EXP-001", "RRU-EXP-002", "TMA-EXP-003", "ANT-EXP-004"]
            line_ids = []
            for idx, s in enumerate(serials, start=1):
                l_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO field.task_line (id, tenant_id, site_id, task_id, line_no, expected_qty, uom, status, expected_serial, location_id, version)
                    VALUES (%s, %s, %s, %s, %s, 1, 'EA', 'pending', %s, %s, 1);
                    """,
                    (l_id, t_id, site_id, task_id, idx, s, loc_id),
                )
                line_ids.append(l_id)

        conn.commit()

    return {
        "site_id": site_id,
        "site_code": site_code,
        "loc_id": loc_id,
        "task_id": task_id,
        "serials": serials,
        "line_ids": line_ids,
    }


# =========================================================================
# PR4.03: Completeness Bounded Property Verification (1,000 runs)
# =========================================================================
@settings(max_examples=1000, deadline=None)
@given(
    exp=st.sets(st.text(min_size=1, max_size=10), max_size=60),
    cap=st.sets(st.text(min_size=1, max_size=10), max_size=80),
)
def test_pr4_03_completeness_bounded_hypothesis(exp, cap):
    """PR4.03 / FR4.024: Completeness = |C intersect E| / |E| lies in [0,1], equals 1 only if E <= C, and 1.0 with empty_scope when empty."""
    val, empty_scope = calculate_completeness(exp, cap)

    # Invariant 1: value strictly bounded in [0.0, 1.0]
    assert 0.0 <= val <= 1.0

    # Invariant 2: empty set yields 1.0 and empty_scope=True
    if len(exp) == 0:
        assert val == 1.0
        assert empty_scope is True
    else:
        assert empty_scope is False
        # Invariant 3: value is 1.0 iff expected is a subset of captured
        if exp.issubset(cap):
            assert val == 1.0
        else:
            assert val < 1.0


# =========================================================================
# PR4.11: Mismatch Symmetry Property Verification (1,000 runs)
# =========================================================================
@settings(max_examples=1000, deadline=None)
@given(
    set_a=st.sets(st.text(min_size=1, max_size=10), max_size=50),
    set_b=st.sets(st.text(min_size=1, max_size=10), max_size=50),
)
def test_pr4_11_mismatch_symmetry_hypothesis(set_a, set_b):
    """PR4.11 / FR4.025: Every ERP-only and tower-only item is reported; swapping sets swaps counts."""
    matched_1, erp_only_1, tower_only_1 = classify_sets_symmetric(set_a, set_b)
    matched_2, erp_only_2, tower_only_2 = classify_sets_symmetric(set_b, set_a)

    # Invariant 1: Matched is symmetric (A & B == B & A)
    assert matched_1 == matched_2

    # Invariant 2: Swapping roles swaps erp_only and tower_only counts and sets
    assert erp_only_1 == tower_only_2
    assert tower_only_1 == erp_only_2
    assert len(erp_only_1) == len(tower_only_2)
    assert len(tower_only_1) == len(erp_only_2)


# =========================================================================
# TC4.122: Audit Sign-off Rule Enforcement
# =========================================================================
def test_tc4_122_signoff_blocked_until_explained_or_waived(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """TC4.122 / FR4.028: Sign-off blocked with 409 and MSG4.21 count; waiver succeeds."""
    t_id = auth_context["tenant_id"]
    task_id = test_audit_site["task_id"]

    # 1. Attempt sign-off when all 4 lines are uncaptured and unexplained -> blocked
    with pytest.raises(AuditSignoffConflict) as exc:
        sign_off_audit_task(
            tenant_id=t_id,
            task_id=task_id,
            signed_by=auth_context["tech_id"],
            supervisor_waiver=False,
        )
    assert exc.value.unresolved_count == 4
    assert "4 expected items are not captured or explained" in str(exc.value)

    # 2. HTTP Endpoint test for 409 Conflict with MSG4.21 count
    resp = client.post(
        f"/v1/tasks/{task_id}/audit/signoff",
        json={"supervisor_waiver": False},
        headers=auth_context["headers_tech"],
    )
    assert resp.status_code == 409
    data = resp.json()["detail"]
    assert data["unresolved_count"] == 4
    assert "4 expected items are not captured or explained" in data["message"]

    # 3. Supervisor waiver with reason succeeds
    resp_waived = client.post(
        f"/v1/tasks/{task_id}/audit/signoff",
        json={
            "supervisor_waiver": True,
            "waiver_reason": "Shelter locked by landlord - approved to close",
        },
        headers=auth_context["headers_super"],
    )
    assert resp_waived.status_code == 200
    res_data = resp_waived.json()
    assert res_data["status"] == "signed_off"
    assert res_data["waived_count"] == 4


# =========================================================================
# TC4.123: Update ERP Decision with Segregation of Duties (SoD)
# =========================================================================
def test_tc4_123_update_erp_decision_with_sod(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """TC4.123 / FR4.027 / FR4.067: Technician cannot decide on own capture (403 SoD); supervisor decision succeeds."""
    t_id = auth_context["tenant_id"]
    task_id = test_audit_site["task_id"]
    site_id = test_audit_site["site_id"]
    capturing_tech = auth_context["tech_id"]
    auth_context["super_id"]

    # Seed an open mismatch finding captured by technician Alice
    finding_id = str(uuid.uuid4())
    capture_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.capture (id, tenant_id, site_id, task_id, code_type, code_value, confidence, verify_status)
                VALUES (%s, %s, %s, %s, 'serial_text', '21A7K0093', 0.96, 'verified');
                """,
                (capture_id, t_id, site_id, task_id),
            )

            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, tower_location_id,
                    location_id, capture_id, class, expected_serial, found_serial,
                    status, dedupe_key
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, 'serial_mismatch', '21A7K0098', '21A7K0093',
                    'open', %s
                );
                """,
                (
                    finding_id,
                    t_id,
                    task_id,
                    site_id,
                    test_audit_site["loc_id"],
                    test_audit_site["loc_id"],
                    capture_id,
                    f"{site_id}:21A7K0093:serial_mismatch",
                ),
            )
        conn.commit()

    # 1. Capturing technician Alice tries to decide -> blocked by SoD (403)
    resp_sod = client.post(
        f"/v1/mismatches/{finding_id}/decision",
        json={
            "decision": "update_erp",
            "note": "Self-approval attempt",
            "capturing_technician_id": capturing_tech,
        },
        headers=auth_context["headers_tech"],
    )
    assert resp_sod.status_code == 403
    assert resp_sod.json()["detail"]["error_code"] == "FIELD-EXC-403-SOD"

    # 2. Supervisor Dan submits update_erp decision -> accepted, creates approval request
    resp_super = client.post(
        f"/v1/mismatches/{finding_id}/decision",
        json={
            "decision": "update_erp",
            "note": "Plate clearly photographed and verified by Spark",
            "capturing_technician_id": capturing_tech,
        },
        headers=auth_context["headers_super"],
    )
    assert resp_super.status_code == 200
    dec_data = resp_super.json()
    assert dec_data["status"] == "awaiting_approval"
    assert dec_data["requires_approval"] is True
    approval_id = dec_data["approval_id"]
    assert approval_id is not None

    # 3. Approve approval request -> resolves finding and writes audit event
    resp_appr = client.post(
        f"/v1/mismatches/approvals/{approval_id}/approve",
        headers=auth_context["headers_super"],
    )
    assert resp_appr.status_code == 200
    assert resp_appr.json()["status"] == "resolved"


# =========================================================================
# TC4.124: Exception Case Deduplication
# =========================================================================
def test_tc4_124_exception_deduplication(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """TC4.124 / FR4.026: Reconciling same serial mismatch twice keeps exactly 1 open exception case."""
    t_id = auth_context["tenant_id"]
    task_id = test_audit_site["task_id"]
    site_id = test_audit_site["site_id"]
    loc_id = test_audit_site["loc_id"]

    # Pre-seed an open audit finding
    finding_id = str(uuid.uuid4())
    dedupe_key = f"{site_id}:RRU-DUP-991:serial_mismatch"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, tower_location_id,
                    location_id, class, expected_serial, found_serial,
                    status, dedupe_key
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, 'serial_mismatch', 'RRU-EXP-001', 'RRU-DUP-991',
                    'open', %s
                );
                """,
                (finding_id, t_id, task_id, site_id, loc_id, loc_id, dedupe_key),
            )
        conn.commit()

    # Pass 1: Open exception cases
    cases_1 = open_and_deduplicate_exceptions(tenant_id=t_id, task_id=task_id)
    assert len(cases_1) == 1

    # Pass 2: Re-run exception processing on the same task
    cases_2 = open_and_deduplicate_exceptions(tenant_id=t_id, task_id=task_id)
    assert len(cases_2) == 0  # No new case opened

    # Verify database contains exactly 1 exception case for this dedupe_key
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute(
                "SELECT COUNT(*) FROM field.exception_case WHERE tenant_id = %s AND dedupe_key = %s;",
                (t_id, dedupe_key),
            )
            count = cur.fetchone()[0]
            assert count == 1


# =========================================================================
# TC4.120 & TC4.121: Missing & Unknown Finding Endpoints
# =========================================================================
def test_tc4_120_and_tc4_121_findings_endpoints(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """TC4.120 & TC4.121 / FR4.022, FR4.023: Mark missing creates erp_only; record unknown creates tower_only."""
    task_id = test_audit_site["task_id"]

    # 1. Mark Missing (FR4.023 / TC4.121)
    resp_missing = client.post(
        f"/v1/tasks/{task_id}/audit/findings/missing",
        json={
            "expected_serial": "RRU-EXP-001",
            "equipment_class": "RRU",
            "reason": "not_found",
            "location_id": test_audit_site["loc_id"],
        },
        headers=auth_context["headers_tech"],
    )
    assert resp_missing.status_code == 200
    assert resp_missing.json()["class"] == "erp_only"
    assert resp_missing.json()["reason"] == "not_found"

    # Invalid reason returns 422
    resp_inv = client.post(
        f"/v1/tasks/{task_id}/audit/findings/missing",
        json={
            "expected_serial": "RRU-EXP-002",
            "equipment_class": "RRU",
            "reason": "unauthorized_reason",
        },
        headers=auth_context["headers_tech"],
    )
    assert resp_inv.status_code == 422

    # 2. Record Unknown (FR4.022 / TC4.120)
    resp_unknown = client.post(
        f"/v1/tasks/{task_id}/audit/findings/unknown",
        json={
            "found_serial": "TMA-SURPRISE-99",
            "equipment_class": "TMA",
            "location_id": test_audit_site["loc_id"],
            "crop_ref": "crops/surprise-tma.jpg",
        },
        headers=auth_context["headers_tech"],
    )
    assert resp_unknown.status_code == 200
    assert resp_unknown.json()["class"] == "tower_only"
    assert resp_unknown.json()["found_serial"] == "TMA-SURPRISE-99"


# =========================================================================
# API Contract Tests: Progress (API4.07), Reconcile (API4.06), Mismatches (API4.16)
# =========================================================================
def test_api4_07_progress_and_api4_06_reconcile(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """API4.06 & API4.07: Reconcile endpoint returns findings summary and progress returns completeness."""
    task_id = test_audit_site["task_id"]

    # Reconcile endpoint (API4.06)
    resp_rec = client.post(
        f"/v1/tasks/{task_id}/audit/reconcile",
        json={},
        headers=auth_context["headers_super"],
    )
    assert resp_rec.status_code == 200
    rec_data = resp_rec.json()
    assert "matched" in rec_data
    assert "erp_only" in rec_data
    assert "completeness" in rec_data

    # Progress endpoint (API4.07)
    client.post(
        f"/v1/tasks/{task_id}/audit/reconcile",
        headers=auth_context["headers_super"],
    )
    resp_get_prog = client.get(
        f"/v1/audits/{task_id}/progress",
        headers=auth_context["headers_super"],
    )
    assert resp_get_prog.status_code == 200
    prog_data = resp_get_prog.json()
    assert "site" in prog_data
    assert "towers" in prog_data
    assert len(prog_data["towers"]) > 0


def test_api4_16_mismatches_queue_query(
    auth_context: dict[str, Any], test_audit_site: dict[str, Any]
):
    """API4.16: Query mismatch queue with filters and pagination."""
    resp = client.get(
        f"/v1/mismatches?site_id={test_audit_site['site_id']}&limit=10",
        headers=auth_context["headers_super"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "count" in data
