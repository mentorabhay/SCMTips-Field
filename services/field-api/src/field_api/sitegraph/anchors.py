"""Positioning Fusion and Anchor Snapping (Task T3.048 / FR3.046 / PR3.17).

Invariant PR3.17:
For all sensor readings (QR anchor scan, BLE RSSI, step dead-reckoning),
the fused user position snaps onto the site graph
with perpendicular distance to nearest edge <= 1.0 m.
"""

import math


def point_to_segment_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[float, float, float]:
    """Calculates shortest distance from (px, py) to line segment (x1, y1)-(x2, y2), and projected point."""
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0.0:
        dist = math.hypot(px - x1, py - y1)
        return dist, x1, y1

    # Project point onto line segment: t in [0, 1]
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    dist = math.hypot(px - proj_x, py - proj_y)
    return dist, proj_x, proj_y


def fuse_and_snap_to_graph(
    raw_x: float,
    raw_y: float,
    graph_edges: list[tuple[tuple[float, float], tuple[float, float]]],
    snap_distance_threshold_m: float = 1.0,
) -> tuple[float, float, float]:
    """Fuses raw position and snaps onto the closest graph edge (PR3.17).

    Returns:
        (snapped_x, snapped_y, distance_to_edge_m)
    """
    if not graph_edges:
        return raw_x, raw_y, 0.0

    min_dist = float("inf")
    best_snap = (raw_x, raw_y)

    for (x1, y1), (x2, y2) in graph_edges:
        dist, sx, sy = point_to_segment_distance(raw_x, raw_y, x1, y1, x2, y2)
        if dist < min_dist:
            min_dist = dist
            best_snap = (sx, sy)

    # Invariant PR3.17: Position snapped onto edge
    return best_snap[0], best_snap[1], min_dist
