"""Evidence HTTP API (M5 contract section 3).

GET  /v1/evidence/documents/{doc_number}?year=      field.evidence.pack (every field role of the tenant)
     -> the JSON evidence pack (evidence/pack.py); ETag = the pack's sha256
POST /v1/evidence/documents/{doc_number}/link?year=  field.evidence.pack; Idempotency-Key (middleware)
     -> {url, path, expires_at}: a signed link to the page (evidence/signing.py), valid FIELD_EVIDENCE_LINK_TTL_S
        (default 24 h)
GET  /evidence/{token}                              public: the HMAC token is the credential (tenant + document +
     expiry); 401 for a tampered, malformed or expired token; -> the self-contained HTML page (evidence/page.py)
The link's host is FIELD_PUBLIC_BASE_URL when set (http/https), else the request's own base URL.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.claims.looks import LookPort, get_look_port
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.evidence import signing
from field_api.evidence.pack import build_pack
from field_api.evidence.page import render

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Evidence (M5)"])

DOC_PATTERN = r"^[A-Za-z0-9._-]{1,40}$"
YEAR_PATTERN = r"^\d{4}$"
PUBLIC_BASE_ENV = "FIELD_PUBLIC_BASE_URL"
ERR_TOKEN = FieldError(status=401, code="FIELD-EVD-401-INVALID-TOKEN", title="Invalid or expired evidence link")
PAGE_HEADERS = MappingProxyType({
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none';"
                               " form-action 'none'; frame-ancestors 'none'",
})


class EvidenceLinkOut(BaseModel):
    url: str
    path: str
    expires_at: str


def _base_url(request: Request) -> str:
    configured = os.getenv(PUBLIC_BASE_ENV, "").strip().rstrip("/")
    if configured and re.match(r"^https?://[^\s/]+", configured):
        return configured
    return str(request.base_url).rstrip("/")


@router.get("/v1/evidence/documents/{doc_number}")
def get_evidence_pack(
    response: Response,
    doc_number: str = Path(pattern=DOC_PATTERN),
    year: str | None = Query(None, pattern=YEAR_PATTERN),
    principal: Principal = Depends(require_permission("field.evidence.pack")),
    looks: LookPort = Depends(get_look_port),
) -> dict[str, Any]:
    pack = build_pack(principal, doc_number, year, looks=looks)
    response.headers["ETag"] = f'"{pack.body["hashes"]["pack_sha256"]}"'
    response.headers["Cache-Control"] = "private, no-store"
    return pack.body


@router.post("/v1/evidence/documents/{doc_number}/link", response_model=EvidenceLinkOut)
def post_evidence_link(
    request: Request,
    doc_number: str = Path(pattern=DOC_PATTERN),
    year: str | None = Query(None, pattern=YEAR_PATTERN),
    principal: Principal = Depends(require_permission("field.evidence.pack")),
    looks: LookPort = Depends(get_look_port),
) -> dict[str, Any]:
    pack = build_pack(principal, doc_number, year, looks=looks)  # 404 / 409 before a link is ever signed
    doc = pack.body["document"]
    token, exp = signing.sign(principal.tenant_id, str(doc["number"]), str(doc["year"]))
    path = f"/evidence/{token}"
    return {"url": _base_url(request) + path, "path": path,
            "expires_at": datetime.fromtimestamp(exp, UTC).isoformat()}


@router.get("/evidence/{token}", response_class=HTMLResponse)
def get_evidence_page(token: str, looks: LookPort = Depends(get_look_port)) -> HTMLResponse:
    try:
        link = signing.verify(token)
    except signing.BadToken as e:
        logger.info("evidence_link_refused", reason=e.reason)
        raise ERR_TOKEN from None
    reader = Principal(id="evidence-link", tenant_id=link.tenant_id, roles=[], permissions=[], site_ids=["*"],
                       auth_type="evidence_link")
    pack = build_pack(reader, link.doc_number, link.fiscal_year, looks=looks)
    return HTMLResponse(render(pack.body, pack.photo), headers=dict(PAGE_HEADERS))
