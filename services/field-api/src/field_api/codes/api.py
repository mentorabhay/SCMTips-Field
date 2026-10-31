"""GET /v1/codes/{code}?site_id= : what a scanned code is on a site (M3 contract section 2).

Any field role with field.task.read. 200 {code, kind: material|bin|serial|unknown,
material: {material, description, uom} | null, bin: str | null, site_mode: production|sandbox}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from field_api.auth.jwt import Principal
from field_api.codes.resolve import CodeLookup, resolve_code
from field_api.deps import require_permission

router = APIRouter(tags=["Codes (M3)"])


@router.get("/v1/codes/{code}")
def get_code(
    code: str = Path(min_length=1, max_length=128),
    site_id: str = Query(..., description="the site the code was scanned on"),
    principal: Principal = Depends(require_permission("field.task.read")),
) -> CodeLookup:
    return resolve_code(principal, site_id, code)
