"""Keyset Cursor Pagination with HMAC-Signed Opaque Cursors (Task T1.019 / PR1.09 / TC1.116)."""

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import Query
from pydantic import BaseModel

from field_api.config import settings


class PaginatedResponse(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    total_in_page: int


def encode_cursor(last_id: str, filter_hash: str = "") -> str:
    """Encode an HMAC-signed opaque cursor string."""
    payload = json.dumps({"id": last_id, "fh": filter_hash}).encode("utf-8")
    signature = hmac.new(
        settings.FIELD_CURSOR_HMAC_SECRET.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()[:16]
    token = f"{base64.urlsafe_b64encode(payload).decode('utf-8')}.{signature}"
    return token


def decode_cursor(cursor_str: str | None) -> str | None:
    """Decode and verify an HMAC-signed cursor string, returning last_id or None."""
    if not cursor_str:
        return None
    try:
        parts = cursor_str.split(".")
        if len(parts) != 2:
            return None
        b64_payload, signature = parts
        payload = base64.urlsafe_b64decode(b64_payload.encode("utf-8"))
        expected_sig = hmac.new(
            settings.FIELD_CURSOR_HMAC_SECRET.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()[:16]

        if not hmac.compare_digest(signature, expected_sig):
            return None

        data = json.loads(payload.decode("utf-8"))
        return str(data.get("id"))
    except Exception:
        return None


def get_page_params(
    cursor: str | None = Query(None, description="Opaque keyset cursor from prior response"),
    limit: int = Query(
        settings.FIELD_DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.FIELD_MAX_PAGE_SIZE,
        description="Page size limit (1..200)",
    ),
) -> tuple[str | None, int]:
    """FastAPI dependency extracting cursor and page limit."""
    last_id = decode_cursor(cursor)
    return last_id, limit
