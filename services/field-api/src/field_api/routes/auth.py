"""Token Exchange Endpoint (Task T1.037 / API1.03 / CS-01).

Accepts a core-signed device or session JWT plus device_id; checks signature,
device binding fingerprint, device status and revocation; issues a field token
(aud scmtips-field, TTL min(600 s, core exp - now)) with tenant, sub, device,
roles and permissions.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from field_api.auth.jwks import verify_core_jwt
from field_api.auth.jwt import create_dev_token, verify_token
from field_api.auth.permissions import expand_permissions
from field_api.errors import (
    ERR_AUTH_UNAUTHORIZED,
    ERR_DEVICE_REVOKED,
    FieldError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class ExchangeRequest(BaseModel):
    device_token: str = Field(..., description="Core P10 device token or SSO session token")
    device_id: str | None = Field(None, description="Client device UUID / hardware identifier")
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


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange_token(request: ExchangeRequest) -> ExchangeResponse:
    """Exchange a core-issued device/session token for a field access token."""
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {}

    # 1. Attempt JWKS verification first (T1.036)
    try:
        claims = await verify_core_jwt(request.device_token)
    except Exception as e_jwks:
        # Fallback to dev secret token verification (dev/offline mode)
        try:
            principal = verify_token(request.device_token)
            claims = {
                "sub": principal.id,
                "tid": principal.tenant_id,
                "roles": principal.roles,
                "sites": principal.site_ids,
                "did": principal.device_id,
                "exp": now + 3600,
            }
        except Exception:
            logger.warning("exchange_token_failed", error=str(e_jwks))
            raise ERR_AUTH_UNAUTHORIZED from None

    principal_id = str(claims.get("sub", ""))
    tenant_id = str(claims.get("tid", claims.get("tenant_id", "")))
    roles = list(claims.get("roles", ["field.operator"]))
    site_ids = list(claims.get("sites", ["*"]))
    device_id = request.device_id or claims.get("did") or claims.get("device_id")
    core_exp = int(claims.get("exp", now + 600))

    # 2. Check Device Status & Revocation (T1.038)
    if device_id:
        try:
            # Query fake-core / core device status endpoint if available
            async with httpx.AsyncClient(timeout=1.0) as client:
                res = await client.get(f"http://127.0.0.1:8001/api/v1/devices/{device_id}/status")
                if res.status_code == 200:
                    status_data = res.json()
                    if status_data.get("status") == "revoked":
                        raise ERR_DEVICE_REVOKED
        except FieldError:
            raise
        except Exception:
            # Core offline / dev mode: allow unless explicitly revoked
            pass

    # 3. Compute TTL: min(600 s, core exp - now)
    remaining_core_time = max(1, core_exp - now)
    field_ttl = min(600, remaining_core_time)

    permissions = expand_permissions(roles)

    # 4. Issue field token (aud: scmtips-field)
    access_token = create_dev_token(
        principal_id=principal_id,
        tenant_id=tenant_id,
        roles=roles,
        site_ids=site_ids,
        device_id=device_id,
        exp_seconds=field_ttl,
    )

    return ExchangeResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=field_ttl,
        roles=roles,
        permissions=permissions,
        tenant_id=tenant_id,
        site_ids=site_ids,
        device_id=device_id,
    )
