"""FastAPI Router for Asset Models, glTF Validation, and BOM Versioning (WS4.7).

Exposes:
- POST  /v1/asset-models (API4.12)
- POST  /v1/asset-models/{id}/publish (API4.13)
- GET   /v1/asset-models/{id}/bom (API4.14)
- PATCH /v1/asset-models/{id}/bom (TC4.146)
"""

from __future__ import annotations

import base64
import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from field_api.auth.jwks import verify_core_jwt
from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.deps import require_principal
from field_api.models.upload import create_asset_model_draft
from field_api.models.versions import get_model_bom, publish_asset_model, update_model_bom
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Asset Models & 3D BOM"])


class BomPatchRequest(BaseModel):
    items: list[dict[str, Any]] = Field(
        ..., description="List of BOM item updates (part_no, description, etc.)"
    )


@router.post(
    "/v1/asset-models",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a draft model version (multipart .glb + BOM CSV - API4.12)",
)
async def api_upload_asset_model(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.12: Upload and validate .glb model and BOM CSV."""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data = await request.json()
        eq_class = data.get("equipment_class")
        ver = data.get("version")
        csv_text = data.get("bom_csv", "")
        glb_b64 = data.get("glb_base64")
        if not glb_b64 or not eq_class or not ver:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "FIELD-MOD-422-INVALID",
                    "message": "Missing required fields in JSON payload",
                },
            )
        glb_data = base64.b64decode(glb_b64)
    else:
        form = await request.form()
        eq_class = form.get("equipment_class")
        ver = form.get("version")
        glb_field = form.get("glb")
        bom_csv_field = form.get("bom_csv")
        if not eq_class or not ver or not glb_field or not bom_csv_field:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "FIELD-MOD-422-INVALID",
                    "message": "Missing required multipart fields",
                },
            )
        glb_data = (
            await glb_field.read()
            if hasattr(glb_field, "read")
            else (glb_field.encode("utf-8") if isinstance(glb_field, str) else bytes(glb_field))
        )
        csv_bytes = (
            await bom_csv_field.read()
            if hasattr(bom_csv_field, "read")
            else bytes(bom_csv_field, "utf-8")
        )
        csv_text = (
            csv_bytes.decode("utf-8")
            if isinstance(csv_bytes, (bytes, bytearray))
            else str(csv_bytes)
        )

    return create_asset_model_draft(
        tenant_id=principal.tenant_id,
        equipment_class=eq_class,
        version=ver,
        glb_bytes=glb_data,
        bom_csv_text=csv_text,
        created_by=principal.id,
    )


@router.post(
    "/v1/asset-models/{id}/publish",
    status_code=status.HTTP_200_OK,
    summary="Publish a validated version with step-up verification (API4.13)",
)
async def api_publish_asset_model(
    id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_stepup_token: str | None = Header(None, alias="X-Stepup-Token"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.13: Publish model version, allocate stable balloons, and emit outbox event.

    Needs BOTH the field.model.publish permission AND step-up: X-Stepup-Token must be a core token
    (verified against the core JWKS) for the same user and tenant, issued within the last 5 minutes,
    i.e. a fresh re-authentication. (Previously any non-empty header bypassed the permission check.)
    """
    if not has_permission(principal.permissions, "field.model.publish"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error_code": "FIELD-AUTH-403-FORBIDDEN", "message": "field.model.publish required"})
    await _require_stepup(x_stepup_token, principal)

    return publish_asset_model(
        tenant_id=principal.tenant_id,
        model_id=id,
        published_by=principal.id,
    )


STEPUP_MAX_AGE_S = 300


async def _require_stepup(token: str | None, principal: Principal) -> None:
    def refuse(msg: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail={"error_code": "FIELD-AUTH-401-STEPUP", "message": msg})

    if not token:
        raise refuse("Publishing a model requires a fresh re-authentication (step-up)")
    try:
        claims = await verify_core_jwt(token)
    except Exception:
        raise refuse("Step-up token is not a valid core token") from None
    tenant = str(claims.get("tenant_id") or claims.get("tid") or "")
    iat = int(claims.get("iat") or 0)
    if str(claims.get("sub")) != principal.id or tenant != principal.tenant_id:
        raise refuse("Step-up token belongs to another user")
    if time.time() - iat > STEPUP_MAX_AGE_S:
        raise refuse("Step-up is older than 5 minutes; re-authenticate")


@router.get(
    "/v1/asset-models/{id}/bom",
    status_code=status.HTTP_200_OK,
    summary="Get BOM with balloons, node mapping, explode vectors (API4.14)",
)
def api_get_asset_model_bom(
    id: str,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.14: Retrieve BOM hierarchy, balloons, and explode vectors."""
    return get_model_bom(tenant_id=principal.tenant_id, model_id=id)


@router.patch(
    "/v1/asset-models/{id}/bom",
    status_code=status.HTTP_200_OK,
    summary="Update model BOM (rejected with 409 if published - TC4.146)",
)
def api_patch_asset_model_bom(
    id: str,
    body: BomPatchRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """TC4.146: Immutability enforcement on published models."""
    return update_model_bom(
        tenant_id=principal.tenant_id,
        model_id=id,
        bom_updates=body.items,
    )
