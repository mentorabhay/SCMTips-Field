"""Idempotency-Key middleware backed by field.idempotency_record (T1.017 / PR1.01-PR1.03) (C4).

Previously a process-local dict keyed by the key alone: lost on restart, not shared across
workers, and one tenant's key collided with another's. Now (tenant_id, key) is unique in Postgres:

- POST requires Idempotency-Key (400 FIELD-IDEM-400-MISSING-KEY), except /v1/auth/exchange and
  multipart/streaming uploads that carry their own content hash
- same key + same fingerprint (method, path, principal, canonical body) -> stored response replayed
- same key + different body -> 422 FIELD-IDEM-422-KEY-REUSED
- a concurrent duplicate while the first is running -> 409 FIELD-IDEM-409-IN-PROGRESS
- 5xx responses are not stored (the client may retry); an abandoned in-progress row expires after
  IN_PROGRESS_TTL; completed rows live FIELD_IDEMPOTENCY_TTL_S (24 h)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import psycopg
import structlog
from fastapi import Request, Response
from fastapi.responses import Response as RawResponse
from psycopg.types.json import Jsonb
from starlette.middleware.base import BaseHTTPMiddleware

from field_api.config import settings
from field_api.db import tenant_tx
from field_api.errors import (
    ERR_IDEMPOTENCY_IN_PROGRESS,
    ERR_IDEMPOTENCY_REUSED,
    FieldError,
    problem_json_response,
)

logger = structlog.get_logger(__name__)

IN_PROGRESS_TTL = timedelta(seconds=60)
EXEMPT_PATHS = frozenset({"/v1/auth/exchange"})
ERR_MISSING_KEY = FieldError(code="FIELD-IDEM-400-MISSING-KEY", status=400, title="Idempotency-Key header required")
REPLAY_HEADERS = ("content-type", "etag", "location", "retry-after")


def compute_fingerprint(method: str, path: str, principal_id: str, body_bytes: bytes) -> str:
    """Canonical sha256 fingerprint of (method, path, principal, canonical JSON body)."""
    try:
        canonical = (json.dumps(json.loads(body_bytes), sort_keys=True, separators=(",", ":")).encode()
                     if body_bytes else b"")
    except ValueError:
        canonical = body_bytes
    h = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), principal_id.encode(), canonical):
        h.update(part)
        h.update(b"|")
    return h.hexdigest()


def _problem(err: FieldError, request: Request) -> Response:
    return problem_json_response(err.status, err.code, err.title, err.detail, request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method != "POST" or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        principal = getattr(request.state, "principal", None)
        if principal is None:  # unauthenticated: the route's own auth answers (401)
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return _problem(ERR_MISSING_KEY, request)
        if len(key) > 200:
            return _problem(ERR_IDEMPOTENCY_REUSED, request)
        ctype = request.headers.get("content-type", "")
        body = b"" if ctype.startswith("multipart/") else await request.body()
        fp = compute_fingerprint(request.method, request.url.path, principal.id,
                                 body if body else ctype.encode() + request.headers.get("content-length", "").encode())
        now = datetime.now(UTC)
        ttl = timedelta(seconds=settings.FIELD_IDEMPOTENCY_TTL_S)

        with tenant_tx(principal.tenant_id) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"idem:{principal.tenant_id}:{key}",))
            cur.execute(
                "SELECT fingerprint, status, status_code, headers, body, media_type, created_at, expires_at"
                " FROM field.idempotency_record WHERE idempotency_key = %s",
                (key,),
            )
            row = cur.fetchone()
            if row:
                fpr, status, code, headers, stored, media, created, expires = row
                expired = (expires and expires < now) or (status == "in_progress" and created + IN_PROGRESS_TTL < now)
                if expired:
                    cur.execute("DELETE FROM field.idempotency_record WHERE idempotency_key = %s", (key,))
                    row = None
                elif fpr != fp:
                    return _problem(ERR_IDEMPOTENCY_REUSED, request)
                elif status == "in_progress":
                    return _problem(ERR_IDEMPOTENCY_IN_PROGRESS, request)
                else:
                    hdrs = {**(headers or {}), "Idempotent-Replayed": "true"}
                    return RawResponse(content=bytes(stored or b""), status_code=code, headers=hdrs, media_type=media)
            cur.execute(
                "INSERT INTO field.idempotency_record (tenant_id, idempotency_key, fingerprint, status, route, expires_at)"
                " VALUES (%s, %s, %s, 'in_progress', %s, %s)",
                (principal.tenant_id, key, fp, request.url.path, now + ttl),
            )

        try:
            response = await call_next(request)
        except Exception:
            self._forget(principal.tenant_id, key)
            raise
        chunks = [c async for c in response.body_iterator]  # type: ignore[attr-defined]
        content = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
        if response.status_code >= 500:
            self._forget(principal.tenant_id, key)
        else:
            keep = {k: v for k, v in response.headers.items() if k.lower() in REPLAY_HEADERS}
            try:
                with tenant_tx(principal.tenant_id) as cur:
                    cur.execute(
                        "UPDATE field.idempotency_record SET status = 'completed', status_code = %s, headers = %s,"
                        " body = %s, media_type = %s, body_sha256 = %s WHERE idempotency_key = %s",
                        (response.status_code, Jsonb(keep), content, response.media_type,
                         hashlib.sha256(content).hexdigest(), key),
                    )
            except psycopg.Error:
                logger.exception("idempotency_store_failed", key=key)
        return RawResponse(content=content, status_code=response.status_code,
                           headers=dict(response.headers), media_type=response.media_type)

    @staticmethod
    def _forget(tenant_id: str, key: str) -> None:
        try:
            with tenant_tx(tenant_id) as cur:
                cur.execute("DELETE FROM field.idempotency_record WHERE idempotency_key = %s AND status = 'in_progress'",
                            (key,))
        except psycopg.Error:
            logger.exception("idempotency_forget_failed", key=key)
