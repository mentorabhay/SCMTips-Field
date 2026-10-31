"""Sites (API1.05 / API1.06 / API1.07) on Postgres with RLS (C4; was an in-process store).

Also fixes authorization: create/patch required only a login; the spec requires field.site.edit.

M3: every site has a ``mode``, production (default) or sandbox (home / training: unknown boxes may become
materials, see field_api/sandbox). Only field.admin sets or changes it (field.site.edit alone is not
enough), and every change is audited in field.outbox as ``site.mode_changed``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.http.etag import generate_etag, verify_if_match
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params
from field_api.rows import fetch_dict, fetch_dicts

router = APIRouter(prefix="/v1/sites", tags=["Sites"])

COLS = ("id, tenant_id, code, name, kind, erp_plant, erp_storage_locations, timezone, lat, lon, status, "
        "version, created_at, updated_at, geofence_radius_m, mode")
ERR_SITE_NOT_FOUND = FieldError(code="FIELD-SITE-404-NOT-FOUND", status=404, title="Site not found")
ERR_SITE_CODE_EXISTS = FieldError(code="FIELD-SITE-409-CODE-EXISTS", status=409, title="Site code taken")
ERR_MODE_ADMIN = FieldError(code="FIELD-AUTH-403-PERMISSION", status=403, title="Only an administrator sets the site mode",
                            detail="production / sandbox is changed by field.admin only")
SiteMode = Literal["production", "sandbox"]


class SiteCreate(BaseModel):
    code: str = Field(..., pattern=r"^[A-Z0-9-]{2,32}$", json_schema_extra={"example": "SAMPLE-WH-01"})
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(..., pattern=r"^(warehouse|tower|plant|yard|other)$")
    erp_plant: str | None = Field(None, min_length=4, max_length=4, json_schema_extra={"example": "1010"})
    erp_storage_locations: list[str] = Field(default_factory=list)
    timezone: str = "UTC"
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(None, ge=10, le=5000)
    mode: SiteMode = "production"


class SiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    erp_storage_locations: list[str] | None = None
    status: str | None = Field(None, pattern=r"^(active|inactive)$")
    timezone: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(None, ge=10, le=5000)
    mode: SiteMode | None = None


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
    geofence_radius_m: int | None = None
    mode: str = "production"


def _require_admin(principal: Principal) -> None:
    if not has_permission(principal.permissions, "field.*"):
        raise ERR_MODE_ADMIN


def _audit_mode(cur: Any, principal: Principal, site_id: str, old: str | None, new: str) -> None:
    cur.execute(
        "INSERT INTO field.outbox (tenant_id, event_type, aggregate_id, payload) VALUES (%s, 'site.mode_changed', %s, %s)",
        (principal.tenant_id, site_id, json.dumps({"site_id": site_id, "from": old, "to": new, "by": principal.id})),
    )


def _norm(row: dict[str, Any]) -> dict[str, Any]:
    row["erp_storage_locations"] = row.get("erp_storage_locations") or []
    row["timezone"] = row.get("timezone") or "UTC"
    return row


@router.get("", response_model=PaginatedResponse)
async def list_sites(
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.site.read")),
) -> PaginatedResponse:
    last_id, limit = pagination
    with principal_tx(principal) as cur:
        cur.execute(
            f"SELECT {COLS} FROM field.site WHERE (%s::uuid IS NULL OR id > %s::uuid) ORDER BY id LIMIT %s",  # noqa: S608
            (last_id, last_id, limit + 1),
        )
        rows = [_norm(r) for r in fetch_dicts(cur)]
    page = rows[:limit]
    return PaginatedResponse(
        items=[SiteRecord.model_validate(r).model_dump() for r in page],
        next_cursor=encode_cursor(page[-1]["id"]) if len(rows) > limit and page else None,
        total_in_page=len(page),
    )


@router.post("", response_model=SiteRecord, status_code=201)
async def create_site(
    site_in: SiteCreate,
    response: Response,
    principal: Principal = Depends(require_permission("field.site.edit")),
) -> SiteRecord:
    if site_in.mode != "production":
        _require_admin(principal)
    try:
        with principal_tx(principal) as cur:
            cur.execute(
                f"""
                INSERT INTO field.site (tenant_id, code, name, kind, erp_plant, erp_storage_locations, timezone,
                       lat, lon, geofence_radius_m, status, mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, 150), 'active', %s)
                RETURNING {COLS}
                """,  # noqa: S608
                (principal.tenant_id, site_in.code, site_in.name, site_in.kind, site_in.erp_plant,
                 site_in.erp_storage_locations, site_in.timezone, site_in.lat, site_in.lon, site_in.geofence_radius_m,
                 site_in.mode),
            )
            row = _norm(fetch_dict(cur) or {})
            if site_in.mode != "production":
                _audit_mode(cur, principal, str(row["id"]), None, site_in.mode)
    except psycopg.errors.UniqueViolation as e:
        raise ERR_SITE_CODE_EXISTS from e
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    response.headers["Location"] = f"/v1/sites/{row['id']}"
    return SiteRecord.model_validate(row)


def _get(cur: Any, site_id: str) -> dict[str, Any]:
    cur.execute(
        f"SELECT {COLS} FROM field.site WHERE id::text = %s OR code = %s",  # noqa: S608
        (site_id, site_id),
    )
    row = fetch_dict(cur)
    if not row:
        raise ERR_SITE_NOT_FOUND
    return _norm(row)


@router.get("/{site_id}", response_model=SiteRecord)
async def get_site(
    site_id: str,
    response: Response,
    principal: Principal = Depends(require_permission("field.site.read")),
) -> SiteRecord:
    with principal_tx(principal) as cur:  # RLS site_scope hides out-of-scope sites -> 404
        row = _get(cur, site_id)
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    return SiteRecord.model_validate(row)


@router.patch("/{site_id}", response_model=SiteRecord)
async def update_site(
    site_id: str,
    update_in: SiteUpdate,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission("field.site.edit")),
) -> SiteRecord:
    changes = update_in.model_dump(exclude_unset=True)
    if "mode" in changes:
        if changes["mode"] is None:
            changes.pop("mode")
        else:
            _require_admin(principal)
    with principal_tx(principal) as cur:
        current = _get(cur, site_id)
        verify_if_match(request, int(current["version"]), current["id"])
        if "mode" in changes and changes["mode"] != current.get("mode"):
            _audit_mode(cur, principal, str(current["id"]), current.get("mode"), changes["mode"])
        sets = ", ".join(f"{k} = %s" for k in changes)
        cur.execute(
            f"UPDATE field.site SET {sets}{', ' if sets else ''}version = version + 1, updated_at = NOW()"  # noqa: S608
            f" WHERE id = %s::uuid AND version = %s RETURNING {COLS}",
            (*changes.values(), current["id"], current["version"]),
        )
        row = fetch_dict(cur)
        if not row:  # concurrent update between read and write
            verify_if_match(request, int(current["version"]) + 1, current["id"])
            raise ERR_SITE_NOT_FOUND
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    return SiteRecord.model_validate(_norm(row))
