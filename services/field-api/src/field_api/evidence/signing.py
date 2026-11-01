"""Signed evidence-page links (M5 contract section 3), signed like ``field_worker.jobs.audit_report``: HMAC-SHA256
with FIELD_EVIDENCE_SECRET, bound to the tenant and an expiry.

Token = ``<payload>.<signature>``: ``payload`` is base64url (no padding) of the compact JSON
``{"v": 1, "t": tenant_id, "d": doc_number, "y": fiscal_year, "e": expires_at_unix}``; ``signature`` is the hex
HMAC-SHA256 over ``DOMAIN + payload`` (DOMAIN separates these tokens from the audit-report signatures, which use the
same key). Verification checks the signature in constant time first, then the shape, then the expiry. The token
carries no secret; the key is read by name (A-02) and never logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass

from field_api.secrets import required_secret

DOMAIN = b"scmtips-field/m5-evidence-page/v1\n"
SECRET_ENV = "FIELD_EVIDENCE_SECRET"
TTL_ENV = "FIELD_EVIDENCE_LINK_TTL_S"
DEFAULT_TTL_S = 24 * 3600
MIN_TTL_S, MAX_TTL_S = 60, 7 * 24 * 3600
MAX_TOKEN_LEN = 600
DOC_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
YEAR_RE = re.compile(r"^\d{4}$")


class BadToken(Exception):
    """The link is not valid: tampered, malformed or expired (``reason`` is safe to log)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EvidenceLink:
    tenant_id: str
    doc_number: str
    fiscal_year: str
    expires_at: int


def link_ttl_s() -> int:
    raw = os.getenv(TTL_ENV, "").strip()
    if not raw.isdigit():
        return DEFAULT_TTL_S
    return max(MIN_TTL_S, min(MAX_TTL_S, int(raw)))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(payload: str) -> str:
    key = required_secret(SECRET_ENV).encode("utf-8")
    return hmac.new(key, DOMAIN + payload.encode("ascii"), hashlib.sha256).hexdigest()


def sign(tenant_id: str, doc_number: str, fiscal_year: str, *, ttl_s: int | None = None,
         now: float | None = None) -> tuple[str, int]:
    """(token, expires_at unix seconds)."""
    if not DOC_RE.match(doc_number) or not YEAR_RE.match(fiscal_year):
        raise ValueError("bad document number or year")
    exp = int((now if now is not None else time.time()) + (ttl_s if ttl_s is not None else link_ttl_s()))
    body = json.dumps({"v": 1, "t": tenant_id, "d": doc_number, "y": fiscal_year, "e": exp},
                      separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = _b64(body)
    return f"{payload}.{_sig(payload)}", exp


def verify(token: str, *, now: float | None = None) -> EvidenceLink:
    if not token or len(token) > MAX_TOKEN_LEN or token.count(".") != 1:
        raise BadToken("malformed")
    payload, sig = token.split(".")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", payload) or not re.fullmatch(r"[0-9a-f]{64}", sig):
        raise BadToken("malformed")
    if not hmac.compare_digest(_sig(payload), sig):
        raise BadToken("signature")
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        raise BadToken("malformed") from None
    if not isinstance(data, dict) or data.get("v") != 1:
        raise BadToken("malformed")
    t, d, y, e = data.get("t"), data.get("d"), data.get("y"), data.get("e")
    if not (isinstance(t, str) and isinstance(d, str) and isinstance(y, str) and isinstance(e, int)):
        raise BadToken("malformed")
    if not DOC_RE.match(d) or not YEAR_RE.match(y):
        raise BadToken("malformed")
    if (now if now is not None else time.time()) > e:
        raise BadToken("expired")
    return EvidenceLink(t, d, y, e)
