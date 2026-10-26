"""Authentication and Principal Resolution Middleware (Task T1.011 / FR1.009)."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from field_api.auth.jwt import Principal, verify_token

logger = structlog.get_logger(__name__)

# Paths that do not require authentication
PUBLIC_PATHS = {
    "/v1/health",
    "/v1/ready",
    "/v1/auth/exchange",
    "/docs",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path

        # Allow public endpoints without auth
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/static"):
            res = await call_next(request)
            return res

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            # Let route dependency or handler decide or fail closed
            request.state.principal = None
            res = await call_next(request)
            return res

        token = auth_header[7:].strip()
        try:
            principal: Principal = verify_token(token)
            request.state.principal = principal
            request.state.principal_id = principal.id
            request.state.tenant_id = principal.tenant_id
            request.state.site_ids = principal.site_ids
            structlog.contextvars.bind_contextvars(
                tenant_id=principal.tenant_id,
                principal_id=principal.id,
            )
        except Exception:
            request.state.principal = None

        res = await call_next(request)
        return res
