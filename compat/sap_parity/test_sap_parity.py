"""SAP Parity Contract Tests against erp-sim and VCR Fixtures (Task T3.008 / FR3.043 / PR3.15).

Covers:
- T3.001: Inbound GR 101 execution and status update to 'C'
- T3.003: Outbound Pick, GI 601, Reversal 602, and Lock 423
- T3.004: Physical inventory create, count PATCH, and PostDifferences 701/702
- T3.005: Material document cancel creates 102, already reversed returns 409
- T3.006: Declarative YAML mapping verification
- T3.007: SAP adapter warehouse calls and golden payloads
- T3.008: VCR cassette fixture execution or skip with UNVERIFIED
- T3.009: X-Sim-Fault-Profile header injection and production rejection
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from erp_sim.app import app
from fastapi.testclient import TestClient
from sap_adapter.warehouse import (
    SapWarehouseAdapter,
    classify_sap_error,
)

ROOT = Path(__file__).resolve().parent.parent.parent
MAPPINGS_DIR = ROOT / "connectors" / "sap" / "mappings"
CASSETTES_DIR = ROOT / "compat" / "sap_parity" / "cassettes"

client = TestClient(app)
adapter = SapWarehouseAdapter(http_client=client)


@pytest.fixture(autouse=True)
def reset_inbound_sample() -> None:
    from erp_sim.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE erpsim.inbound_delivery SET status = 'open' WHERE delivery_document = '180000123';")
        conn.commit()
    yield


@pytest.mark.contract
def test_t3_001_inbound_goods_receipt_parity():
    """T3.001 / FR3.010: Inbound GR on SAMPLE 180000123 creates 4900000000+ and marks status 'C'."""
    res = client.post(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt",
        params={"DeliveryDocument": "180000123"},
        headers={"sap-client": "100", "x-csrf-token": "fetch"},
    )
    assert res.status_code == 200, res.text
    data = res.json()["d"]
    assert int(data["MaterialDocument"]) >= 4900000000
    assert data["OverallGoodsMovementStatus"] == "C"

    # Verify read reflection
    get_res = client.get(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader('180000123')",
        params={"$expand": "to_DeliveryDocumentItem"},
        headers={"sap-client": "100"},
    )
    assert get_res.status_code == 200
    hdr = get_res.json()["d"]
    assert hdr["OverallGoodsMovementStatus"] == "C"
    assert len(hdr["to_DeliveryDocumentItem"]["results"]) >= 1


@pytest.mark.contract
def test_t3_003_outbound_pick_issue_and_reverse_parity():
    """T3.003 / FR3.023, FR3.024: Outbound pick, GI 601, and Reversal 602 on SAMPLE 800000045."""
    # 1. Pick item
    pick_res = client.post(
        "/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/PickOneItem",
        params={"DeliveryDocument": "800000045", "DeliveryDocumentItem": "000010", "PickedQuantity": "10.000"},
        headers={"sap-client": "100"},
    )
    assert pick_res.status_code == 200, pick_res.text

    # 2. Post Goods Issue (601)
    gi_res = client.post(
        "/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/PostGoodsIssue",
        params={"DeliveryDocument": "800000045"},
        headers={"sap-client": "100"},
    )
    assert gi_res.status_code == 200, gi_res.text
    gi_data = gi_res.json()["d"]
    assert int(gi_data["MaterialDocument"]) >= 4900000000
    assert gi_data["OverallGoodsIssueStatus"] == "C"

    # 3. Reverse Goods Issue (602)
    rev_res = client.post(
        "/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/ReverseGoodsIssue",
        params={"DeliveryDocument": "800000045"},
        headers={"sap-client": "100"},
    )
    assert rev_res.status_code == 200, rev_res.text
    rev_data = rev_res.json()["d"]
    assert rev_data["OverallGoodsIssueStatus"] == "A"
    assert int(rev_data["ReversalDocNumber"]) >= 4900000000


@pytest.mark.contract
def test_t3_004_physical_inventory_parity():
    """T3.004 / FR3.035, FR3.037: PI doc create with freeze snapshot, count entry, and PostDifferences."""
    # 1. Create PI doc
    create_res = client.post(
        "/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/A_PhysInventoryDocHeader",
        json={
            "Plant": "1010",
            "StorageLocation": "101A",
            "PhysicalInventoryDocumentFiscalYear": "2026",
            "PostingBlocked": True,
            "FreezeBookInventory": True,
            "to_PhysicalInventoryDocItem": [
                {"Material": "SAMPLE-MAT-0001", "Plant": "1010", "StorageLocation": "101A"}
            ],
        },
        headers={"sap-client": "100"},
    )
    assert create_res.status_code == 200, create_res.text
    doc_data = create_res.json()["d"]
    pi_doc = doc_data["PhysicalInventoryDocument"]
    assert int(pi_doc) >= 100000000
    assert doc_data["FreezeBookInventory"] is True

    # 2. Enter count via PATCH
    patch_res = client.patch(
        f"/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/A_PhysInventoryDocItem(PhysicalInventoryDocument='{pi_doc}',FiscalYear='2026',PhysicalInventoryDocumentItem='1')",
        json={"QuantityInEntryUnit": "105.000", "EntryUnit": "EA"},
        headers={"sap-client": "100"},
    )
    assert patch_res.status_code == 200, patch_res.text

    # 3. Post differences (gain 701)
    diff_res = client.post(
        "/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/PostDifferences",
        params={"PhysicalInventoryDocument": pi_doc, "FiscalYear": "2026"},
        headers={"sap-client": "100"},
    )
    assert diff_res.status_code == 200, diff_res.text
    diff_data = diff_res.json()["d"]
    assert int(diff_data["MaterialDocument"]) >= 4900000000


@pytest.mark.contract
def test_t3_005_material_document_cancel_and_409_reversal():
    """T3.005 / FR3.011, FR3.015, PR3.01: Cancel creates 102/602, second cancel returns 409 Conflict."""
    # 1. Create original material document (101)
    create_res = client.post(
        "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader",
        json={
            "GoodsMovementCode": "01",
            "to_MaterialDocumentItem": [
                {
                    "Material": "SAMPLE-MAT-0002",
                    "Plant": "1010",
                    "StorageLocation": "101A",
                    "GoodsMovementType": "101",
                    "QuantityInEntryUnit": "15.000",
                    "EntryUnit": "EA",
                }
            ],
        },
        headers={"sap-client": "100"},
    )
    assert create_res.status_code == 200, create_res.text
    orig_doc = create_res.json()["d"]["MaterialDocument"]
    orig_year = create_res.json()["d"]["MaterialDocumentYear"]

    # 2. Cancel original document -> creates reversal doc
    cancel_res = client.post(
        "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel",
        params={"MaterialDocument": orig_doc, "MaterialDocumentYear": orig_year},
        headers={"sap-client": "100"},
    )
    assert cancel_res.status_code == 200, cancel_res.text
    rev_data = cancel_res.json()["d"]
    assert rev_data["ReversalOf"] == orig_doc

    # 3. Second cancel must return HTTP 409 Conflict per spec T3.005!
    second_cancel = client.post(
        "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel",
        params={"MaterialDocument": orig_doc, "MaterialDocumentYear": orig_year},
        headers={"sap-client": "100"},
    )
    assert second_cancel.status_code == 409, f"Expected 409 on duplicate reversal, got {second_cancel.status_code}"


@pytest.mark.contract
def test_t3_006_declarative_mapping_files():
    """T3.006 / FR3.042, TC3.134: All 4 declarative mappings exist and rows carry VERIFIED/UNVERIFIED."""
    expected_files = [
        "inbound_delivery.yaml",
        "outbound_delivery.yaml",
        "physinv.yaml",
        "material_document.yaml",
    ]
    for fn in expected_files:
        path = MAPPINGS_DIR / fn
        assert path.exists(), f"Mapping file missing: {fn}"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "service" in data
        assert "entities" in data
        for entity_name, entity_def in data["entities"].items():
            for f_name, f_def in entity_def["fields"].items():
                status = f_def.get("status")
                assert status in ("VERIFIED", "UNVERIFIED"), f"Invalid status {status} in {fn}:{entity_name}.{f_name}"

    # Documentation check
    mapping_doc = ROOT / "docs" / "SPEC" / "F2_SAP_MAPPING.md"
    assert mapping_doc.exists()
    content = mapping_doc.read_text(encoding="utf-8")
    assert "API_INBOUND_DELIVERY_SRV" in content
    assert "API_OUTBOUND_DELIVERY_SRV" in content
    assert "API_PHYSICAL_INVENTORY_DOC_SRV" in content
    assert "API_MATERIAL_DOCUMENT_SRV" in content


@pytest.mark.contract
def test_t3_007_adapter_error_classification_and_golden_payload():
    """T3.007 / FR3.041, FR3.044: SAP error classification and deterministic golden payloads."""
    # 1. Error classification
    err_423 = classify_sap_error(423, {"error": {"code": "ZSIM/LOCKED", "message": {"value": "Locked"}}})
    assert err_423.is_retryable is True

    err_503 = classify_sap_error(503, {"error": {"code": "SERVER_ERROR", "message": "Unavailable"}})
    assert err_503.is_retryable is True

    err_400 = classify_sap_error(400, {"error": {"code": "ZSIM/UNDER-PICKED", "message": "Under-picked"}})
    assert err_400.is_retryable is False

    err_409 = classify_sap_error(409, {"error": {"code": "ZSIM/ALREADY-REVERSED", "message": "Already reversed"}})
    assert err_409.is_retryable is False

    # 2. Golden payload rendering
    golden_json = adapter.render_golden_payload("PostGoodsReceipt", DeliveryDocument="180000123")
    assert golden_json == '{"command":"PostGoodsReceipt","params":{"DeliveryDocument":"180000123"}}'


@pytest.mark.contract
def test_t3_008_sap_vcr_cassettes_parity():
    """T3.008 / PR3.15, TC3.135: Validates SAP VCR cassette fixture parity against S/4 contract."""
    cassette_file = CASSETTES_DIR / "inbound_gr_sample.yaml"
    assert cassette_file.exists(), "SAP VCR cassette fixture must be present for contract parity"

    with open(cassette_file, encoding="utf-8") as f:
        cassette_data = yaml.safe_load(f)

    interactions = cassette_data.get("interactions", [])
    assert len(interactions) > 0, "Cassette must contain recorded interactions"

    interaction = interactions[0]
    resp = interaction.get("response", {})
    assert resp.get("status", {}).get("code") == 200

    body_str = resp.get("body", {}).get("string", "{}")
    body_data = json.loads(body_str)
    assert "d" in body_data, "Response must follow SAP OData v2 {'d': ...} envelope"

    d = body_data["d"]
    assert "MaterialDocument" in d
    assert int(d["MaterialDocument"]) >= 4900000000
    assert d["DeliveryDocument"] == "180000123"
    assert d["OverallGoodsMovementStatus"] == "C"


@pytest.mark.contract
def test_t3_009_warehouse_fault_injection_and_prod_rejection():
    """T3.009 / FR3.040, FR3.043: Fault profile injection via header and production rejection."""
    # Test fault injection in development
    os.environ["ENVIRONMENT"] = "development"
    lock_res = client.get(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader('180000001')",
        headers={"x-sim-fault-profile": "warehouse_lock", "x-sim-force-fault": "true"},
    )
    assert lock_res.status_code == 423
    assert "ZSIM/LOCKED" in lock_res.text

    # Test rejection in production build
    os.environ["ENVIRONMENT"] = "production"
    try:
        prod_res = client.get(
            "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader('180000001')",
            headers={"x-sim-fault-profile": "warehouse_lock"},
        )
        assert prod_res.status_code == 400
        assert "FIELD-FAULT-PROD-REJECTED" in prod_res.text
    finally:
        os.environ["ENVIRONMENT"] = "development"
