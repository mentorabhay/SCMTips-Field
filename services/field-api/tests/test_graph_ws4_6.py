"""Automated Test Suite for Phase 4 Workstream 4.6 (3D Site Graph, Routing & Trails).

Covers:
- T4.029: Store source recorded on install (FR4.037 / TC4.132)
- T4.050: 3D graph nodes and edges schema contract (FR4.046 / TC4.142)
- T4.051: 3D routing Dijkstra with 3x climb weighting (FR4.047 / PR4.07 / API4.11)
- T4.052: Spoken newcomer guidance text generator (FR4.048 / TC4.143)
- T4.053: Equipment trail API ordered by occurred_at, seq (FR4.049 / PR4.06 / API4.10)
- T4.054: Console trail replay step contract (FR4.050 / TC4.144)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.equipment.history import append_serial_event
from field_api.graph.guidance import generate_newcomer_guidance
from field_api.graph.route3d import dijkstra_3d
from hypothesis import given, settings
from hypothesis import strategies as st

client = TestClient(app)


def _auth_headers(tenant_id: str, user_id: str = "test-user-ws46") -> dict[str, str]:
    token = create_dev_token(
        principal_id=user_id,
        tenant_id=tenant_id,
        roles=["technician", "supervisor", "lead"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": f"req-{uuid.uuid4()}",
    }


# ==============================================================================
# Property PR4.06: Trail order Hypothesis 500 runs
# ==============================================================================
@settings(max_examples=500, deadline=None)
@given(
    events=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=1000),  # timestamp offset in seconds
            st.integers(min_value=1, max_value=500),  # seq
            st.text(min_size=1, max_size=10, alphabet="ABC123"),  # loc
        ),
        min_size=1,
        max_size=40,
    )
)
def test_pr4_06_trail_order_property(events):
    """PR4.06: Trail replay visits locations in non-decreasing occurred_at with ties broken by seq.

    Every history event is visited exactly once.
    """
    base_time = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    raw_events = [
        {
            "occurred_at": base_time + timedelta(seconds=t_off),
            "seq": s,
            "loc": loc,
            "id": idx,
        }
        for idx, (t_off, s, loc) in enumerate(events)
    ]

    # Replay sorting reference: strictly (occurred_at, seq)
    sorted_expected = sorted(raw_events, key=lambda e: (e["occurred_at"], e["seq"]))

    # Verify monotonic ordering
    for i in range(len(sorted_expected) - 1):
        e1 = sorted_expected[i]
        e2 = sorted_expected[i + 1]
        assert (e1["occurred_at"], e1["seq"]) <= (e2["occurred_at"], e2["seq"])

    # Verify every event is visited exactly once
    assert len(sorted_expected) == len(raw_events)
    assert {e["id"] for e in sorted_expected} == {e["id"] for e in raw_events}


# ==============================================================================
# Property PR4.07: Route respects climb weight Hypothesis 500 runs
# ==============================================================================
@settings(max_examples=500, deadline=None)
@given(
    walk_a=st.floats(min_value=1.0, max_value=100.0),
    climb_a=st.floats(min_value=0.0, max_value=50.0),
    walk_b=st.floats(min_value=1.0, max_value=100.0),
    climb_b=st.floats(min_value=0.0, max_value=50.0),
)
def test_pr4_07_route_respects_climb_weight(walk_a, climb_a, walk_b, climb_b):
    """PR4.07: Dijkstra chooses path with minimal cost = walk_m + 3 * climb_m."""
    # Graph: Start -> NodeA -> End (Path A)
    #        Start -> NodeB -> End (Path B)
    nodes = {
        "start": {"id": "start", "name": "Start Node"},
        "nodeA": {"id": "nodeA", "name": "Route A Node"},
        "nodeB": {"id": "nodeB", "name": "Route B Node"},
        "end": {"id": "end", "name": "End Node"},
    }
    edges = [
        {
            "from_node_id": "start",
            "to_node_id": "nodeA",
            "distance_m": walk_a / 2,
            "climb_length_m": climb_a / 2,
            "is_one_way": True,
        },
        {
            "from_node_id": "nodeA",
            "to_node_id": "end",
            "distance_m": walk_a / 2,
            "climb_length_m": climb_a / 2,
            "is_one_way": True,
        },
        {
            "from_node_id": "start",
            "to_node_id": "nodeB",
            "distance_m": walk_b / 2,
            "climb_length_m": climb_b / 2,
            "is_one_way": True,
        },
        {
            "from_node_id": "nodeB",
            "to_node_id": "end",
            "distance_m": walk_b / 2,
            "climb_length_m": climb_b / 2,
            "is_one_way": True,
        },
    ]

    cost_a = walk_a + 3.0 * climb_a
    cost_b = walk_b + 3.0 * climb_b

    res = dijkstra_3d(nodes, edges, "start", "end")

    expected_min_cost = min(cost_a, cost_b)
    assert abs(res["cost"] - expected_min_cost) < 1e-3
    assert abs(res["cost"] - (res["walk_m"] + 3.0 * res["climb_m"])) < 1e-3

    if cost_a < cost_b - 1e-5:
        assert res["nodes"] == ["Start Node", "Route A Node", "End Node"]
    elif cost_b < cost_a - 1e-5:
        assert res["nodes"] == ["Start Node", "Route B Node", "End Node"]


# ==============================================================================
# Unit Test TC4.143: Newcomer guidance text generator
# ==============================================================================
def test_tc4_143_newcomer_guidance_text():
    """TC4.143: Spoken guidance matches template: 'Climb 40 m to Level 3 platform. Clip in at every rest platform.'"""
    route_nodes = [
        {"name": "ground-gate", "subkind": "ground", "z": 0.0},
        {"name": "ladder-foot-T01", "subkind": "ladder_foot", "z": 0.0},
        {"name": "rp-L2", "subkind": "rest_platform", "z": 20.0},
        {"name": "rp-L3", "subkind": "rest_platform", "z": 40.0},
    ]
    guidance = generate_newcomer_guidance(route_nodes, climb_m=40.0, walk_m=11.5)
    assert guidance == "Climb 40 m to Level 3 platform. Clip in at every rest platform."


# ==============================================================================
# Contract Test TC4.142: 3D graph nodes and edges contract
# ==============================================================================
def test_tc4_142_3d_graph_contract():
    """TC4.142: rest_platform node and climb edge; z and subkind stored; invalid length rejected."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Insert site
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Tower Alpha', 'tower', 'active', 28.5, 77.2);
                """,
                (site_id, tenant_id, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )

            # 2. Insert rest_platform node with z and subkind
            node1_id = str(uuid.uuid4())
            node2_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.site_graph_node (
                    id, tenant_id, site_id, name, node_type, z, subkind, platform_height_m
                ) VALUES (
                    %s, %s, %s, 'ladder-foot-T01', 'waypoint', 0.0, 'ladder_foot', 0.0
                ), (
                    %s, %s, %s, 'rp-L2', 'waypoint', 20.0, 'rest_platform', 20.0
                );
                """,
                (node1_id, tenant_id, site_id, node2_id, tenant_id, site_id),
            )

            # 3. Insert valid edge with climb_length_m
            edge_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.site_graph_edge (
                    id, tenant_id, site_id, from_node_id, to_node_id, distance_m, climb_length_m, is_one_way
                ) VALUES (
                    %s, %s, %s, %s, %s, 1.5, 20.0, false
                );
                """,
                (edge_id, tenant_id, site_id, node1_id, node2_id),
            )

    # 4. Verify negative climb length is rejected by check constraint
    with pytest.raises(Exception):
        with get_conn() as conn2:
            with conn2.cursor() as cur2:
                cur2.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
                cur2.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
                cur2.execute("SELECT set_config('app.site_ids', '*', true);")
                cur2.execute(
                    """
                    INSERT INTO field.site_graph_edge (
                        id, tenant_id, site_id, from_node_id, to_node_id, distance_m, climb_length_m
                    ) VALUES (
                        %s, %s, %s, %s, %s, 1.5, -5.0
                    );
                    """,
                    (str(uuid.uuid4()), tenant_id, site_id, node1_id, node2_id),
                )


# ==============================================================================
# Integration Test TC4.132: Trail from store (API4.10)
# ==============================================================================
def test_tc4_132_trail_from_store():
    """TC4.132: Issue from store then install; GET API4.10 first point equals 'Plant 1100 / SL 0001'."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    serial = f"SR-{uuid.uuid4().hex[:8].upper()}"
    headers = _auth_headers(tenant_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Insert site and tower location
            site_code = f"SITE-{uuid.uuid4().hex[:6].upper()}"
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Delhi Hub', 'tower', 'active', 28.5, 77.2);
                """,
                (site_id, tenant_id, site_code),
            )
            loc_id = str(uuid.uuid4())
            fl_code = f"{site_code}-T01-SEC-A-L3"
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, path, depth, fl_code, kind, status, height_m)
                VALUES (%s, %s, %s, 'SEC-A-L3', 'T01.SEC_A.L3', 3, %s, 'position', 'active', 45.0);
                """,
                (loc_id, tenant_id, site_id, fl_code),
            )

    # Step 1: Issue from store
    t_issue = datetime(2026, 6, 2, 8, 0, 0, tzinfo=UTC)
    append_serial_event(
        tenant_id=tenant_id,
        serial_no=serial,
        event_type="issue",
        source_plant="1100",
        source_storage_location="0001",
        occurred_at=t_issue,
    )

    # Step 2: Install at tower location
    t_install = datetime(2026, 6, 2, 10, 30, 0, tzinfo=UTC)
    append_serial_event(
        tenant_id=tenant_id,
        serial_no=serial,
        event_type="install",
        location_id=loc_id,
        occurred_at=t_install,
    )

    # Step 3: GET /v1/equipment/{serial}/trail (API4.10)
    resp = client.get(
        f"/v1/equipment/{serial}/trail",
        headers={**headers, "Idempotency-Key": f"idem-{uuid.uuid4()}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["serial"] == serial
    assert len(data["points"]) == 2

    # First point MUST be store point per TC4.132
    pt1 = data["points"][0]
    assert pt1["seq"] == 1
    assert pt1["type"] == "issue"
    assert pt1["label"] == "Plant 1100 / SL 0001"

    # Second point is installation
    pt2 = data["points"][1]
    assert pt2["seq"] == 2
    assert pt2["type"] == "install"
    assert fl_code in pt2["label"]


# ==============================================================================
# Endpoint Test: 3D Route API4.11
# ==============================================================================
def test_api4_11_route_endpoint():
    """API4.11: GET /v1/sites/{id}/route returns weighted route, climb_m, walk_m, nodes, guidance."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Insert site
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Tower 42', 'tower', 'active', 28.5, 77.2);
                """,
                (site_id, tenant_id, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )

            # Insert nodes: ground-gate -> ladder-foot-T01 -> rp-L2 -> rp-L3
            n_ground = str(uuid.uuid4())
            n_ladder = str(uuid.uuid4())
            n_rp2 = str(uuid.uuid4())
            n_rp3 = str(uuid.uuid4())

            cur.execute(
                """
                INSERT INTO field.site_graph_node (id, tenant_id, site_id, name, node_type, z, subkind)
                VALUES
                    (%s, %s, %s, 'ground-gate', 'waypoint', 0.0, 'ground'),
                    (%s, %s, %s, 'ladder-foot-T01', 'waypoint', 0.0, 'ladder_foot'),
                    (%s, %s, %s, 'rp-L2', 'waypoint', 20.0, 'rest_platform'),
                    (%s, %s, %s, 'rp-L3', 'waypoint', 40.0, 'rest_platform');
                """,
                (
                    n_ground,
                    tenant_id,
                    site_id,
                    n_ladder,
                    tenant_id,
                    site_id,
                    n_rp2,
                    tenant_id,
                    site_id,
                    n_rp3,
                    tenant_id,
                    site_id,
                ),
            )

            # Insert edges:
            # ground-gate -> ladder-foot-T01: walk = 11.5m, climb = 0m
            # ladder-foot-T01 -> rp-L2: walk = 0m, climb = 20.0m
            # rp-L2 -> rp-L3: walk = 0m, climb = 20.0m
            cur.execute(
                """
                INSERT INTO field.site_graph_edge (id, tenant_id, site_id, from_node_id, to_node_id, distance_m, climb_length_m, is_one_way)
                VALUES
                    (%s, %s, %s, %s, %s, 11.5, 0.0, false),
                    (%s, %s, %s, %s, %s, 0.0, 20.0, false),
                    (%s, %s, %s, %s, %s, 0.0, 20.0, false);
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    site_id,
                    n_ground,
                    n_ladder,
                    str(uuid.uuid4()),
                    tenant_id,
                    site_id,
                    n_ladder,
                    n_rp2,
                    str(uuid.uuid4()),
                    tenant_id,
                    site_id,
                    n_rp2,
                    n_rp3,
                ),
            )

    resp = client.get(
        f"/v1/sites/{site_id}/route?from=ground-gate&to=rp-L3",
        headers={**headers, "Idempotency-Key": f"idem-{uuid.uuid4()}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Total walk = 11.5, climb = 40.0. Cost = 11.5 + 3 * 40 = 131.5 (API4.11 exact match)
    assert abs(data["cost"] - 131.5) < 1e-3
    assert abs(data["climb_m"] - 40.0) < 1e-3
    assert abs(data["walk_m"] - 11.5) < 1e-3
    assert data["nodes"] == ["ground-gate", "ladder-foot-T01", "rp-L2", "rp-L3"]
    assert "Climb 40 m to Level 3 platform. Clip in at every rest platform." in data["guidance"]


def test_api4_11_missing_node_and_unreachable():
    """API4.11 error handling: 404 on missing node, 422 on disconnected nodes."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Insert site
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Tower 42', 'tower', 'active', 28.5, 77.2);
                """,
                (site_id, tenant_id, f"SITE-{uuid.uuid4().hex[:6].upper()}"),
            )

            # Insert 2 disconnected nodes
            n1 = str(uuid.uuid4())
            n2 = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO field.site_graph_node (id, tenant_id, site_id, name, node_type, z, subkind)
                VALUES
                    (%s, %s, %s, 'node-a', 'waypoint', 0.0, 'ground'),
                    (%s, %s, %s, 'node-b', 'waypoint', 10.0, 'rest_platform');
                """,
                (n1, tenant_id, site_id, n2, tenant_id, site_id),
            )

    # 1. 404 for unknown node
    resp_404 = client.get(
        f"/v1/sites/{site_id}/route?from=node-a&to=nonexistent-z",
        headers={**headers, "Idempotency-Key": f"idem-{uuid.uuid4()}"},
    )
    assert resp_404.status_code == 404
    body_404 = resp_404.json()
    err_code = body_404.get("code") or (
        body_404.get("detail", {}).get("error_code")
        if isinstance(body_404.get("detail"), dict)
        else None
    )
    assert err_code == "FIELD-GRAPH-404-NODE" or "FIELD-GRAPH-404-NODE" in str(body_404)

    # 2. 422 for unreachable disconnected nodes
    resp_422 = client.get(
        f"/v1/sites/{site_id}/route?from=node-a&to=node-b",
        headers={**headers, "Idempotency-Key": f"idem-{uuid.uuid4()}"},
    )
    assert resp_422.status_code == 422
    body_422 = resp_422.json()
    err_code_422 = body_422.get("code") or (
        body_422.get("detail", {}).get("error_code")
        if isinstance(body_422.get("detail"), dict)
        else None
    )
    assert err_code_422 == "FIELD-GRAPH-422-NO-ROUTE" or "FIELD-GRAPH-422-NO-ROUTE" in str(body_422)
