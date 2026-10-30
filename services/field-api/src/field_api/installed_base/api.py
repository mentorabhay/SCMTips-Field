"""Installed Base Read Model and API (Task T4.027 / FR4.065 / API4.18 / TC4.157).

Features:
- GET /v1/installed-base?serial=&site_id=
- Strictly requires at least one of 'serial' or 'site_id'; raises 400 FIELD-IB-400-FILTER.
- Filters across field.installed_base view under forced tenant RLS.
- Returns list of current installed equipment with functional location erp_ref and since timestamp.
- p95 latency target <= 80 ms (API4.18).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from field_api.db import DATABASE_URL
from field_api.deps import Principal, require_principal

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/installed-base", tags=["Installed Base"])



@router.get("", response_model=dict[str, Any])
async def get_installed_base(
    request: Request,
    serial: str | None = Query(None, description="Equipment serial number filter"),
    site_id: str | None = Query(None, description="Site UUID filter"),
    principal: Principal = Depends(require_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """GET /v1/installed-base: Query installed base by serial or site_id (API4.18)."""
    # Validate filter requirement: serial or site_id required
    if not serial and not site_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "FIELD-IB-400-FILTER",
                "message": "serial or site_id required",
            },
        )

    tenant_id = principal.tenant_id

    # Query field.installed_base view under tenant context
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            query = """
                SELECT
                    serial_no,
                    erp_equipment_no,
                    material,
                    equipment_class,
                    pinned_model_version,
                    site_id,
                    site_erp_ref,
                    site_name,
                    location_id,
                    sector_code,
                    level_height_m,
                    position_code,
                    erp_ref,
                    since
                FROM field.installed_base
                WHERE tenant_id = %s
            """
            params: list[Any] = [tenant_id]

            if serial:
                query += " AND serial_no = %s"
                params.append(serial)
            if site_id:
                query += " AND site_id = %s"
                params.append(site_id)

            query += " ORDER BY since DESC;"

            cur.execute(query, params)
            rows = cur.fetchall()

    items = []
    for r in rows:
        since_val = r[13]
        since_iso = (
            since_val.isoformat()
            if isinstance(since_val, datetime)
            else str(since_val)
            if since_val
            else None
        )

        items.append(
            {
                "serial_no": r[0],
                "erp_equipment_no": r[1] or "",
                "material": r[2],
                "equipment_class": r[3],
                "pinned_model_version": r[4],
                "site_id": str(r[5]) if r[5] else None,
                "site_erp_ref": r[6] or "",
                "site_name": r[7] or "",
                "location_id": str(r[8]) if r[8] else None,
                "sector_code": r[9],
                "level_height_m": float(r[10]) if r[10] is not None else None,
                "position_code": r[11],
                "erp_ref": r[12] or "",
                "since": since_iso,
            }
        )

    return {"items": items}
