"""Location hierarchy (API1.08 / API1.09 / PR1.20) on Postgres with RLS (C4; was in-process).

Depth <= 6 (spec), cycles refused, parent must be in the same site, and a move rewrites the path
and depth of every descendant (previously descendants kept stale paths).
"""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import ERR_LOCATION_CYCLE, ERR_LOCATION_DEPTH, FieldError
from field_api.http.etag import generate_etag, verify_if_match
from field_api.http.pagination import PaginatedResponse, encode_cursor, get_page_params
from field_api.rows import fetch_dict, fetch_dicts

router = APIRouter(prefix="/v1/locations", tags=["Locations"])

MAX_DEPTH = 6
ALLOWED_KINDS = frozenset({"zone", "aisle", "rack", "level", "position", "tower", "sector",
                           "tower_site", "shelter", "rack_slot"})
COLS = ("id, tenant_id, site_id, parent_id, kind, code, path, depth, erp_ref, erp_ref_type, status, version, "
        "created_at, updated_at")
ERR_LOC_NOT_FOUND = FieldError(code="FIELD-LOC-404-NOT-FOUND", status=404, title="Location not found")
ERR_PATH_EXISTS = FieldError(code="FIELD-LOC-409-PATH-EXISTS", status=409, title="Location path exists")
ERR_PARENT_SITE = FieldError(code="FIELD-LOC-422-PARENT-SITE", status=422, title="Parent is in another site")
ERR_KIND = FieldError(code="FIELD-LOC-422-PARENT-KIND", status=422, title="Location kind not allowed")


class LocationCreate(BaseModel):
    site_id: str
    parent_id: str | None = None
    kind: str
    code: str = Field(..., pattern=r"^[A-Z0-9-]{1,24}$")
    erp_ref: str | None = None
    erp_ref_type: str | None = Field(None, pattern=r"^(storage_bin|functional_location)$")


class LocationUpdate(BaseModel):
    code: str | None = Field(None, pattern=r"^[A-Z0-9-]{1,24}$")
    parent_id: str | None = None
    status: str | None = Field(None, pattern=r"^(active|inactive)$")


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


def _get(cur: Any, loc_id: str) -> dict[str, Any]:
    cur.execute(f"SELECT {COLS} FROM field.location WHERE id = %s::uuid", (loc_id,))  # noqa: S608
    row = fetch_dict(cur)
    if not row:
        raise ERR_LOC_NOT_FOUND
    return row


def _path_depth(cur: Any, site_id: str, parent_id: str | None, code: str) -> tuple[str, int]:
    if not parent_id:
        return code, 1
    parent = _get(cur, parent_id)
    if parent["site_id"] != site_id:
        raise ERR_PARENT_SITE
    depth = int(parent["depth"]) + 1
    if depth > MAX_DEPTH:
        raise ERR_LOCATION_DEPTH
    return f"{parent['path']}/{code}", depth


