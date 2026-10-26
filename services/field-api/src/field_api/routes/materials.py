"""Cached ERP Material Master Search Endpoints (API1.10)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_permission
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params

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


_DEFAULT_MATERIALS: list[dict[str, Any]] = [
    {
        "id": "018f0000-0000-7000-8000-000000000101",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "erp_material_no": "SAMPLE-MAT-0001",
        "plant": "1010",
        "description": "5G Remote Radio Unit RRU 32T32R",
        "base_uom": "EA",
        "batch_managed": False,
        "serial_profile": "SER-5G",
        "gtin": "00012345678905",
        "status": "active",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    },
    {
        "id": "018f0000-0000-7000-8000-000000000102",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "erp_material_no": "SAMPLE-MAT-0002",
        "plant": "1010",
        "description": "Baseband Unit BBU Subrack Chassis",
        "base_uom": "EA",
        "batch_managed": False,
        "serial_profile": "SER-5G",
        "gtin": "00012345678912",
        "status": "active",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    },
]

MATERIALS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]](
    seed=_DEFAULT_MATERIALS
)


@router.get("", response_model=PaginatedResponse)
async def search_materials(
    plant: str | None = Query(None, description="Plant filter e.g. 1010"),
    q: str | None = Query(None, description="Search term for material no or description"),
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.material.read")),
) -> PaginatedResponse:
    """Search cached materials by plant, number or description with cursor pagination."""
    last_id, limit = pagination
    all_mats = MATERIALS_STORE.list(principal.tenant_id)

    if plant:
        all_mats = [m for m in all_mats if m["plant"] == plant]
    if q:
        query_lower = q.lower()
        all_mats = [
            m
            for m in all_mats
            if query_lower in str(m["erp_material_no"]).lower()
            or query_lower in str(m["description"]).lower()
        ]

    if last_id:
        all_mats = [m for m in all_mats if m["id"] > last_id]

    page_items = all_mats[:limit]
    next_cursor = encode_cursor(page_items[-1]["id"]) if len(all_mats) > limit else None

    return PaginatedResponse(
        items=[MaterialRecord.model_validate(m).model_dump() for m in page_items],
        next_cursor=next_cursor,
        total_in_page=len(page_items),
    )
