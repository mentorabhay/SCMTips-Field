"""SCMTIPS Field Error Registry and RFC 9457 Problem+JSON Handler (Task T1.013 / PR1.12)."""

from typing import Any

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


class FieldError(Exception):
    """Domain exception mapping to an RFC 9457 problem response."""

    def __init__(
        self,
        code: str,
        status: int,
        title: str,
        detail: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail or title
        self.errors = errors or []


# Standard Error Catalog
ERR_IDEMPOTENCY_REUSED = FieldError(
    code="FIELD-IDEM-422-KEY-REUSED",
    status=422,
    title="Idempotency Key Reused",
    detail="The provided Idempotency-Key was already used with a different request payload.",
)

ERR_IDEMPOTENCY_IN_PROGRESS = FieldError(
    code="FIELD-IDEM-409-IN-PROGRESS",
    status=409,
    title="Request in Progress",
    detail="A request with this Idempotency-Key is currently executing. Retry after 1 second.",
)

ERR_ETAG_REQUIRED = FieldError(
    code="FIELD-ETAG-428-REQUIRED",
    status=428,
    title="Precondition Required",
    detail="This resource requires an If-Match header matching the current version.",
)

ERR_ETAG_MISMATCH = FieldError(
    code="FIELD-ETAG-412-PRECONDITION-FAILED",
    status=412,
    title="Precondition Failed",
    detail="The resource version has changed since the If-Match tag was retrieved.",
)

ERR_AUTH_UNAUTHORIZED = FieldError(
    code="FIELD-AUTH-401-UNAUTHORIZED",
    status=401,
    title="Unauthorized",
    detail="Missing or invalid authentication credentials.",
)

ERR_AUTH_FORBIDDEN = FieldError(
    code="FIELD-AUTH-403-FORBIDDEN",
    status=403,
    title="Forbidden",
    detail="Principal does not possess required permissions or site scope.",
)

ERR_DEVICE_REVOKED = FieldError(
    code="FIELD-AUTH-403-DEVICE-REVOKED",
    status=403,
    title="Device Revoked",
    detail="The requested device registration has been revoked by core or supervisor.",
)

ERR_NOT_FOUND = FieldError(
    code="FIELD-CORE-404-NOT-FOUND",
    status=404,
    title="Not Found",
    detail="The requested resource does not exist.",
)

ERR_LOCATION_CYCLE = FieldError(
    code="FIELD-LOC-422-CYCLE",
    status=422,
    title="Location Hierarchy Cycle",
    detail="Moving this location under the target parent would create a directed cycle.",
)

ERR_LOCATION_DEPTH = FieldError(
    code="FIELD-LOC-422-MAX-DEPTH",
    status=422,
    title="Location Depth Exceeded",
    detail="Location hierarchy depth cannot exceed 6 levels.",
)


def problem_json_response(
    status: int,
    code: str,
    title: str,
    detail: str,
    request: Request,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build RFC 9457 Problem+JSON response."""
    request_id = getattr(request.state, "request_id", "req-unknown")
    body: dict[str, Any] = {
        "type": f"urn:scmtips-field:problem:{code}",
        "code": code,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": str(request.url),
        "request_id": request_id,
    }
    if errors:
        body["errors"] = errors

    headers = {"Content-Type": "application/problem+json"}
    if status == 409 and code == "FIELD-IDEM-409-IN-PROGRESS":
        headers["Retry-After"] = "1"

    return JSONResponse(status_code=status, content=body, headers=headers)
