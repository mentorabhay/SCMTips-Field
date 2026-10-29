"""Unit and integration tests for WS3.6 Site Graph & Dijkstra Wayfinding (Tasks T3.046 - T3.055).

Covers:
- T3.046: Node and edge construction, bin tree hierarchy validation (PR3.11).
- T3.047: Dijkstra shortest-path calculations (TC3.130 / PR3.09).
- T3.048: Position fusion and graph edge snapping (PR3.17).
"""

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token
from field_api.sitegraph.anchors import fuse_and_snap_to_graph
from field_api.sitegraph.dijkstra import DijkstraWayfinder
from field_api.sitegraph.graph import BinTreeValidationException, validate_bin_hierarchy_tree


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def auth_headers(role: str = "field.supervisor") -> dict[str, str]:
    token = create_dev_token(
        principal_id="user-sup-1",
        tenant_id="tenant-test-1",
        roles=[role],
        site_ids=["site-1"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# -----------------------------------------------------------------------------
# T3.046: Bin Tree Hierarchy Validation (PR3.11)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_046_bin_hierarchy_tree_validation():
    # Valid tree: Warehouse -> Aisle 1 -> Rack 01 -> Bin A-01-01
    valid_locations = [
        {"id": "loc-wh", "parent_id": None},
        {"id": "loc-aisle-1", "parent_id": "loc-wh"},
        {"id": "loc-rack-01", "parent_id": "loc-aisle-1"},
        {"id": "bin-a0101", "parent_id": "loc-rack-01"},
    ]
    assert validate_bin_hierarchy_tree(valid_locations) is True

    # Invalid: Multiple parents for one bin
    multi_parent = [
        {"id": "bin-x", "parent_id": "rack-1"},
        {"id": "bin-x", "parent_id": "rack-2"},
    ]
    with pytest.raises(BinTreeValidationException):
        validate_bin_hierarchy_tree(multi_parent)

    # Invalid: Directed cycle A -> B -> A
    cycle = [
        {"id": "loc-A", "parent_id": "loc-B"},
        {"id": "loc-B", "parent_id": "loc-A"},
    ]
    with pytest.raises(BinTreeValidationException):
        validate_bin_hierarchy_tree(cycle)


# -----------------------------------------------------------------------------
# T3.047: Dijkstra Shortest Path (TC3.130 / PR3.09)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_047_dijkstra_shortest_path():
    nodes = {
        "N1": {"name": "Dock 1"},
        "N2": {"name": "Intersection A"},
        "N3": {"name": "Aisle 1 Start"},
        "N4": {"name": "Bin A-01-01"},
    }
    # Path 1: N1 -> N2 (5m), N2 -> N4 (10m) = total 15m
    # Path 2: N1 -> N3 (8m), N3 -> N4 (4m) = total 12m (Shortest)
    edges = [
        {"from": "N1", "to": "N2", "distance_m": 5.0},
        {"from": "N2", "to": "N4", "distance_m": 10.0},
        {"from": "N1", "to": "N3", "distance_m": 8.0},
        {"from": "N3", "to": "N4", "distance_m": 4.0},
    ]

    res = DijkstraWayfinder.find_shortest_path(nodes, edges, "N1", "N4")
    assert res is not None
    assert res["total_distance_m"] == 12.0
    assert res["path"] == ["N1", "N3", "N4"]

    # Invariant PR3.09: Uses strictly existing edges
    traversed_edges = res["edges"]
    assert len(traversed_edges) == 2

    # Unreachable target returns None
    nodes_disc = dict(nodes)
    nodes_disc["N_ISOLATED"] = {"name": "Isolated"}
    assert DijkstraWayfinder.find_shortest_path(nodes_disc, edges, "N1", "N_ISOLATED") is None


# -----------------------------------------------------------------------------
# T3.048: Position Fusion and Graph Snapping (PR3.17)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t3_048_position_fusion_and_snapping():
    # Corridor edge along x-axis from (0, 0) to (10, 0)
    edges = [((0.0, 0.0), (10.0, 0.0))]

    # User slightly off corridor at (5.0, 0.4)
    raw_x, raw_y = 5.0, 0.4
    snapped_x, snapped_y, dist = fuse_and_snap_to_graph(raw_x, raw_y, edges)

    assert snapped_x == 5.0
    assert snapped_y == 0.0
    assert dist == pytest.approx(0.4, abs=1e-4)
    assert dist <= 1.0  # Snapped within 1.0m tolerance (PR3.17)


# -----------------------------------------------------------------------------
# FastApi Endpoint Routing Tests
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_sitegraph_api_endpoints(client):
    headers = auth_headers("field.supervisor")

    # 1. Add nodes
    client.post(
        "/v1/sitegraph/nodes",
        json={"id": "node-1", "name": "Start Waypoint", "x_m": 0.0, "y_m": 0.0},
        headers=headers,
    )
    client.post(
        "/v1/sitegraph/nodes",
        json={"id": "node-2", "name": "End Bin", "x_m": 10.0, "y_m": 0.0, "bin_id": "BIN-01"},
        headers=headers,
    )

    # 2. Add edge
    client.post(
        "/v1/sitegraph/edges",
        json={"from_node_id": "node-1", "to_node_id": "node-2", "distance_m": 10.0},
        headers=headers,
    )

    # 3. Shortest path
    path_resp = client.post(
        "/v1/sitegraph/shortest-path",
        json={"start_node_id": "node-1", "target_node_id": "node-2"},
        headers=headers,
    )
    assert path_resp.status_code == 200
    assert path_resp.json()["total_distance_m"] == 10.0

    # 4. Snap position
    snap_resp = client.post(
        "/v1/sitegraph/snap",
        json={"raw_x": 4.0, "raw_y": 0.2},
        headers=headers,
    )
    assert snap_resp.status_code == 200
    assert snap_resp.json()["is_on_graph"] is True
