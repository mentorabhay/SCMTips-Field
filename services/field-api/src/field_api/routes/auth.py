"""Token Exchange Endpoint (Task T1.037 / API1.03 / CS-01; M4 F7 core tokens).

Accepts a core-signed device or session JWT (asymmetric, verified against the core JWKS; never the
field HS256 key, so a field token cannot be exchanged for a new one), plus an optional device_id.
Checks the device binding and status, then issues a field token (aud scmtips-field,
TTL min(600 s, core exp - now)).

M4 F7 (handover 01 / 01a, M4 contract section 4):
- Core app tokens (POST {CORE}/v1/auth/app/token) carry two extra claims, ``permissions`` (core permission keys,
  e.g. ``voice.approve``) and ``email``. Both are optional; when present they must be a list of strings and a
  string. The permissions are echoed as ``core_permissions`` (field never decides an approval: every approval
  rule lives in the core); the e-mail is never stored nor put in the field token.
- A core token is bound to the core's device id (``device_id`` claim, the app's install id, 8-64 chars), which is
  not a field.device id. The field device for it is the field.device whose id OR serial_no equals that core id.
  When there is none yet and the core's device status (FIELD_CORE_DEVICE_STATUS_URL) answers ``active``, the
  exchange registers it (kind phone, serial_no = the core device id) and answers its id as ``device_id``: the app
  uses that id and does not POST /v1/devices for it. Without a configured core device check a bound token with
  no field.device stays refused (403), as before.
- Device status: FIELD_CORE_DEVICE_STATUS_URL (template with {device_id}, {tenant_id} from the token) is asked
  about the core-bound device id; an unbound token (dev QR pairing) has no core device and is not asked there.
  Legacy CORE_API_URL (fake-core's /api/v1/devices/{id}/status) keeps today's behaviour: it is asked about the
  device id in use. Unreachable or malformed answers count as not active (fail closed).
- Roles (the core's reply TO_FIELD section 2, decision (b)): the core's token carries core role keys
  (``approver``, ``procurement``, ...). They are mapped to Field roles by FIELD_CORE_ROLE_MAP (default table in
  field_api.auth.core_roles); Field role names keep working as they are. A token whose roles map to nothing is
  refused with 403 FIELD-AUTH-403-NO-FIELD-ROLE and a sentence the app shows on its sign-in screen (not a bare
  401). The mapped core keys are echoed as ``core_roles``.
- Every call to the core carries ``X-Requested-With: lr`` (TO_FIELD section 3: the core checks it).
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from field_api.auth.core import CORE_HEADERS, device_status_template, render_device_status_url
from field_api.auth.core_roles import RoleMapError, core_role_map, map_roles
from field_api.auth.jwks import verify_core_jwt
from field_api.auth.jwt import create_dev_token
from field_api.auth.permissions import expand_permissions
from field_api.db import tenant_tx
from field_api.errors import (
    ERR_AUTH_UNAUTHORIZED,
    ERR_CORE_ROLE_MAP_INVALID,
    ERR_DEVICE_REVOKED,
    err_no_field_role,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

MAX_FIELD_TTL_S = 600
# Tests route the core device-status call in-process (httpx.ASGITransport(app=<stand-in core>)); None = network.
CORE_TRANSPORT: httpx.AsyncBaseTransport | None = None


class ExchangeRequest(BaseModel):
    device_token: str = Field(..., description="Core P10 device token, SSO session token or core app token")
    device_id: str | None = Field(None, description="Field device id (from POST /v1/devices or a previous exchange)")
    client_id: str | None = None


class ExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    roles: list[str]
    permissions: list[str]
    tenant_id: str
    site_ids: list[str]
    device_id: str | None = None
    core_permissions: list[str] = Field(default_factory=list,
                                        description="the core token's permissions claim (M4 F7); field decides nothing on them")
    core_roles: list[str] = Field(default_factory=list,
                                  description="the core role keys of the token that FIELD_CORE_ROLE_MAP mapped to `roles`")


def _field_device(tenant_id: str, ref: str) -> tuple[str, str, str] | None:
    """(id, serial_no, status) of the field.device whose id or serial_no is ``ref``; the id wins."""
    with tenant_tx(tenant_id, ("*",)) as cur:
        cur.execute("SELECT id::text, serial_no, status FROM field.device WHERE id::text = %s OR serial_no = %s"
                    " ORDER BY (id::text = %s) DESC LIMIT 1", (ref, ref, ref))
        row = cur.fetchone()
    return (str(row[0]), str(row[1]), str(row[2])) if row else None


def _register_core_device(tenant_id: str, core_device_id: str, model: str) -> str:
    """field.device for a core-bound device the core reports active (serial_no = the core device id)."""
    with tenant_tx(tenant_id, ("*",)) as cur:
        cur.execute(
            "INSERT INTO field.device (tenant_id, kind, serial_no, model, status, last_seen_at)"
            " VALUES (%s, 'phone', %s, %s, 'active', NOW())"
            " ON CONFLICT (tenant_id, serial_no) DO UPDATE SET last_seen_at = NOW() WHERE field.device.status = 'active'"
            " RETURNING id::text",
            (tenant_id, core_device_id, model[:120]),
        )
        row = cur.fetchone()
    logger.info("core_device_registered", device_id=str(row[0]) if row else None)
    return str(row[0]) if row else ""


async def _core_device_active(url: str) -> bool:
    """Ask core for the device status. Unreachable or malformed answers count as not active."""
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("FIELD_CORE_TIMEOUT_S", "2.0")),
                                     transport=CORE_TRANSPORT) as client:
            res = await client.get(url, headers=dict(CORE_HEADERS))
        return res.status_code == 200 and res.json().get("status") == "active"
    except (httpx.HTTPError, ValueError, AttributeError):
        logger.warning("core_device_status_unavailable")
        return False


async def _core_check(tenant_id: str, field_device_id: str, core_device_id: str | None) -> bool | None:
    """True/False from the configured core device check, None when no check applies."""
    cfg = device_status_template()
    if cfg is None:
        return None
    template, is_core = cfg
    ask = core_device_id if is_core else (core_device_id or field_device_id)
    if not ask:
        return None
    try:
        url = render_device_status_url(template, ask, tenant_id)
    except ValueError:
        logger.error("core_device_status_url_invalid")
        return False
    return await _core_device_active(url)


def _str_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [str(v) for v in value]
    return None


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange_token(request: ExchangeRequest) -> ExchangeResponse:
    """Exchange a core-issued device/session token for a field access token."""
    now = int(datetime.now(UTC).timestamp())
    try:
        claims: dict[str, Any] = await verify_core_jwt(request.device_token)
    except Exception as e:  # any verification problem is a 401, never a fallback
        logger.warning("exchange_token_rejected", error=type(e).__name__)
        raise ERR_AUTH_UNAUTHORIZED from None

    principal_id = str(claims.get("sub") or "")
    tenant_id = str(claims.get("tenant_id") or claims.get("tid") or "")
    roles = claims.get("roles")
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise ERR_AUTH_UNAUTHORIZED from None
    if not principal_id or not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise ERR_AUTH_UNAUTHORIZED
    try:
        mapped = map_roles([str(r) for r in roles], core_role_map())
    except RoleMapError as e:
        logger.error("core_role_map_invalid", problem=str(e))
        raise ERR_CORE_ROLE_MAP_INVALID from None
    if not mapped.field_roles:
        logger.warning("exchange_no_field_role", roles=[str(r) for r in roles][:8])
        raise err_no_field_role([str(r) for r in roles])
    if mapped.ignored:
        logger.info("exchange_roles_ignored", roles=mapped.ignored[:8])
    field_roles = mapped.field_roles
    sites = claims.get("sites", ["*"])
    site_ids = [str(s) for s in sites] if isinstance(sites, list) else ["*"]

    core_permissions: list[str] = []
    if "permissions" in claims:
        perms = _str_list(claims["permissions"])
        if perms is None:
            raise ERR_AUTH_UNAUTHORIZED
        core_permissions = perms
    if "email" in claims and not isinstance(claims["email"], str):
        raise ERR_AUTH_UNAUTHORIZED

    raw_bound = claims.get("device_id") or claims.get("did")
    bound = str(raw_bound) if raw_bound else None
    device_id = request.device_id or bound
    if device_id:
        if request.device_id and request.device_id != bound:
            dev = _field_device(tenant_id, request.device_id)
            if dev is not None and dev[0] != request.device_id:
                dev = None  # an explicit device_id is a field.device id, never a serial number
            if bound and (dev is None or dev[1] != bound):
                raise ERR_AUTH_UNAUTHORIZED  # token bound to a different device
        else:  # the device the token is bound to: a field.device id (P10) or a core device id (serial_no)
            dev = _field_device(tenant_id, device_id)
        if dev is None:
            # A core-bound device field has not seen yet: only the core can vouch for it.
            if not bound or await _core_check(tenant_id, "", bound) is not True:
                raise ERR_DEVICE_REVOKED
            device_id = _register_core_device(tenant_id, bound, str(claims.get("device_model") or "core-device"))
            if not device_id:
                raise ERR_DEVICE_REVOKED
        else:
            if dev[2] != "active":
                raise ERR_DEVICE_REVOKED
            device_id = dev[0]
            if await _core_check(tenant_id, device_id, bound) is False:
                raise ERR_DEVICE_REVOKED

    field_ttl = min(MAX_FIELD_TTL_S, int(claims["exp"]) - now)
    if field_ttl < 1:
        raise ERR_AUTH_UNAUTHORIZED
    access_token = create_dev_token(
        principal_id=principal_id,
        tenant_id=tenant_id,
        roles=field_roles,
        site_ids=site_ids,
        device_id=device_id,
        exp_seconds=field_ttl,
    )
    return ExchangeResponse(
        access_token=access_token,
        expires_in=field_ttl,
        roles=field_roles,
        permissions=expand_permissions(field_roles),
        tenant_id=tenant_id,
        site_ids=site_ids,
        device_id=device_id,
        core_permissions=core_permissions,
        core_roles=mapped.core_roles,
    )
