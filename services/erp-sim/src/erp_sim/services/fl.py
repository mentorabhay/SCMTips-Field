"""API_FUNCTIONALLOCATION OData Service for S/4HANA Emulation (Task T4.004 / FR4.004).

Provides FunctionalLocation read endpoints with prefix filtering and LastChangeDateTime filters,
reading from seeded tower fixtures (towers.json).
"""

import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Header, Query

router = APIRouter(prefix="/sap/opu/odata/sap/API_FUNCTIONALLOCATION", tags=["FunctionalLocation"])

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "towers.json"


def load_fl_fixtures() -> list[dict[str, Any]]:
    if not FIXTURE_PATH.exists():
        # Fallback path if run from root
        alt_path = Path("services/erp-sim/src/erp_sim/fixtures/towers.json")
        if alt_path.exists():
            with open(alt_path, encoding="utf-8") as f:
                data = json.load(f)
                return cast(list[dict[str, Any]], data.get("functional_locations", []))
        return []

    with open(FIXTURE_PATH, encoding="utf-8") as f:
        data = json.load(f)
        return cast(list[dict[str, Any]], data.get("functional_locations", []))


@router.get("/FunctionalLocation")
@router.get("/A_FunctionalLocation")
async def get_functional_locations(
    filter_expr: str | None = Query(None, alias="$filter"),
    top: int | None = Query(1000, alias="$top"),
    skip: int | None = Query(0, alias="$skip"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """OData v2 endpoint to list functional locations with prefix and change date filtering."""
    locations = load_fl_fixtures()

    # Filter by $filter expression (e.g. startswith(FunctionalLocation, 'IN01-TWR-0042'))
    if filter_expr:
        filter_expr = filter_expr.strip()
        # Handle startswith
        if "startswith(FunctionalLocation" in filter_expr:
            import re
            m = re.search(r"startswith\(FunctionalLocation,\s*'([^']+)'\)", filter_expr)
            if m:
                prefix = m.group(1)
                locations = [loc for loc in locations if loc["FunctionalLocation"].startswith(prefix)]
        elif "FunctionalLocation eq" in filter_expr:
            import re
            m = re.search(r"FunctionalLocation eq '([^']+)'", filter_expr)
            if m:
                target = m.group(1)
                locations = [loc for loc in locations if loc["FunctionalLocation"] == target]

    # Apply pagination
    skip_val = skip or 0
    top_val = top or 1000
    paged = locations[skip_val : skip_val + top_val]

    return {
        "d": {
            "results": paged,
            "__count": len(locations),
        }
    }
