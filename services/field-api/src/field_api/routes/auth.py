"""Token Exchange Endpoint (Task T1.037 / API1.03 / CS-01).

Accepts a core-signed device or session JWT (asymmetric, verified against the core JWKS; never the
field HS256 key, so a field token cannot be exchanged for a new one), plus an optional device_id.
Checks the device binding and status (field.device; core device status when CORE_API_URL is set,
failing closed), then issues a field token (aud scmtips-field, TTL min(600 s, core exp - now)).
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from field_api.auth.jwks import verify_core_jwt
from field_api.auth.jwt import create_dev_token
from field_api.auth.permissions import ROLE_PERMISSIONS, expand_permissions
from field_api.db import tenant_tx
from field_api.errors import ERR_AUTH_UNAUTHORIZED, ERR_DEVICE_REVOKED

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

MAX_FIELD_TTL_S = 600


class ExchangeRequest(BaseModel):
    device_token: str = Field(..., description="Core P10 device token or SSO session token")
    device_id: str | None = Field(None, description="Field device id (from POST /v1/devices)")
    client_id: str | None = None


class ExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    roles: list[str]
    permissions: list[str]
    tenant_id: str
    site_ids: list[str]
    device_id: str | None = None


def _field_device_active(tenant_id: str, device_id: str) -> bool:
    with tenant_tx(tenant_id, ("*",)) as cur:
        cur.execute("SELECT status FROM field.device WHERE id::text = %s", (device_id,))
        row = cur.fetchone()
    return row is not None and row[0] == "active"


async def _core_device_active(core_url: str, device_id: str) -> bool:
    """Ask core for the device status. Unreachable or malformed answers count as not active."""
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("FIELD_CORE_TIMEOUT_S", "2.0"))) as client:
            res = await client.get(f"{core_url.rstrip('/')}/api/v1/devices/{device_id}/status")
        return res.status_code == 200 and res.json().get("status") == "active"
    except (httpx.HTTPError, ValueError):
        logger.warning("core_device_status_unavailable", device_id=device_id)
        return False


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange_token(request: ExchangeRequest) -> ExchangeResponse:
    """Exchange a core-issued device/session token for a field access token."""
    now = int(datetime.now(UTC).timestamp())
    try:
        claims: dict[str, Any] = await verify_core_jwt(request.device_token)
    except Exception as e:  # any verification problem is a 401, never a fallback
        logger.warning("exchange_token_rejected", error=type(e).__name__)
        raise ERR_AUTH_UNAUTHORIZED from None

    principal_id = str(claims.get("sub") or "")
    tenant_id = str(claims.get("tenant_id") or claims.get("tid") or "")
    roles = claims.get("roles")
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise ERR_AUTH_UNAUTHORIZED from None
    if not principal_id or not isinstance(roles, list) or not roles or any(r not in ROLE_PERMISSIONS for r in roles):
        raise ERR_AUTH_UNAUTHORIZED
    sites = claims.get("sites", ["*"])
    site_ids = [str(s) for s in sites] if isinstance(sites, list) else ["*"]

    bound = claims.get("device_id") or claims.get("did")
    device_id = request.device_id or (str(bound) if bound else None)
    if device_id:
        if bound and str(bound) != device_id:
            raise ERR_AUTH_UNAUTHORIZED  # token bound to a different device
        if not _field_device_active(tenant_id, device_id):
            raise ERR_DEVICE_REVOKED
        core_url = os.getenv("CORE_API_URL")
        if core_url and not await _core_device_active(core_url, device_id):
            raise ERR_DEVICE_REVOKED

    field_ttl = min(MAX_FIELD_TTL_S, int(claims["exp"]) - now)
    if field_ttl < 1:
        raise ERR_AUTH_UNAUTHORIZED
    access_token = create_dev_token(
        principal_id=principal_id,
        tenant_id=tenant_id,
        roles=[str(r) for r in roles],
        site_ids=site_ids,
        device_id=device_id,
        exp_seconds=field_ttl,
    )
    return ExchangeResponse(
        access_token=access_token,
        expires_in=field_ttl,
        roles=[str(r) for r in roles],
        permissions=expand_permissions([str(r) for r in roles]),
        tenant_id=tenant_id,
        site_ids=site_ids,
        device_id=device_id,
    )
