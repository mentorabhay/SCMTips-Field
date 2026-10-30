"""FastAPI Route Dependencies for Security & Tenancy (Task T1.020 / FR1.030)."""

from collections.abc import Callable

from fastapi import Depends, Request

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.errors import ERR_AUTH_FORBIDDEN, ERR_AUTH_UNAUTHORIZED, ERR_DEVICE_REVOKED

__all__ = [
    "Principal",
    "get_principal",
    "require_principal",
    "require_permission",
    "require_site_scope",
]


def get_principal(request: Request) -> Principal | None:
    """Extract optional principal from request state."""
    return getattr(request.state, "principal", None)


def device_is_revoked(principal: Principal) -> bool:
    """True when the token is bound to a device that is no longer active (T1.038 / FR1.034).

    A device token whose device row is missing is also refused: bindings are created by
    POST /v1/devices before the device can act.
    """
    from field_api.db import (
        tenant_tx,  # local import: db imports config, avoid cycles at import time
    )

    with tenant_tx(principal.tenant_id, ("*",)) as cur:
        cur.execute("SELECT status FROM field.device WHERE id::text = %s", (principal.device_id,))
        row = cur.fetchone()
    return row is None or row[0] != "active"


def require_principal(principal: Principal | None = Depends(get_principal)) -> Principal:
    """Ensure principal is authenticated (fail-closed); device-bound tokens need an active device."""
    if not principal:
        raise ERR_AUTH_UNAUTHORIZED
    if principal.device_id and device_is_revoked(principal):
        raise ERR_DEVICE_REVOKED
    return principal


def require_permission(perm: str) -> Callable[[Principal], Principal]:
    """Dependency factory checking that the principal possesses a specific permission."""

    def _checker(principal: Principal = Depends(require_principal)) -> Principal:
        if not has_permission(principal.permissions, perm):
            raise ERR_AUTH_FORBIDDEN
        return principal

    return _checker


def require_site_scope(site_id: str, principal: Principal) -> None:
    """Validate that the requested site_id is within the principal's site scope."""
    if "*" in principal.site_ids:
        return
    if site_id not in principal.site_ids:
        raise ERR_AUTH_FORBIDDEN
