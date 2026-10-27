"""Newcomer Guidance Generator (Task T4.052 / FR4.048 / TC4.143).

Produces concise, site-specific safety and navigation instructions from computed 3D routes.
Pre-climb briefing spoken before technician commences vertical climb.
"""

from __future__ import annotations

import re
from typing import Any


def generate_newcomer_guidance(
    nodes: list[dict[str, Any]],
    climb_m: float,
    walk_m: float,
) -> str:
    """Produce newcomer guidance string from 3D route (FR4.048 / TC4.143).

    Example output:
    'Climb 40 m to Level 3 platform. Clip in at every rest platform.'
    """
    if not nodes:
        return "Proceed to destination."

    target_node = nodes[-1]
    target_name = target_node.get("name", "destination")

    if climb_m > 0:
        # Determine target platform label
        target_level = None
        m = re.search(r"L(?:evel\s*)?(\d+)", target_name, re.IGNORECASE)
        if m:
            target_level = f"Level {m.group(1)} platform"
        elif target_node.get("subkind") in ("rest_platform", "sector_platform"):
            sub_title = target_node.get("subkind", "").replace("_", " ").title()
            target_level = f"{sub_title}"
        else:
            target_level = f"{target_name} platform"

        climb_str = f"{int(round(climb_m))} m"
        return f"Climb {climb_str} to {target_level}. Clip in at every rest platform."
    else:
        return f"Walk {walk_m:.1f} m to {target_name}."
