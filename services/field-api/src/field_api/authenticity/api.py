"""C3 authenticity check routes (docs/design/M5_C3_CONTRACT.md section 4).

POST /v1/authenticity/checks {code, capture_id?, site_id?, area?}   field.authenticity.check; Idempotency-Key
     -> 200 the check (always 200 once the site and capture are found: an unreachable maker or a model failure is a
        verdict or a visual status, never an error). With a photo the visual seal check runs in this request's
        background task after the answer (``final`` false until it ends).
GET  /v1/authenticity/checks/{check_id}                             field.authenticity.check -> the check as it is now
GET  /v1/authenticity/checks/{check_id}/evidence                    field.authenticity.check -> the JSON evidence pack
POST /v1/authenticity/checks/{check_id}/link                        field.authenticity.check -> {url, path, expires_at}
GET  /evidence/check/{token}                                        public: the HMAC token is the credential -> HTML
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from fastapi.responses import HTMLResponse
from field_oem.ports.oem_port import OemPort
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.authenticity.evidence import build_check_pack, render_check
from field_api.authenticity.oem import get_oem_port
from field_api.authenticity.seal import VisualPorts, get_visual_ports
from field_api.authenticity.service import CheckIn, create_check, get_check
from field_api.deps import require_permission
from field_api.evidence import signing
from field_api.evidence.api import ERR_TOKEN, PAGE_HEADERS, _base_url

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Authenticity checks (M5 C3)"])
PERMISSION = "field.authenticity.check"


class CheckLinkOut(BaseModel):
    url: str
    path: str
    expires_at: str


@router.post("/v1/authenticity/checks", status_code=200)
def post_check(
    body: CheckIn,
    background: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission(PERMISSION)),
    port: OemPort = Depends(get_oem_port),
    vports: VisualPorts = Depends(get_visual_ports),
) -> dict[str, Any]:
    return create_check(principal, body, idempotency_key, port, vports, defer=background.add_task)


@router.get("/v1/authenticity/checks/{check_id}")
def read_check(check_id: str, principal: Principal = Depends(require_permission(PERMISSION))) -> dict[str, Any]:
    return get_check(principal, check_id)


@router.get("/v1/authenticity/checks/{check_id}/evidence")
def check_evidence(check_id: str, response: Response,
                   principal: Principal = Depends(require_permission(PERMISSION))) -> dict[str, Any]:
    pack = build_check_pack(principal, check_id)
    response.headers["ETag"] = f'"{pack.body["hashes"]["pack_sha256"]}"'
    response.headers["Cache-Control"] = "private, no-store"
    return pack.body


@router.post("/v1/authenticity/checks/{check_id}/link", response_model=CheckLinkOut)
def check_link(check_id: str, request: Request,
               principal: Principal = Depends(require_permission(PERMISSION))) -> dict[str, Any]:
    check = get_check(principal, check_id)  # 404 before a link is ever signed
    token, exp = signing.sign_check(principal.tenant_id, check["check_id"])
    path = f"/evidence/check/{token}"
    return {"url": _base_url(request) + path, "path": path, "expires_at": datetime.fromtimestamp(exp, UTC).isoformat()}


@router.get("/evidence/check/{token}", response_class=HTMLResponse)
def check_page(token: str) -> HTMLResponse:
    try:
        link = signing.verify_check(token)
    except signing.BadToken as e:
        logger.info("check_evidence_link_refused", reason=e.reason)
        raise ERR_TOKEN from None
    reader = Principal(id="evidence-link", tenant_id=link.tenant_id, roles=[], permissions=[], site_ids=["*"],
                       auth_type="evidence_link")
    pack = build_check_pack(reader, link.check_id)
    return HTMLResponse(render_check(pack.body, pack.photo), headers=dict(PAGE_HEADERS))
