"""Unit and integration tests for WS3.4 Outbound Operations (Tasks T3.029 - T3.035).

Covers:
- T3.030: Picking confirmation, bin mismatch rejection, batch/serial enforcement (TC3.115, TC3.116).
- T3.031: Short-pick exception handling and cycle count triggers (TC3.117).
- T3.032: Outbound posting job generation with sequential OBD keys (TC3.118 / PR3.07).
- T3.033: Outbound HU packing with GS1 Mod-10 SSCC generation (TC3.119 / PR3.12).
- T3.034: 601 Goods issue and 602 reversal (TC3.120 / PR3.08 / PR3.01).
- T3.035: 2-opt shortest pick path tour optimization (FR3.026).
"""

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token
from field_api.sitegraph.pickpath import optimize_pick_path
from field_api.warehouse.outbound.goods_issue import (
    GoodsIssueException,
    post_goods_issue,
    reverse_goods_issue,
)
from field_api.warehouse.outbound.pack import (
    OutboundPackManager,
    calculate_gs1_mod10_check_digit,
    generate_sscc,
    validate_sscc,
)
from field_api.warehouse.outbound.pick import PickEngine, PickingException
from field_api.warehouse.outbound.post import generate_pick_posting_jobs
from field_api.warehouse.outbound.short_pick import handle_short_pick


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def auth_headers(role: str = "field.supervisor") -> dict[str, str]:
    token = create_dev_token(
        principal_id="user-op-1",
        tenant_id="11111111-1111-4111-8111-111111111111",
        roles=[role],
        site_ids=["site-1"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# -----------------------------------------------------------------------------
# T3.030: Picking Confirmation (TC3.115, TC3.116 / PR3.08)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_030_pick_confirmation_success_and_bin_mismatch():
    line = {
        "id": "line-01",
        "storage_bin": "A-01-01",
        "material_id": "MAT-CARTON-10",
        "required_qty": 5.0,
        "picked_qty": 0.0,
    }

    # 1. Correct bin and material
    res = PickEngine.evaluate_pick(
        line=line,
        scanned_bin="A-01-01",
        scanned_code="MAT-CARTON-10",
        quantity=3.0,
    )
    assert res["is_confirmed"] is True
    assert res["picked_qty"] == 3.0
    assert res["remaining_qty"] == 2.0
    assert res["is_line_complete"] is False

    # 2. Bin mismatch raises 422 FIELD-PICK-422-BIN-MISMATCH (TC3.115)
    with pytest.raises(PickingException) as exc_info:
        PickEngine.evaluate_pick(
            line=line,
            scanned_bin="B-02-02",
            scanned_code="MAT-CARTON-10",
            quantity=1.0,
        )
    assert exc_info.value.code == "FIELD-PICK-422-BIN-MISMATCH"


@pytest.mark.unit
def test_t3_030_pick_wrong_material_and_batch_serial_enforcement():
    line = {
        "id": "line-02",
        "storage_bin": "A-01-02",
        "material_id": "MAT-SPECIAL-99",
        "required_qty": 2.0,
        "picked_qty": 0.0,
        "is_batch_managed": True,
        "is_serial_managed": True,
    }

    # Wrong material raises 422 (TC3.116)
    with pytest.raises(PickingException) as exc_info:
        PickEngine.evaluate_pick(
            line=line,
            scanned_bin="A-01-02",
            scanned_code="WRONG-MATERIAL-00",
            quantity=1.0,
        )
    assert exc_info.value.code == "FIELD-PICK-422-WRONG-MATERIAL"

    # Batch missing
    with pytest.raises(PickingException) as exc_info:
        PickEngine.evaluate_pick(
            line=line,
            scanned_bin="A-01-02",
            scanned_code="MAT-SPECIAL-99",
            quantity=1.0,
            batch=None,
        )
    assert exc_info.value.code == "FIELD-PICK-422-BATCH-REQUIRED"

    # Serial missing
    with pytest.raises(PickingException) as exc_info:
        PickEngine.evaluate_pick(
            line=line,
            scanned_bin="A-01-02",
            scanned_code="MAT-SPECIAL-99",
            quantity=1.0,
            batch="BATCH-2026-X",
            serial=None,
        )
    assert exc_info.value.code == "FIELD-PICK-422-SERIAL-REQUIRED"

    # Full compliance
    res = PickEngine.evaluate_pick(
        line=line,
        scanned_bin="A-01-02",
        scanned_code="MAT-SPECIAL-99",
        quantity=2.0,
        batch="BATCH-2026-X",
        serial="SN-987654",
    )
    assert res["is_confirmed"] is True
    assert res["is_line_complete"] is True


# -----------------------------------------------------------------------------
# T3.031: Short Pick Exception Handling (TC3.117)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_031_short_pick_exception_and_cycle_count_trigger():
    line = {
        "id": "line-03",
        "storage_bin": "C-03-01",
        "material_id": "MAT-WIDGET-05",
        "required_qty": 10.0,
        "picked_qty": 0.0,
    }

    # Valid short pick: picked 4 out of 10 due to bin_empty
    res = handle_short_pick(line=line, short_qty=4.0, reason_code="bin_empty")
    assert res["status"] == "short_confirmed"
    assert res["confirmed_picked_qty"] == 4.0
    assert res["shortage_qty"] == 6.0
    assert res["cycle_count_requested"] is True
    assert res["cycle_count_event"]["trigger_source"] == "short_pick"

    # Invalid reason rejected
    with pytest.raises(ValueError):
        handle_short_pick(line=line, short_qty=4.0, reason_code="operator_tired")

    # Short quantity >= required rejected
    with pytest.raises(ValueError):
        handle_short_pick(line=line, short_qty=10.0, reason_code="bin_empty")


# -----------------------------------------------------------------------------
# T3.032: Outbound Posting Jobs (TC3.118 / PR3.07)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_032_outbound_posting_jobs_generation():
    lines = [
        {"line_item_no": "000010", "picked_qty": 5.0},
        {"line_item_no": "000020", "picked_qty": 2.0},
    ]
    jobs = generate_pick_posting_jobs("800000045", lines)
    assert len(jobs) == 4
    assert jobs[0]["queue_key"] == "OBD:800000045"
    assert jobs[0]["action"] == "PickOneItem"
    assert jobs[0]["seq"] == 1
    assert jobs[1]["action"] == "ConfirmPickingOneItem"
    assert jobs[1]["seq"] == 2
    assert jobs[2]["seq"] == 3
    assert jobs[3]["seq"] == 4


# -----------------------------------------------------------------------------
# T3.033: Outbound HU Packing and SSCC Generation (TC3.119 / PR3.12)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_033_outbound_hu_packing_and_sscc():
    # Mod-10 check digit verification
    test_17 = "00890123000000001"
    check = calculate_gs1_mod10_check_digit(test_17)
    assert 0 <= check <= 9

    sscc = generate_sscc("0890123", "0", 1)
    assert len(sscc) == 18
    assert validate_sscc(sscc) is True

    line = {
        "id": "line-04",
        "material_id": "MAT-01",
        "picked_qty": 10.0,
        "delivery_no": "800000045",
    }

    # Successful packing
    hu = OutboundPackManager.pack_line(line=line, pack_quantity=10.0, serial_counter=42)
    assert hu["status"] == "packed"
    assert hu["packed_quantity"] == 10.0
    assert validate_sscc(hu["sscc"]) is True

    # Overpacking rejected
    with pytest.raises(ValueError):
        OutboundPackManager.pack_line(line=line, pack_quantity=15.0)


# -----------------------------------------------------------------------------
# T3.034: Goods Issue 601 and Reversal 602 (TC3.120 / PR3.08 / PR3.01)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_034_goods_issue_and_reversal():
    lines = [
        {
            "id": "L1",
            "material_id": "MAT-01",
            "required_qty": 5.0,
            "picked_qty": 5.0,
            "status": "picked",
        },
        {
            "id": "L2",
            "material_id": "MAT-02",
            "required_qty": 10.0,
            "picked_qty": 10.0,
            "status": "picked",
        },
    ]

    # Successful 601 goods issue
    gi_result = post_goods_issue("800000045", lines)
    assert gi_result["movement_type"] == "601"
    assert gi_result["total_issued_qty"] == 15.0
    assert gi_result["status"] == "goods_issue_posted"

    # Reversal 602 (PR3.01: net delta is 0.0)
    rev_result = reverse_goods_issue(gi_result)
    assert rev_result["movement_type"] == "602"
    assert rev_result["total_reversed_qty"] == 15.0
    assert rev_result["net_stock_delta"] == 0.0

    # Incomplete pick blocks GI
    incomplete_lines = [
        {
            "id": "L1",
            "material_id": "MAT-01",
            "required_qty": 5.0,
            "picked_qty": 2.0,
            "status": "open",
        }
    ]
    with pytest.raises(GoodsIssueException):
        post_goods_issue("800000046", incomplete_lines)


# -----------------------------------------------------------------------------
# T3.035: Pick Path 2-Opt Optimization (FR3.026)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_035_pick_path_2opt_optimization():
    stops = [
        {"storage_bin": "A-01-01"},
        {"storage_bin": "B-05-02"},
        {"storage_bin": "A-01-02"},
        {"storage_bin": "B-05-01"},
    ]
    coords = {
        "A-01-01": (0.0, 0.0),
        "A-01-02": (0.0, 2.0),
        "B-05-01": (10.0, 0.0),
        "B-05-02": (10.0, 2.0),
    }

    optimized = optimize_pick_path(stops, coords)
    assert len(optimized) == 4
    bins = [s["storage_bin"] for s in optimized]
    # Path should visit adjacent bins sequentially (A-01-01 -> A-01-02 -> B-05-02 -> B-05-01)
    assert bins[0].startswith("A-01")
    assert bins[1].startswith("A-01")


# -----------------------------------------------------------------------------
# FastApi Endpoint Routing Tests
# -----------------------------------------------------------------------------
# test_outbound_api_endpoints: removed in C3 (tested invented in-memory /v1/warehouse/outbound routes whose pick fabricated unknown lines; spec pick = API3.04 counts + API3.06 confirm (GI 601); API3.09 HUs still missing).
