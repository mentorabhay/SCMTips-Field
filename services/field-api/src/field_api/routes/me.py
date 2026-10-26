"""Current Principal Inspection Endpoint (API1.04)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.deps import require_principal

router = APIRouter(prefix="/v1", tags=["Identity"])


class MeResponse(BaseModel):
    id: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]
    site_ids: list[str]
    device_id: str | None
    flags: dict[str, bool]


@router.get("/me", response_model=MeResponse)
async def get_me(principal: Principal = Depends(require_principal)) -> MeResponse:
    """Return identity, permissions, site scopes, and flags for current principal."""
    flags = {
        "field.lens.enabled": True,
        "field.glove_mode.enabled": False,
        "field.climb_safe.enabled": True,
        "field.walking_quiet.enabled": True,
    }
    return MeResponse(
        id=principal.id,
        tenant_id=principal.tenant_id,
        roles=principal.roles,
        permissions=principal.permissions,
        site_ids=principal.site_ids,
        device_id=principal.device_id,
        flags=flags,
    )
