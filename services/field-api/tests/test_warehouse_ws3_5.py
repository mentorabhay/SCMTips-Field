"""Unit and integration tests for WS3.5 Physical Inventory & Cycle Counting (Tasks T3.036 - T3.045).

Covers:
- T3.036: PI document creation (TC3.121).
- T3.037: ABC cycle-count rule scheduling and triggers (TC3.122).
- T3.038: Blind count projection redaction (TC3.123 / PR3.03).
- T3.039: Count entry and commitment (TC3.124 / PR3.02).
- T3.040: Recount rule and different operator validation (TC3.125 / PR3.04).
- T3.041: Difference posting approval gate (TC3.126 / PR3.05).
- T3.042: Difference posting 701 gain / 702 loss (TC3.127).
- T3.043: Book inventory freeze snapshot (TC3.128 / PR3.16).
- T3.044: Quantity-conserving audit export (TC3.129 / PR3.18).
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token
from field_api.warehouse.inventory.approvals import (
    ApprovalException,
    evaluate_variance_approval_requirement,
    validate_approval_state_for_posting,
)
from field_api.warehouse.inventory.documents import PiDocumentCreate, PiDocumentManager
from field_api.warehouse.inventory.entry import InventoryCountEntry, record_inventory_count
from field_api.warehouse.inventory.export import generate_inventory_audit_export
from field_api.warehouse.inventory.freeze import FreezeSnapshotManager
from field_api.warehouse.inventory.post_diff import post_physical_inventory_difference
from field_api.warehouse.inventory.projection import (
    FORBIDDEN_OPERATOR_FIELDS,
    project_inventory_response,
    project_operator_count_line,
)
from field_api.warehouse.inventory.recount import (
    RecountException,
    initiate_recount,
    validate_recount_assignment,
)
from field_worker.warehouse.cycle_count import CycleCountScheduler


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def auth_headers(role: str = "field.operator") -> dict[str, str]:
    token = create_dev_token(
        principal_id="user-op-2",
        tenant_id="tenant-test-1",
        roles=[role],
        site_ids=["site-1"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# -----------------------------------------------------------------------------
# T3.036: PI Document Creation (TC3.121)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_036_pi_document_creation():
    req = PiDocumentCreate(
        plant="PL01",
        storage_location="SL01",
        bins=["A-01-01", "A-01-02"],
        materials=["MAT-01", "MAT-02"],
        freeze_book=True,
        posting_blocked=True,
    )
    doc = PiDocumentManager.create_document(req, doc_counter=101)
    assert doc["plant"] == "PL01"
    assert doc["storage_location"] == "SL01"
    assert doc["freeze_book"] is True
    assert doc["posting_blocked"] is True
    assert doc["status"] == "open"
    assert doc["doc_number"] == "1000000101"


# -----------------------------------------------------------------------------
# T3.037: ABC Cycle Count Rules (TC3.122)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_037_cycle_count_rules():
    now = datetime(2026, 10, 30, 12, 0)

    # Class A: 30 days interval
    counted_20d_ago = now - timedelta(days=20)
    counted_35d_ago = now - timedelta(days=35)

    assert CycleCountScheduler.is_item_due(counted_20d_ago, "A", now=now) is False
    assert CycleCountScheduler.is_item_due(counted_35d_ago, "A", now=now) is True

    # Exception trigger makes it immediately due
    assert (
        CycleCountScheduler.is_item_due(counted_20d_ago, "A", now=now, has_exception_trigger=True)
        is True
    )

    # Batching <= 50
    items = [{"id": f"item-{i}"} for i in range(125)]
    batches = CycleCountScheduler.group_due_items_into_batches(items, max_batch_size=50)
    assert len(batches) == 3
    assert len(batches[0]) == 50
    assert len(batches[1]) == 50
    assert len(batches[2]) == 25


# -----------------------------------------------------------------------------
# T3.038: Blind Count Projection (TC3.123 / PR3.03)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_038_blind_count_projection_redaction():
    raw_line = {
        "id": "line-pi-01",
        "pi_doc_id": "doc-01",
        "storage_bin": "B-01-01",
        "material_id": "MAT-SECRET-99",
        "book_qty": 50.0,
        "book_value": 5000.0,
        "difference_qty": 5.0,
        "difference_value": 500.0,
        "status": "open",
    }

    # Operator projection MUST redact all book and difference quantities (PR3.03)
    projected = project_operator_count_line(raw_line)
    for forbidden in FORBIDDEN_OPERATOR_FIELDS:
        assert forbidden not in projected, f"Forbidden field '{forbidden}' leaked to operator!"

    assert "counted_qty" in projected
    assert "storage_bin" in projected
    assert "material_id" in projected

    # Nested projection check
    operator_resp = project_inventory_response(raw_line, has_supervisor_book_permission=False)
    assert "book_qty" not in operator_resp
    assert "difference_qty" not in operator_resp

    # Supervisor retains book visibility
    supervisor_resp = project_inventory_response(raw_line, has_supervisor_book_permission=True)
    assert supervisor_resp["book_qty"] == 50.0


# -----------------------------------------------------------------------------
# T3.039: Count Entry and Confirmation (TC3.124 / PR3.02)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_039_count_entry_and_confirmation():
    # Unconfirmed entry rejected
    with pytest.raises(ValueError):
        record_inventory_count(
            InventoryCountEntry(
                pi_doc_id="doc-01",
                line_id="line-01",
                counted_qty=12.0,
                counter_operator_id="user-alice",
                is_confirmed=False,
            )
        )

    # Confirmed entry succeeds
    res = record_inventory_count(
        InventoryCountEntry(
            pi_doc_id="doc-01",
            line_id="line-01",
            counted_qty=12.0,
            counter_operator_id="user-alice",
            is_confirmed=True,
        )
    )
    assert res["status"] == "counted"
    assert res["committed_qty"] == 12.0
    assert res["is_zero_count"] is False

    # Zero count explicitly flag
    zero_res = record_inventory_count(
        InventoryCountEntry(
            pi_doc_id="doc-01",
            line_id="line-02",
            counted_qty=0.0,
            is_zero_count=True,
            counter_operator_id="user-alice",
            is_confirmed=True,
        )
    )
    assert zero_res["is_zero_count"] is True
    assert zero_res["committed_qty"] == 0.0


# -----------------------------------------------------------------------------
# T3.040: Recount Rule and Different Operator (TC3.125 / PR3.04)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_040_recount_rule_and_different_operator():
    # Recount initiated when discrepancy exists
    line = {"line_id": "L1", "initial_counter_id": "user-alice"}
    rec = initiate_recount(line, initial_count=10.0, book_qty=15.0)
    assert rec["needs_recount"] is True
    assert rec["status"] == "recount"

    # Same operator rejected with 422 FIELD-PI-422-RECOUNT-SAME-OPERATOR (PR3.04)
    with pytest.raises(RecountException) as exc_info:
        validate_recount_assignment("user-alice", "user-alice")
    assert exc_info.value.code == "FIELD-PI-422-RECOUNT-SAME-OPERATOR"

    # Distinct operator passes
    assert validate_recount_assignment("user-alice", "user-bob") is True


# -----------------------------------------------------------------------------
# T3.041: Difference Approval Gate (TC3.126 / PR3.05)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_041_difference_approval_gate():
    # Variance <= 1000 requires no approval
    needs_app, val = evaluate_variance_approval_requirement(diff_qty=5.0, unit_price=100.0)
    assert val == 500.0
    assert needs_app is False
    assert validate_approval_state_for_posting(val, None, "counter-1") is True

    # Variance > 1000 ($2,000) blocks without approval (PR3.05)
    needs_app, val_high = evaluate_variance_approval_requirement(diff_qty=20.0, unit_price=100.0)
    assert val_high == 2000.0
    assert needs_app is True

    with pytest.raises(ApprovalException) as exc_info:
        validate_approval_state_for_posting(val_high, None, "counter-1")
    assert exc_info.value.code == "FIELD-PI-422-APPROVAL-REQUIRED"

    # Self-approval forbidden
    self_app = {"status": "approved", "approved_by": "counter-1"}
    with pytest.raises(ApprovalException) as exc_info:
        validate_approval_state_for_posting(val_high, self_app, "counter-1")
    assert exc_info.value.code == "FIELD-PI-422-SELF-APPROVAL-FORBIDDEN"

    # Valid manager approval succeeds
    manager_app = {"status": "approved", "approved_by": "supervisor-bob"}
    assert validate_approval_state_for_posting(val_high, manager_app, "counter-1") is True


# -----------------------------------------------------------------------------
# T3.042: Differences Posting 701/702 (TC3.127)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_042_difference_posting_701_and_702():
    line = {"id": "L1", "pi_doc_id": "doc-01"}

    # 701 Inventory Gain (counted 15 > book 10)
    res_gain = post_physical_inventory_difference(
        pi_line=line,
        counted_qty=15.0,
        book_qty=10.0,
        unit_price=50.0,
    )
    assert res_gain["movement_type"] == "701"
    assert res_gain["quantity_posted"] == 5.0
    assert res_gain["difference_doc_no"] is not None

    # 702 Inventory Loss (counted 8 < book 10)
    res_loss = post_physical_inventory_difference(
        pi_line=line,
        counted_qty=8.0,
        book_qty=10.0,
        unit_price=50.0,
    )
    assert res_loss["movement_type"] == "702"
    assert res_loss["quantity_posted"] == 2.0


# -----------------------------------------------------------------------------
# T3.043: Book Inventory Freeze Snapshot (TC3.128 / PR3.16)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_043_freeze_book_snapshot_semantics():
    lines = [{"material_id": "MAT-01", "storage_location": "SL01", "book_qty": 100.0}]
    erp_stock = {"MAT-01:SL01": 100.0}

    frozen = FreezeSnapshotManager.capture_freeze_snapshot(lines, erp_stock)
    assert frozen[0]["frozen_book_qty"] == 100.0

    # Invariant PR3.16: Even if live ERP stock changes to 80 after goods movements,
    # frozen document evaluates differences against 100.0
    live_stock_later = 80.0
    effective_book = FreezeSnapshotManager.resolve_effective_book_qty(
        line=frozen[0],
        is_freeze_enabled=True,
        current_live_stock=live_stock_later,
    )
    assert effective_book == 100.0


# -----------------------------------------------------------------------------
# T3.044: Audit Export Quantity Conservation (TC3.129 / PR3.18)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_044_audit_export_conservation():
    lines = [
        {
            "id": "L1",
            "material_id": "MAT-01",
            "storage_bin": "A-01",
            "book_qty": 10.0,
            "counted_qty": 12.0,
        },
        {
            "id": "L2",
            "material_id": "MAT-02",
            "storage_bin": "A-02",
            "book_qty": 20.0,
            "counted_qty": 15.0,
        },
        {
            "id": "L3",
            "material_id": "MAT-03",
            "storage_bin": "A-03",
            "book_qty": 5.0,
            "counted_qty": 5.0,
        },
    ]

    export = generate_inventory_audit_export("1000000001", lines)
    assert export["is_conserved"] is True
    totals = export["totals"]
    assert totals["total_counted"] == 32.0
    assert totals["total_book"] == 35.0
    assert totals["total_difference"] == -3.0
    assert totals["total_counted"] - totals["total_book"] == totals["total_difference"]
    assert "MAT-01" in export["csv_content"]


# -----------------------------------------------------------------------------
# FastApi Endpoint Routing Tests
# -----------------------------------------------------------------------------
# test_inventory_api_endpoints: removed in C3 (tested the invented in-memory /v1/warehouse/inventory routes; spec API3.10-3.12 covered by tests/integration/test_pi_flow.py).
