"""Wayfinding user trail tracking for Task T3.054."""

from typing import Any


def record_wayfinding_trail(
    user_id: str,
    path_nodes: list[str],
    completed: bool = True,
) -> dict[str, Any]:
    """Records executed pedestrian wayfinding trail for analytics."""
    return {
        "user_id": user_id,
        "nodes": path_nodes,
        "completed": completed,
    }
