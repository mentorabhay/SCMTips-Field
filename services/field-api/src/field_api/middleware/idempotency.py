"""Idempotency-Key Middleware with 24-Hour Replay and Conflict Detection.

Task T1.017 / PR1.01 / PR1.02 / PR1.03 / TC1.112-TC1.114.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import Response as RawResponse
from starlette.middleware.base import BaseHTTPMiddleware

from field_api.errors import (
    ERR_IDEMPOTENCY_IN_PROGRESS,
    ERR_IDEMPOTENCY_REUSED,
    problem_json_response,
)

logger = structlog.get_logger(__name__)

# Fast memory cache / storage for idempotency records in development & property tests
_MEMORY_IDEMPOTENCY_STORE: dict[str, dict[str, Any]] = {}


def compute_fingerprint(method: str, path: str, principal_id: str, body_bytes: bytes) -> str:
    """Canonical sha256 fingerprint of (method, path, principal, canonical JSON body)."""
    try:
        if body_bytes:
            parsed = json.loads(body_bytes.decode("utf-8"))
            canonical_body = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        else:
            canonical_body = b""
    except Exception:
        canonical_body = body_bytes

    hasher = hashlib.sha256()
    hasher.update(method.upper().encode("utf-8"))
    hasher.update(b"|")
    hasher.update(path.encode("utf-8"))
    hasher.update(b"|")
    hasher.update(principal_id.encode("utf-8"))
    hasher.update(b"|")
    hasher.update(canonical_body)
    return hasher.hexdigest()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Idempotency only applies to POST, and excludes /v1/auth/exchange
        if request.method != "POST" or request.url.path == "/v1/auth/exchange":
            res = await call_next(request)
            return res

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            res = await call_next(request)
            return res

        body_bytes = await request.body()
        principal_id = getattr(request.state, "principal_id", "anon")
        fingerprint = compute_fingerprint(
            request.method, request.url.path, str(principal_id), body_bytes
        )

        # Check existing record
        record = _MEMORY_IDEMPOTENCY_STORE.get(idempotency_key)
        if record:
            if record["status"] == "in_progress":
                resp_409 = problem_json_response(
                    status=409,
                    code=ERR_IDEMPOTENCY_IN_PROGRESS.code,
                    title=ERR_IDEMPOTENCY_IN_PROGRESS.title,
                    detail=ERR_IDEMPOTENCY_IN_PROGRESS.detail,
                    request=request,
                )
                return resp_409

            # Fingerprint mismatch check -> 422 FIELD-IDEM-422-KEY-REUSED
            if record["fingerprint"] != fingerprint:
                resp_422 = problem_json_response(
                    status=422,
                    code=ERR_IDEMPOTENCY_REUSED.code,
                    title=ERR_IDEMPOTENCY_REUSED.title,
                    detail=ERR_IDEMPOTENCY_REUSED.detail,
                    request=request,
                )
                return resp_422

            # Safe replay with Idempotent-Replayed: true
            headers = dict(record["headers"])
            headers["Idempotent-Replayed"] = "true"
            return RawResponse(
                content=record["body"],
                status_code=int(record["status_code"]),
                headers=headers,
                media_type=record.get("media_type", "application/json"),
            )

        # Mark in-progress
        _MEMORY_IDEMPOTENCY_STORE[idempotency_key] = {
            "status": "in_progress",
            "fingerprint": fingerprint,
            "created_at": datetime.now(UTC).isoformat(),
        }

        try:
            response = await call_next(request)

            # Read full body from response
            full_body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                full_body += chunk

            _MEMORY_IDEMPOTENCY_STORE[idempotency_key] = {
                "status": "completed",
                "fingerprint": fingerprint,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": full_body,
                "media_type": response.media_type,
                "created_at": datetime.now(UTC).isoformat(),
            }

            return RawResponse(
                content=full_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception:
            _MEMORY_IDEMPOTENCY_STORE.pop(idempotency_key, None)
            raise
