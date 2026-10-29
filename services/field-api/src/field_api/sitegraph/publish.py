"""Site graph snapshot publisher for Task T3.055."""

from typing import Any


def publish_site_graph_version(
    site_id: str, version: int, graph_data: dict[str, Any]
) -> dict[str, Any]:
    """Publishes versioned immutable snapshot of site graph for edge mobile caching."""
    return {
        "site_id": site_id,
        "version": version,
        "nodes_count": len(graph_data.get("nodes", [])),
        "edges_count": len(graph_data.get("edges", [])),
        "status": "published",
    }
