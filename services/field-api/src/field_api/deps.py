"""FastAPI Route Dependencies for Security & Tenancy (Task T1.020 / FR1.030)."""

from collections.abc import Callable

from fastapi import Depends, Request

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.errors import ERR_AUTH_FORBIDDEN, ERR_AUTH_UNAUTHORIZED


def get_principal(request: Request) -> Principal | None:
    """Extract optional principal from request state."""
    return getattr(request.state, "principal", None)


def require_principal(principal: Principal | None = Depends(get_principal)) -> Principal:
    """Ensure principal is authenticated (fail-closed)."""
    if not principal:
        raise ERR_AUTH_UNAUTHORIZED
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
