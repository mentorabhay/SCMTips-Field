"""Location Hierarchy Endpoints with Tree Validation (API1.08 / API1.09 / PR1.20)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_permission, require_principal
from field_api.errors import (
    ERR_LOCATION_CYCLE,
    ERR_LOCATION_DEPTH,
    ERR_NOT_FOUND,
)
from field_api.http.etag import generate_etag, verify_if_match
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params

router = APIRouter(prefix="/v1/locations", tags=["Locations"])

ALLOWED_KINDS = {
    "zone",
    "aisle",
    "rack",
    "level",
    "position",
    "tower",
    "sector",
}


class LocationCreate(BaseModel):
    site_id: str
    parent_id: str | None = None
    kind: str = Field(..., description="zone, aisle, rack, level, position, tower, sector")
    code: str = Field(..., pattern=r"^[A-Z0-9-]{1,24}$")
    erp_ref: str | None = None
    erp_ref_type: str | None = None


class LocationUpdate(BaseModel):
    code: str | None = None
    parent_id: str | None = None
    status: str | None = None


class LocationRecord(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    parent_id: str | None
    kind: str
    code: str
    path: str
    depth: int
    erp_ref: str | None
    erp_ref_type: str | None
    status: str
    version: int
    created_at: str
    updated_at: str


LOCATIONS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()


def _build_path_and_depth(
    tenant_id: str, site_id: str, parent_id: str | None, code: str
) -> tuple[str, int]:
    """Compute location path and tree depth, checking depth <= 6."""
    if not parent_id:
        return code, 1

    parent = LOCATIONS_STORE.get(tenant_id, parent_id)
    if not parent:
        raise ERR_NOT_FOUND

    depth = int(parent["depth"]) + 1
    if depth > 6:
        raise ERR_LOCATION_DEPTH

    path = f"{parent['path']}/{code}"
    return path, depth


def _detect_cycle(tenant_id: str, location_id: str, new_parent_id: str | None) -> None:
    """Ensure moving location_id under new_parent_id does not form a cycle."""
    if not new_parent_id:
        return
    curr: str | None = new_parent_id
    visited: set[str] = set()
    while curr:
        if curr == location_id:
            raise ERR_LOCATION_CYCLE
        if curr in visited:
            break
        visited.add(curr)
        parent_loc = LOCATIONS_STORE.get(tenant_id, curr)
        curr = (
            str(parent_loc.get("parent_id"))
            if (parent_loc and parent_loc.get("parent_id"))
            else None
        )


@router.get("", response_model=PaginatedResponse)
async def list_locations(
    site_id: str | None = Query(None),
    parent_id: str | None = Query(None),
    kind: str | None = Query(None),
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.location.read")),
) -> PaginatedResponse:
    """List locations with filtering and cursor pagination."""
    last_id, limit = pagination
    all_locs = LOCATIONS_STORE.list(principal.tenant_id)

    if site_id:
        all_locs = [item for item in all_locs if item["site_id"] == site_id]
    if parent_id:
        all_locs = [item for item in all_locs if item["parent_id"] == parent_id]
    if kind:
        all_locs = [item for item in all_locs if item["kind"] == kind]

    if last_id:
        all_locs = [item for item in all_locs if item["id"] > last_id]

    page_items = all_locs[:limit]
    next_cursor = encode_cursor(page_items[-1]["id"]) if len(all_locs) > limit else None

    return PaginatedResponse(
        items=[LocationRecord.model_validate(item).model_dump() for item in page_items],
        next_cursor=next_cursor,
        total_in_page=len(page_items),
    )


@router.post("", response_model=LocationRecord, status_code=201)
async def create_location(
    loc_in: LocationCreate,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> LocationRecord:
    """Create a new hierarchical location."""
    path, depth = _build_path_and_depth(
        principal.tenant_id, loc_in.site_id, loc_in.parent_id, loc_in.code
    )
    loc_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()

    record: dict[str, Any] = {
        "id": loc_id,
        "tenant_id": principal.tenant_id,
        "site_id": loc_in.site_id,
        "parent_id": loc_in.parent_id,
        "kind": loc_in.kind,
        "code": loc_in.code,
        "path": path,
        "depth": depth,
        "erp_ref": loc_in.erp_ref,
        "erp_ref_type": loc_in.erp_ref_type,
        "status": "active",
        "version": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    LOCATIONS_STORE.insert(principal.tenant_id, loc_id, record)
    response.headers["ETag"] = generate_etag(loc_id, 1)
    return LocationRecord.model_validate(record)


@router.patch("/{loc_id}", response_model=LocationRecord)
async def update_location(
    loc_id: str,
    update_in: LocationUpdate,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> LocationRecord:
    """Move or rename a location (validates cycles & depth, requires If-Match)."""
    loc = LOCATIONS_STORE.get(principal.tenant_id, loc_id)
    if not loc:
        raise ERR_NOT_FOUND

    verify_if_match(request, int(loc["version"]), loc_id)

    new_parent_id = update_in.parent_id if update_in.parent_id is not None else loc["parent_id"]
    new_code = update_in.code if update_in.code is not None else loc["code"]

    if new_parent_id != loc["parent_id"]:
        _detect_cycle(principal.tenant_id, loc_id, new_parent_id)

    path, depth = _build_path_and_depth(
        principal.tenant_id, str(loc["site_id"]), new_parent_id, str(new_code)
    )

    loc["version"] = int(loc["version"]) + 1
    loc["parent_id"] = new_parent_id
    loc["code"] = new_code
    loc["path"] = path
    loc["depth"] = depth
    loc["updated_at"] = datetime.now(UTC).isoformat()
    if update_in.status:
        loc["status"] = update_in.status

    LOCATIONS_STORE.update(principal.tenant_id, loc_id, loc)
    response.headers["ETag"] = generate_etag(loc_id, int(loc["version"]))
    return LocationRecord.model_validate(loc)
