"""Equipment Trail API (Task T4.053 / FR4.049 / PR4.06 / API4.10 / TC4.132).

Provides:
- GET /v1/equipment/{serial}/trail
Retrieves chronological trail of locations for a serial number, ordered by occurred_at ASC with ties broken by seq ASC.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
import structlog

from field_api.db import get_conn
from field_api.deps import Principal, require_principal

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Equipment Trails"])


class TrailPoint(BaseModel):
    seq: int = Field(..., description="Monotonic event sequence number")
    type: str = Field(..., description="Event type: issue, install, dismantle, move, etc.")
    label: str = Field(..., description="Human-readable location label (e.g. Plant 1100 / SL 0001 or IN01-TWR-0042 T01 Sector A L3 P02)")
    at: str = Field(..., description="ISO 8601 occurred_at timestamp")
    location_id: Optional[str] = Field(None, description="Location UUID if bound to a structure location")
    altitude_m: Optional[float] = Field(None, description="Height in meters if available")


class EquipmentTrailResponse(BaseModel):
    serial: str = Field(..., description="Equipment serial number")
    points: list[TrailPoint] = Field(..., description="Chronological trail points")


def get_equipment_trail(tenant_id: str, serial_no: str) -> dict[str, Any]:
    """Retrieve ordered equipment trail points (API4.10 / PR4.06)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Verify equipment exists
            cur.execute(
                """
                SELECT id, serial_no, material, status
                FROM field.equipment
                WHERE tenant_id = %s AND serial_no = %s;
                """,
                (tenant_id, serial_no),
            )
            eq_row = cur.fetchone()
            if not eq_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error_code": "FIELD-EQP-404-SERIAL", "message": f"Equipment with serial '{serial_no}' not found"},
                )

            eq_id = eq_row[0]

            # 2. Query serial_events ordered by occurred_at ASC, seq ASC (PR4.06)
            cur.execute(
                """
                SELECT se.seq, se.type, se.occurred_at, se.source_plant, se.source_storage_location,
                       se.to_location_id, se.from_location_id,
                       tl.fl_code as to_fl, tl.path as to_path, tl.height_m as to_height,
                       fl.fl_code as from_fl, fl.path as from_path,
                       ts.code as to_site_code, fs.code as from_site_code
                FROM field.serial_event se
                LEFT JOIN field.location tl ON se.to_location_id = tl.id
                LEFT JOIN field.site ts ON tl.site_id = ts.id
                LEFT JOIN field.location fl ON se.from_location_id = fl.id
                LEFT JOIN field.site fs ON fl.site_id = fs.id
                WHERE se.tenant_id = %s AND se.equipment_id = %s
                ORDER BY se.occurred_at ASC, se.seq ASC;
                """,
                (tenant_id, eq_id),
            )
            event_rows = cur.fetchall()

    points: list[TrailPoint] = []
    seen_seqs = set()

    for r in event_rows:
        seq = r[0]
        ev_type = r[1]
        occurred_at = r[2]
        s_plant = r[3]
        s_sloc = r[4]
        to_loc_id = str(r[5]) if r[5] else None
        from_loc_id = str(r[6]) if r[6] else None
        to_fl = r[7]
        to_path = r[8]
        to_height = float(r[9]) if r[9] is not None else None
        from_fl = r[10]
        from_path = r[11]
        to_site = r[12]
        from_site = r[13]

        # Format label based on event context
        label = "Unknown Location"
        loc_id = to_loc_id or from_loc_id
        alt_m = to_height

        if ev_type == "issue" and s_plant and s_sloc:
            label = f"Plant {s_plant} / SL {s_sloc}"
        elif s_plant and s_sloc and not to_fl:
            label = f"Plant {s_plant} / SL {s_sloc}"
        elif to_fl:
            # E.g. "IN01-TWR-0042 T01 Sector A L3 P02" or fl_code
            formatted_site = f"{to_site} " if to_site and not to_fl.startswith(to_site) else ""
            label = f"{formatted_site}{to_fl}".strip()
        elif from_fl:
            formatted_site = f"{from_site} " if from_site and not from_fl.startswith(from_site) else ""
            label = f"{formatted_site}{from_fl}".strip()
        elif s_plant:
            label = f"Plant {s_plant}"

        ts_str = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at)

        points.append(
            TrailPoint(
                seq=seq,
                type=ev_type,
                label=label,
                at=ts_str,
                location_id=loc_id,
                altitude_m=alt_m,
            )
        )
        seen_seqs.add(seq)

    return {
        "serial": serial_no,
        "points": [p.model_dump() for p in points],
    }


@router.get(
    "/v1/equipment/{serial}/trail",
    response_model=EquipmentTrailResponse,
    summary="Ordered trail of locations for a serial (API4.10)",
    status_code=status.HTTP_200_OK,
)
def api_get_equipment_trail(
    serial: str,
    principal: Principal = Depends(require_principal),
) -> EquipmentTrailResponse:
    """Retrieve ordered equipment trail points (API4.10 / FR4.049 / PR4.06)."""
    data = get_equipment_trail(tenant_id=principal.tenant_id, serial_no=serial)
    return EquipmentTrailResponse(**data)