@router.get("", response_model=PaginatedResponse)
async def list_locations(
    site_id: str | None = Query(None),
    parent_id: str | None = Query(None),
    kind: str | None = Query(None),
    pagination: tuple[str | None, int] = Depends(get_page_params),
    principal: Principal = Depends(require_permission("field.location.read")),
) -> PaginatedResponse:
    last_id, limit = pagination
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT {COLS} FROM field.location
             WHERE (%s::uuid IS NULL OR site_id = %s::uuid) AND (%s::uuid IS NULL OR parent_id = %s::uuid)
               AND (%s::text IS NULL OR kind = %s) AND (%s::uuid IS NULL OR id > %s::uuid)
             ORDER BY id LIMIT %s
            """,  # noqa: S608
            (site_id, site_id, parent_id, parent_id, kind, kind, last_id, last_id, limit + 1),
        )
        rows = fetch_dicts(cur)
    page = rows[:limit]
    return PaginatedResponse(
        items=[LocationRecord.model_validate(r).model_dump() for r in page],
        next_cursor=encode_cursor(page[-1]["id"]) if len(rows) > limit and page else None,
        total_in_page=len(page),
    )


@router.post("", response_model=LocationRecord, status_code=201)
async def create_location(
    loc_in: LocationCreate,
    response: Response,
    principal: Principal = Depends(require_permission("field.location.edit")),
) -> LocationRecord:
    if loc_in.kind not in ALLOWED_KINDS:
        raise ERR_KIND
    try:
        with principal_tx(principal) as cur:
            path, depth = _path_depth(cur, loc_in.site_id, loc_in.parent_id, loc_in.code)
            cur.execute(
                f"""
                INSERT INTO field.location (tenant_id, site_id, parent_id, kind, code, path, depth, erp_ref,
                       erp_ref_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active') RETURNING {COLS}
                """,  # noqa: S608
                (principal.tenant_id, loc_in.site_id, loc_in.parent_id, loc_in.kind, loc_in.code, path, depth,
                 loc_in.erp_ref, loc_in.erp_ref_type),
            )
            row = fetch_dict(cur) or {}
    except psycopg.errors.UniqueViolation as e:
        raise ERR_PATH_EXISTS from e
    except psycopg.errors.ForeignKeyViolation as e:
        raise FieldError(code="FIELD-SITE-404-NOT-FOUND", status=404, title="Site not found") from e
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    return LocationRecord.model_validate(row)


@router.get("/{loc_id}", response_model=LocationRecord)
async def get_location(
    loc_id: str,
    principal: Principal = Depends(require_permission("field.location.read")),
) -> LocationRecord:
    with principal_tx(principal) as cur:
        return LocationRecord.model_validate(_get(cur, loc_id))


@router.patch("/{loc_id}", response_model=LocationRecord)
async def update_location(
    loc_id: str,
    update_in: LocationUpdate,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission("field.location.edit")),
) -> LocationRecord:
    try:
        with principal_tx(principal) as cur:
            loc = _get(cur, loc_id)
            verify_if_match(request, int(loc["version"]), loc_id)
            fields = update_in.model_dump(exclude_unset=True)
            new_parent = fields.get("parent_id", loc["parent_id"])
            new_code = fields.get("code") or loc["code"]
            if new_parent and new_parent != loc["parent_id"]:
                # Cycle: the new parent must not be the node itself or one of its descendants.
                cur.execute(
                    "SELECT 1 FROM field.location WHERE id = %s::uuid AND site_id = %s::uuid"
                    " AND (id = %s::uuid OR path = %s OR path LIKE %s)",
                    (new_parent, loc["site_id"], loc_id, loc["path"], loc["path"] + "/%"),
                )
                if cur.fetchone():
                    raise ERR_LOCATION_CYCLE
            path, depth = _path_depth(cur, loc["site_id"], new_parent, new_code)
            # every descendant must stay within MAX_DEPTH after the move
            cur.execute(
                "SELECT COALESCE(MAX(depth), %s) FROM field.location WHERE site_id = %s::uuid AND path LIKE %s",
                (loc["depth"], loc["site_id"], loc["path"] + "/%"),
            )
            max_desc = int(cur.fetchone()[0])
            if depth + (max_desc - int(loc["depth"])) > MAX_DEPTH:
                raise ERR_LOCATION_DEPTH
            cur.execute(
                """
                UPDATE field.location
                   SET path = %s || substr(path, %s), depth = depth + %s, version = version + 1, updated_at = NOW()
                 WHERE site_id = %s::uuid AND path LIKE %s
                """,
                (path, len(loc["path"]) + 1, depth - int(loc["depth"]), loc["site_id"], loc["path"] + "/%"),
            )
            cur.execute(
                f"""
                UPDATE field.location SET parent_id = %s, code = %s, path = %s, depth = %s,
                       status = COALESCE(%s, status), version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING {COLS}
                """,  # noqa: S608
                (new_parent, new_code, path, depth, fields.get("status"), loc_id),
            )
            row = fetch_dict(cur) or {}
    except psycopg.errors.UniqueViolation as e:
        raise ERR_PATH_EXISTS from e
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    return LocationRecord.model_validate(row)
