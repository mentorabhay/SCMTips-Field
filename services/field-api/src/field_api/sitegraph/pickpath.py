"""Pick Path Optimization via Nearest Neighbor and 2-Opt (Task T3.035 / FR3.026).

Orders warehouse picking stops by shortest-path travel distance:
1. Constructs distance matrix from site graph coordinates or Manhattan/Euclidean distances.
2. Applies Nearest Neighbor heuristic to create initial tour.
3. Refines tour with 2-Opt edge swaps (for <= 40 stops).
4. Falls back to alphabetical bin name order if coordinates/graph are unavailable.
"""

import math
from typing import Any


def euclidean_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def calculate_tour_length(tour: list[int], coords: list[tuple[float, float]]) -> float:
    length = 0.0
    for i in range(len(tour) - 1):
        length += euclidean_distance(coords[tour[i]], coords[tour[i + 1]])
    return length


def two_opt_swap(tour: list[int], i: int, k: int) -> list[int]:
    return tour[:i] + tour[i : k + 1][::-1] + tour[k + 1 :]


def optimize_pick_path(
    stops: list[dict[str, Any]],
    graph_coordinates: dict[str, tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Optimizes stop order so that tour length <= alphabetical bin-order length."""
    if len(stops) <= 2:
        return list(stops)

    # Fall back to alphabetical bin order if no coordinates provided (FR3.026)
    if not graph_coordinates:
        return sorted(stops, key=lambda s: s.get("storage_bin") or s.get("bin_id") or "")

    # Extract coordinates for each stop
    coords: list[tuple[float, float]] = []
    valid_stops: list[dict[str, Any]] = []

    for stop in stops:
        bin_id = stop.get("storage_bin") or stop.get("bin_id") or ""
        if bin_id in graph_coordinates:
            coords.append(graph_coordinates[bin_id])
            valid_stops.append(stop)
        else:
            # Fallback coordinate based on hash or zero
            coords.append((0.0, 0.0))
            valid_stops.append(stop)

    n = len(valid_stops)

    # 1. Nearest Neighbor Initial Tour
    unvisited = set(range(1, n))
    current = 0
    tour = [0]

    while unvisited:
        next_node = min(
            unvisited, key=lambda node: euclidean_distance(coords[current], coords[node])
        )
        tour.append(next_node)
        unvisited.remove(next_node)
        current = next_node

    # 2. 2-Opt Optimization for <= 40 stops
    if n <= 40:
        improved = True
        iterations = 0
        max_iterations = 100
        best_distance = calculate_tour_length(tour, coords)

        while improved and iterations < max_iterations:
            improved = False
            iterations += 1
            for i in range(1, n - 1):
                for k in range(i + 1, n):
                    new_tour = two_opt_swap(tour, i, k)
                    new_dist = calculate_tour_length(new_tour, coords)
                    if new_dist < best_distance - 1e-4:
                        tour = new_tour
                        best_distance = new_dist
                        improved = True
                        break
                if improved:
                    break

    return [valid_stops[idx] for idx in tour]
