"""3D Routing Engine with Climb Weighting (Task T4.051 / FR4.047 / PR4.07 / API4.11).

Computes shortest paths in 3D site structure using Dijkstra's algorithm.
Weighting formula:
    cost = walk_distance_m + 3.0 * climb_length_m
Vertical climb is penalized 3x relative to horizontal walking (FR4.047).
"""

from __future__ import annotations

import heapq
from typing import Any

import structlog
from fastapi import HTTPException, status
from field_api.db import get_conn
from field_api.graph.guidance import generate_newcomer_guidance

logger = structlog.get_logger(__name__)

CLIMB_WEIGHT = 3.0


def dijkstra_3d(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    from_id: str,
    to_id: str,
) -> dict[str, Any]:
    """Pure Dijkstra algorithm on 3D site graph with 3x climb weighting (PR4.07).

    Args:
        nodes: Map of node_id -> node attributes (name, subkind, z, etc.)
        edges: List of edge dictionaries (from_node_id, to_node_id, distance_m, climb_length_m, is_one_way)
        from_id: Start node identifier
        to_id: Destination node identifier

    Returns:
        dict with cost, climb_m, walk_m, nodes (list of names), node_details, guidance
    """
    if from_id not in nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "FIELD-GRAPH-404-NODE",
                "message": f"Source node '{from_id}' not found in site graph",
            },
        )
    if to_id not in nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "FIELD-GRAPH-404-NODE",
                "message": f"Target node '{to_id}' not found in site graph",
            },
        )

    # Build adjacency list
    adj: dict[str, list[tuple[str, float, float, float]]] = {nid: [] for nid in nodes}
    for e in edges:
        u = str(e["from_node_id"])
        v = str(e["to_node_id"])
        if u not in nodes or v not in nodes:
            continue
        walk = float(e.get("distance_m", 0.0) or 0.0)
        climb = float(e.get("climb_length_m", 0.0) or 0.0)
        cost = walk + CLIMB_WEIGHT * climb
        is_one_way = bool(e.get("is_one_way", False))

        adj[u].append((v, cost, walk, climb))
        if not is_one_way:
            adj[v].append((u, cost, walk, climb))

    # Dijkstra priority queue: (cumulative_cost, node_id)
    dist: dict[str, float] = {nid: float("inf") for nid in nodes}
    dist[from_id] = 0.0
    # prev: node_id -> (prev_node_id, walk, climb)
    prev: dict[str, tuple[str, float, float] | None] = dict.fromkeys(nodes)

    heap: list[tuple[float, str]] = [(0.0, from_id)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        if u == to_id:
            break

        for v, edge_cost, walk, climb in adj[u]:
            new_cost = d + edge_cost
            if new_cost < dist[v]:
                dist[v] = new_cost
                prev[v] = (u, walk, climb)
                heapq.heappush(heap, (new_cost, v))

    if dist[to_id] == float("inf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-GRAPH-422-NO-ROUTE",
                "message": f"No route exists between '{from_id}' and '{to_id}'",
            },
        )

    # Reconstruct path
    curr: str | None = to_id
    path_nodes: list[str] = []
    tot_walk = 0.0
    tot_climb = 0.0

    while curr is not None:
        path_nodes.append(curr)
        step = prev[curr]
        if step is not None:
            prev_node, w, c = step
            tot_walk += w
            tot_climb += c
            curr = prev_node
        else:
            curr = None

    path_nodes.reverse()

    # Resolve display names and detailed node objects
    node_names = [nodes[nid].get("name") or nid for nid in path_nodes]
    node_details = [nodes[nid] for nid in path_nodes]
    total_cost = tot_walk + CLIMB_WEIGHT * tot_climb

    guidance = generate_newcomer_guidance(node_details, tot_climb, tot_walk)

    return {
        "cost": round(total_cost, 4),
        "climb_m": round(tot_climb, 4),
        "walk_m": round(tot_walk, 4),
        "nodes": node_names,
        "node_ids": path_nodes,
        "guidance": guidance,
    }


def compute_3d_route(
    tenant_id: str,
    site_id: str,
    from_ref: str,
    to_ref: str,
) -> dict[str, Any]:
    """Load site graph from database and compute 3D route (API4.11 / FR4.047)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Load nodes
            cur.execute(
                """
                SELECT id, name, x_m, y_m, z_m, z, subkind, platform_height_m, sector_code
                FROM field.site_graph_node
                WHERE tenant_id = %s AND site_id = %s;
                """,
                (tenant_id, site_id),
            )
            node_rows = cur.fetchall()

            # Load edges
            cur.execute(
                """
                SELECT from_node_id, to_node_id, distance_m, climb_length_m, is_one_way
                FROM field.site_graph_edge
                WHERE tenant_id = %s AND site_id = %s;
                """,
                (tenant_id, site_id),
            )
            edge_rows = cur.fetchall()

    nodes: dict[str, dict[str, Any]] = {}
    name_to_id: dict[str, str] = {}

    for r in node_rows:
        nid = str(r[0])
        name = r[1]
        nodes[nid] = {
            "id": nid,
            "name": name,
            "x_m": float(r[2]) if r[2] is not None else None,
            "y_m": float(r[3]) if r[3] is not None else None,
            "z_m": float(r[4]) if r[4] is not None else None,
            "z": float(r[5]) if r[5] is not None else None,
            "subkind": r[6],
            "platform_height_m": float(r[7]) if r[7] is not None else None,
            "sector_code": r[8],
        }
        if name:
            name_to_id[name] = nid

    edges = [
        {
            "from_node_id": str(r[0]),
            "to_node_id": str(r[1]),
            "distance_m": float(r[2]) if r[2] is not None else 0.0,
            "climb_length_m": float(r[3]) if r[3] is not None else 0.0,
            "is_one_way": bool(r[4]),
        }
        for r in edge_rows
    ]

    # Resolve from_ref and to_ref by id or name
    from_id = name_to_id.get(from_ref) or (from_ref if from_ref in nodes else None)
    to_id = name_to_id.get(to_ref) or (to_ref if to_ref in nodes else None)

    if not from_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "FIELD-GRAPH-404-NODE",
                "message": f"Source node '{from_ref}' not found in site graph",
            },
        )
    if not to_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "FIELD-GRAPH-404-NODE",
                "message": f"Target node '{to_ref}' not found in site graph",
            },
        )

    return dijkstra_3d(nodes, edges, from_id, to_id)
