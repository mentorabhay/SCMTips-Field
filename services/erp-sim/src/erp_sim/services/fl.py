"""API_FUNCTIONALLOCATION OData Service for S/4HANA Emulation (Task T4.004 / FR4.004).

Provides FunctionalLocation read endpoints with prefix filtering and LastChangeDateTime filters,
reading from seeded tower fixtures (towers.json).
"""

import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Header, Query

from erp_sim.db import get_conn

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
    """OData v2 endpoint to list functional locations with prefix and change date filtering.

    Serves the JSON fixtures plus every location in erpsim.functional_location (the database wins
    for the same FunctionalLocation), so towers created for a test read back as a tree.
    """
    by_fl = {loc["FunctionalLocation"]: loc for loc in load_fl_fixtures()}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT func_loc, description, superior_func_loc, kind, sector_code, height_m, plant, last_change_date_time"
            " FROM erpsim.functional_location WHERE client = %s ORDER BY func_loc",
            (sap_client,),
        )
        for r in cur.fetchall():
            by_fl[r[0]] = {
                "FunctionalLocation": r[0], "FunctionalLocationName": r[1], "SuperiorFunctionalLocation": r[2] or "",
                "Kind": r[3], "SectorCode": r[4], "HeightM": float(r[5]) if r[5] is not None else None,
                "MaintenancePlant": r[6] or "", "LastChangeDateTime": r[7].isoformat() if r[7] else None,
            }
    locations = list(by_fl.values())

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
