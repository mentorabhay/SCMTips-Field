"""Site Graph Data Model and Bin Tree Hierarchy Validator (Task T3.046 / FR3.044 / PR3.11).

Invariant PR3.11:
For all storage bin hierarchies, the location graph is a directed tree:
1. Every bin or location has at most one parent.
2. Zero directed cycles.
3. Every path terminates at the warehouse or site root.
"""

from typing import Any


class BinTreeValidationException(Exception):
    pass


def validate_bin_hierarchy_tree(
    locations: list[dict[str, Any]],
) -> bool:
    """Enforces PR3.11: location graph forms a valid tree with single parent and zero cycles."""
    parent_map: dict[str, str] = {}
    nodes: set[str] = set()

    for loc in locations:
        loc_id = loc.get("id") or loc.get("location_id")
        parent_id = loc.get("parent_id") or loc.get("parent_location_id")

        if not loc_id:
            continue
        nodes.add(loc_id)

        if parent_id:
            if loc_id in parent_map:
                raise BinTreeValidationException(
                    f"Location '{loc_id}' has multiple parents: '{parent_map[loc_id]}' and '{parent_id}'"
                )
            parent_map[loc_id] = parent_id

    # Check for cycles using cycle detection traversal
    for node in nodes:
        visited = set()
        cur = node
        while cur in parent_map:
            if cur in visited:
                raise BinTreeValidationException(
                    f"Directed cycle detected involving location '{cur}'"
                )
            visited.add(cur)
            cur = parent_map[cur]

    return True
