"""Dijkstra Shortest-Path Wayfinding Engine (Task T3.047 / FR3.045 / PR3.09 / TC3.130).

Invariant PR3.09:
For all site graphs, start nodes, and target nodes:
The path returned by find_shortest_path(start, target) has total distance <= any other valid path,
and consists exclusively of existing directed edges in the graph.
"""

import heapq
from typing import Any


class DijkstraWayfinder:
    """Computes exact shortest path on warehouse site graphs."""

    @staticmethod
    def find_shortest_path(
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        start_node_id: str,
        target_node_id: str,
    ) -> dict[str, Any] | None:
        if start_node_id not in nodes or target_node_id not in nodes:
            return None

        if start_node_id == target_node_id:
            return {
                "path": [start_node_id],
                "total_distance_m": 0.0,
                "edges": [],
            }

        # Build adjacency list: node -> list of (neighbor, distance, edge_data)
        adj: dict[str, list[tuple[str, float, dict[str, Any]]]] = {nid: [] for nid in nodes}

        for edge in edges:
            u = edge.get("from_node_id") or edge.get("from")
            v = edge.get("to_node_id") or edge.get("to")
            dist = float(edge.get("distance_m") or edge.get("distance", 1.0))
            is_one_way = bool(edge.get("is_one_way", False))

            if u in adj and v in adj:
                adj[u].append((v, dist, edge))
                if not is_one_way:
                    adj[v].append((u, dist, edge))

        # Priority queue for Dijkstra: (distance, current_node, path, edges_traversed)
        pq: list[tuple[float, str, list[str], list[dict[str, Any]]]] = [
            (0.0, start_node_id, [start_node_id], [])
        ]
        visited_dists: dict[str, float] = {start_node_id: 0.0}

        while pq:
            cur_dist, u, path, traversed_edges = heapq.heappop(pq)

            if u == target_node_id:
                return {
                    "path": path,
                    "total_distance_m": cur_dist,
                    "edges": traversed_edges,
                }

            if cur_dist > visited_dists.get(u, float("inf")):
                continue

            for v, weight, edge_info in adj.get(u, []):
                new_dist = cur_dist + weight
                if new_dist < visited_dists.get(v, float("inf")):
                    visited_dists[v] = new_dist
                    heapq.heappush(
                        pq,
                        (new_dist, v, path + [v], traversed_edges + [edge_info]),
                    )

        return None  # Target unreachable
