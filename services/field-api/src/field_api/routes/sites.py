"""Physical Sites Management Endpoints (API1.05 / API1.06 / API1.07)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.db import get_conn
from field_api.deps import require_permission, require_principal
from field_api.errors import ERR_NOT_FOUND
from field_api.http.etag import generate_etag, verify_if_match
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params

router = APIRouter(prefix="/v1/sites", tags=["Sites"])


class SiteCreate(BaseModel):
    code: str = Field(
        ...,
        pattern=r"^[A-Z0-9-]{2,32}$",
        json_schema_extra={"example": "SAMPLE-WH-01"},
    )
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(..., description="warehouse, tower, plant, yard, other")
    erp_plant: str | None = Field(
        None, min_length=4, max_length=4, json_schema_extra={"example": "1010"}
    )
    erp_storage_locations: list[str] = Field(default_factory=list)
    timezone: str = "UTC"
    lat: float | None = None
    lon: float | None = None


class SiteUpdate(BaseModel):
    name: str | None = None
    erp_storage_locations: list[str] | None = None
    status: str | None = None


class SiteRecord(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    kind: str
    erp_plant: str | None
    erp_storage_locations: list[str]
    timezone: str
    lat: float | None
    lon: float | None
    status: str
    version: int
    created_at: str
    updated_at: str


# Seed standard SAMPLE site
_DEFAULT_SITES: list[dict[str, Any]] = [
    {
        "id": "018f0000-0000-7000-8000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "code": "SAMPLE-WH-01",
        "name": "Sample Distribution Center 01",
        "kind": "warehouse",
        "erp_plant": "1010",
        "erp_storage_locations": ["101A", "101Q"],
        "timezone": "UTC",
        "lat": 12.9716,
        "lon": 77.5946,
        "status": "active",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
]

SITES_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]](seed=_DEFAULT_SITES)


@router.get("", response_model=PaginatedResponse)
async def list_sites(
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.site.read")),
) -> PaginatedResponse:
    """List physical sites in tenant scope with cursor pagination."""
    last_id, limit = pagination
    all_sites = SITES_STORE.list(principal.tenant_id)

    # Site-scoping check
    if "*" not in principal.site_ids:
        all_sites = [
            s for s in all_sites if s["id"] in principal.site_ids or s["code"] in principal.site_ids
        ]

    # Keyset filtering
    if last_id:
        all_sites = [s for s in all_sites if s["id"] > last_id]

    page_items = all_sites[:limit]
    next_cursor = encode_cursor(page_items[-1]["id"]) if len(all_sites) > limit else None

    return PaginatedResponse(
        items=[SiteRecord.model_validate(s).model_dump() for s in page_items],
        next_cursor=next_cursor,
        total_in_page=len(page_items),
    )


@router.post("", response_model=SiteRecord, status_code=201)
async def create_site(
    site_in: SiteCreate,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> SiteRecord:
    """Create a new physical site."""
    site_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()
    record = {
        "id": site_id,
        "tenant_id": principal.tenant_id,
        **site_in.model_dump(),
        "status": "active",
        "version": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    SITES_STORE.insert(principal.tenant_id, site_id, record)
    response.headers["ETag"] = generate_etag(site_id, 1)
    return SiteRecord.model_validate(record)


@router.get("/{site_id}", response_model=SiteRecord)
async def get_site(
    site_id: str,
    principal: Principal = Depends(require_principal),
) -> SiteRecord:
    """Retrieve details for a single site."""
    if "*" not in principal.site_ids and site_id not in principal.site_ids:
        raise ERR_NOT_FOUND

    site = SITES_STORE.get(principal.tenant_id, site_id)
    if not site:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true);", (principal.tenant_id,))
                cur.execute(
                    "SELECT set_config('app.current_tenant_id', %s, true);", (principal.tenant_id,)
                )
                cur.execute("SELECT set_config('app.site_ids', '*', true);")
                cur.execute(
                    """
                    SELECT id, code, name, kind, status, lat, lon, created_at, updated_at
                    FROM field.site
                    WHERE tenant_id = %s AND (id::text = %s OR code = %s);
                    """,
                    (principal.tenant_id, site_id, site_id),
                )
                row = cur.fetchone()
                if row:
                    site = {
                        "id": str(row[0]),
                        "tenant_id": principal.tenant_id,
                        "code": row[1],
                        "name": row[2],
                        "kind": row[3],
                        "status": row[4],
                        "lat": float(row[5]) if row[5] is not None else 0.0,
                        "lon": float(row[6]) if row[6] is not None else 0.0,
                        "erp_plant": "1010",
                        "erp_storage_locations": [],
                        "timezone": "UTC",
                        "version": 1,
                        "created_at": row[7].isoformat()
                        if row[7]
                        else datetime.now(UTC).isoformat(),
                        "updated_at": row[8].isoformat()
                        if row[8]
                        else datetime.now(UTC).isoformat(),
                    }
    if not site:
        raise ERR_NOT_FOUND
    return SiteRecord.model_validate(site)


@router.patch("/{site_id}", response_model=SiteRecord)
async def update_site(
    site_id: str,
    update_in: SiteUpdate,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> SiteRecord:
    """Update physical site metadata (requires If-Match tag)."""
    site = SITES_STORE.get(principal.tenant_id, site_id)
    if not site:
        raise ERR_NOT_FOUND

    # Validate If-Match
    verify_if_match(request, int(site["version"]), site_id)

    # Increment version
    site["version"] = int(site["version"]) + 1
    site["updated_at"] = datetime.now(UTC).isoformat()
    for k, v in update_in.model_dump(exclude_unset=True).items():
        site[k] = v

    SITES_STORE.update(principal.tenant_id, site_id, site)
    response.headers["ETag"] = generate_etag(site_id, int(site["version"]))
    return SiteRecord.model_validate(site)
