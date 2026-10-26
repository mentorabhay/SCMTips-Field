"""Request-ID Middleware with Redacted Structured Logging (Task T1.014 / FR1.015 / FR1.063)."""

import re
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from field_common.uuid7 import uuid7_str
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
logger = structlog.get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming_id = request.headers.get("X-Request-Id")
        if incoming_id and REQUEST_ID_REGEX.match(incoming_id):
            request_id = incoming_id
        else:
            request_id = f"req-{uuid7_str()}"

        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
