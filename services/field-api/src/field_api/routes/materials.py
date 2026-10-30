"""Cached ERP material master search (API1.10) on Postgres with RLS (C4; was an in-process store).

Rows are written by the worker's material sync (field_worker.material_sync); deleted-in-ERP rows
are excluded.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params
from field_api.rows import fetch_dicts

router = APIRouter(prefix="/v1/materials", tags=["Materials"])


class MaterialRecord(BaseModel):
    id: str
    tenant_id: str
    erp_material_no: str
    plant: str
    description: str
    base_uom: str
    batch_managed: bool
    serial_profile: str | None
    gtin: str | None
    status: str
    version: int
    created_at: str
    updated_at: str


@router.get("", response_model=PaginatedResponse)
async def search_materials(
    plant: str | None = Query(None, description="Plant filter e.g. 1010"),
    q: str | None = Query(None, max_length=64, description="Material number or description contains"),
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.material.read")),
) -> PaginatedResponse:
    last_id, limit = pagination
    like = f"%{q.replace('%', r'\%').replace('_', r'\_')}%" if q else None
    with principal_tx(principal) as cur:
        cur.execute(
            """
            SELECT id, tenant_id, erp_material_no, plant, description, base_uom, batch_managed, serial_profile,
                   gtin, status, version, created_at, updated_at
              FROM field.material
             WHERE deleted_in_erp_at IS NULL
               AND (%s::text IS NULL OR plant = %s)
               AND (%s::text IS NULL OR erp_material_no ILIKE %s OR description ILIKE %s)
               AND (%s::uuid IS NULL OR id > %s::uuid)
             ORDER BY id LIMIT %s
            """,
            (plant, plant, like, like, like, last_id, last_id, limit + 1),
        )
        rows = fetch_dicts(cur)
    page = rows[:limit]
    return PaginatedResponse(
        items=[MaterialRecord.model_validate({**r, "status": r.get("status") or "active"}).model_dump() for r in page],
        next_cursor=encode_cursor(page[-1]["id"]) if len(rows) > limit and page else None,
        total_in_page=len(page),
    )
