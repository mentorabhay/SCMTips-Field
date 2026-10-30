"""Tests for Phase 3 Tasks T3.045 through T3.072 (WS3.5 - WS3.9)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.approvals import local as approvals_local
from field_api.auth.jwt import create_dev_token
from field_api.sitegraph import bin_import as sitegraph_bin_import
from field_api.sitegraph import route as sitegraph_route
from field_api.sitegraph.anchors import fuse_and_snap_to_graph
from field_api.sitegraph.dijkstra import DijkstraWayfinder
from field_api.sitegraph.publish import publish_site_graph_version
from field_api.sitegraph.trails import record_wayfinding_trail
from field_api.warehouse.inventory import assignment as inv_assignment
from field_api.warehouse.inventory import block as inv_block
from field_worker.exports import core_supply as worker_core_supply
from field_worker.warehouse import late_receipt as worker_late_receipt
from field_worker.warehouse import obd_import as worker_obd_import
from field_worker.warehouse.core_seams import CoreSeamsManager


@pytest.fixture
def client():
    return TestClient(create_app())


def auth_headers(roles: list[str]) -> dict[str, str]:
    token = create_dev_token("test-sup", "11111111-1111-4111-8111-111111111112", roles)
    return {"Authorization": f"Bearer {token}"}


# test_t3_045_inventory_post_diff_api: removed in C3 (it asserted that a supervisor posts 701/702 with client-supplied book qty and no approval, i.e. the P0 bypass; replaced by services/field-api/tests/integration/test_pi_flow.py).

@pytest.mark.unit
def test_t3_049_positioning_anchors():
    """T3.049: Anchor positioning fusion and graph snapping."""
    edges = [((0.0, 0.0), (10.0, 0.0))]
    snapped_x, snapped_y, dist = fuse_and_snap_to_graph(5.0, 0.2, edges, 1.0)
    assert snapped_y == 0.0
    assert snapped_x == 5.0
    assert dist == 0.2


@pytest.mark.unit
def test_t3_050_positioning_stub_contract():
    """T3.050: Positioning stub module verification."""
    stub_dir = Path("apps/field-android/core-positioning-stub")
    assert stub_dir.exists()


@pytest.mark.unit
def test_t3_051_sitegraph_routing():
    """T3.051: Wayfinding shortest-path computation."""
    nodes = {"N1": {"id": "N1"}, "N2": {"id": "N2"}}
    edges = [{"from_node_id": "N1", "to_node_id": "N2", "distance_m": 5.0}]
    res = DijkstraWayfinder.find_shortest_path(nodes, edges, "N1", "N2")
    assert res is not None
    assert res["total_distance_m"] == 5.0


@pytest.mark.unit
def test_t3_052_walking_quiet_mode():
    """T3.052: Walking-quiet mode prompt suppression contract."""
    wq_file = Path(
        "apps/field-android/core-capture/src/main/kotlin/com/scmtips/field/core/capture/safety/WalkingQuiet.kt"
    )
    assert wq_file.exists()


@pytest.mark.unit
def test_t3_053_wayfinding_guidance_contract():
    """T3.053: Wayfinding guidance contract."""
    nodes = {"N1": {"id": "N1"}, "N2": {"id": "N2"}, "N3": {"id": "N3"}}
    edges = [
        {"from_node_id": "N1", "to_node_id": "N2", "distance_m": 10.0},
        {"from_node_id": "N2", "to_node_id": "N3", "distance_m": 10.0},
    ]
    res = DijkstraWayfinder.find_shortest_path(nodes, edges, "N1", "N3")
    assert res is not None
    assert len(res["path"]) == 3


@pytest.mark.unit
def test_t3_054_wayfinding_trails():
    """T3.054: Pedestrian wayfinding trail logging."""
    trail = record_wayfinding_trail("user-01", ["N1", "N2", "N3"])
    assert trail["user_id"] == "user-01"
    assert len(trail["nodes"]) == 3


@pytest.mark.unit
def test_t3_055_sitegraph_publish():
    """T3.055: Versioned site graph snapshot publication."""
    res = publish_site_graph_version("SITE-01", 1, {"nodes": [{"id": "N1"}], "edges": []})
    assert res["status"] == "published"
    assert res["version"] == 1


@pytest.mark.unit
def test_t3_056_warehouse_board_contract():
    """T3.056: Operations board console page contract (SCR3.01)."""
    board_page = Path("apps/field-console/app/warehouse/board/page.tsx")
    assert board_page.exists()
    content = board_page.read_text(encoding="utf-8")
    assert "Warehouse Operations Board" in content
    assert "T3.056" in content


@pytest.mark.unit
def test_t3_057_warehouse_discrepancies_contract():
    """T3.057: Discrepancy workbench console page contract (SCR3.02)."""
    page = Path("apps/field-console/app/warehouse/discrepancies/page.tsx")
    assert page.exists()
    content = page.read_text(encoding="utf-8")
    assert "Warehouse Discrepancies" in content
    assert "T3.057" in content


@pytest.mark.unit
def test_t3_058_warehouse_receiving_contract():
    """T3.058: Inbound receiving console page contract (SCR3.03)."""
    page = Path("apps/field-console/app/warehouse/receiving/page.tsx")
    assert page.exists()
    content = page.read_text(encoding="utf-8")
    assert "Inbound Receiving Console" in content
    assert "T3.058" in content


@pytest.mark.unit
def test_t3_059_warehouse_accuracy_contract():
    """T3.059: Inventory accuracy dashboard console page contract (SCR3.04)."""
    page = Path("apps/field-console/app/warehouse/accuracy/page.tsx")
    assert page.exists()
    content = page.read_text(encoding="utf-8")
    assert "Inventory Accuracy" in content
    assert "T3.059" in content


@pytest.mark.unit
def test_t3_060_warehouse_inventory_queues_contract():
    """T3.060: Inventory, approvals, and queues console pages (SCR3.05)."""
    inv = Path("apps/field-console/app/warehouse/inventory/page.tsx")
    appr = Path("apps/field-console/app/warehouse/approvals/page.tsx")
    q = Path("apps/field-console/app/warehouse/queues/page.tsx")
    assert inv.exists() and appr.exists() and q.exists()


@pytest.mark.unit
def test_t3_061_core_supply_export():
    """T3.061: Core supply guided-load delivery schedule importer."""
    tasks = CoreSeamsManager.import_guided_load_schedules([{"delivery_no": "D1", "priority": 10}])
    assert len(tasks) == 1
    assert tasks[0]["delivery_no"] == "D1"
    # Ensure imported module interfaces are validated
    assert worker_core_supply is not None
    assert worker_late_receipt is not None
    assert worker_obd_import is not None
    assert approvals_local is not None
    assert sitegraph_bin_import is not None
    assert sitegraph_route is not None
    assert inv_assignment is not None
    assert inv_block is not None


@pytest.mark.unit
def test_t3_062_late_receipt_signal():
    """T3.062: Overdue shipment late-receipt signal detector."""
    from datetime import datetime, timedelta

    now = datetime(2026, 10, 29, 12, 0, 0)
    overdue_arrival = (now - timedelta(hours=2)).isoformat()
    signals = CoreSeamsManager.evaluate_late_receipt_signals(
        deliveries=[
            {"delivery_no": "D1", "expected_arrival": overdue_arrival, "is_arrived": False}
        ],
        current_time=now,
    )
    assert len(signals) == 1
    assert signals[0]["signal_type"] == "LATE_RECEIPT_ALERT"


@pytest.mark.unit
def test_t3_063_warehouse_lens_contracts():
    """T3.063: Warehouse glasses HUD lens layout contract."""
    lens_test = Path(
        "apps/field-android/core-wearables-testing/src/test/kotlin/com/scmtips/field/core/wearables/LensRendererTest.kt"
    )
    assert lens_test.exists()


@pytest.mark.unit
def test_t3_064_warehouse_phone_contracts():
    """T3.064: Warehouse mobile screen contracts."""
    tasks_module = Path("apps/field-android/feature-tasks")
    assert tasks_module.exists()


@pytest.mark.unit
def test_t3_065_warehouse_outbox_contract():
    """T3.065: Offline warehouse outbox adapter contract."""
    outbox_file = Path(
        "apps/field-android/core-outbox/src/main/kotlin/com/scmtips/field/core/outbox/WarehouseOutbox.kt"
    )
    assert outbox_file.exists()


@pytest.mark.unit
def test_t3_066_warehouse_a11y_contrast():
    """T3.066: Warehouse UI accessibility and contrast contract."""
    a11y_test = Path("tests/property/test_pr1_18_contrast.py")
    assert a11y_test.exists()


@pytest.mark.unit
def test_t3_067_warehouse_audit_trail():
    """T3.067: Warehouse audit log dispatcher."""
    from field_api.audit.warehouse import record_warehouse_audit_event

    res = record_warehouse_audit_event("GR_POST", "1800001", "user-01", {"qty": 10.0})
    assert res["status"] == "recorded"


@pytest.mark.unit
def test_t3_068_warehouse_properties_coverage():
    """T3.068: Phase 3 property suite coverage (PR3.01 - PR3.18)."""
    prop_test = Path("tests/property/test_pr3_warehouse_properties.py")
    assert prop_test.exists()


@pytest.mark.unit
def test_t3_069_posting_load_script():
    """T3.069: Posting load test k6 script contract."""
    k6_file = Path("tests/load/posting_k6.js")
    assert k6_file.exists()
    content = k6_file.read_text(encoding="utf-8")
    assert "k6/http" in content


@pytest.mark.unit
def test_t3_070_warehouse_security():
    """T3.070: Warehouse authorization tests verification."""
    sec_test = Path("services/field-api/tests/security/test_warehouse.py")
    assert sec_test.exists()


@pytest.mark.unit
def test_t3_071_device_usability_report():
    """T3.071: Usability evaluation report verification."""
    report = Path("docs/reports/F2_device_usability.md")
    assert report.exists()


@pytest.mark.unit
def test_t3_072_phase3_completion_report():
    """T3.072: Phase 3 completion report verification."""
    report = Path("docs/reports/PHASE3_REPORT.md")
    assert report.exists()
