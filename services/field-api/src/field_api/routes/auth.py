"""Interim Token Exchange Endpoint (Task T1.037 / API1.03 / CS-01 interim)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from field_api.auth.jwt import create_dev_token, verify_token

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class ExchangeRequest(BaseModel):
    device_token: str = Field(..., description="Core P10 device token")
    client_id: str | None = None


class ExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    roles: list[str]
    permissions: list[str]
    tenant_id: str
    site_ids: list[str]


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange_token(request: ExchangeRequest) -> ExchangeResponse:
    """Exchange a core-issued device token for a field access token."""
    # Verify core token
    principal = verify_token(request.device_token)

    # Issue scoped field access token
    access_token = create_dev_token(
        principal_id=principal.id,
        tenant_id=principal.tenant_id,
        roles=principal.roles,
        site_ids=principal.site_ids,
        device_id=principal.device_id,
        exp_seconds=3600,
    )

    return ExchangeResponse(
        access_token=access_token,
        roles=principal.roles,
        permissions=principal.permissions,
        tenant_id=principal.tenant_id,
        site_ids=principal.site_ids,
    )
