"""Devices (API1.11 / API2.01-2.05) on Postgres with RLS (C4; was an in-process store).

- register a phone, or glasses paired to a phone (device_pairing; 409 if the phone is already paired
  and replace is false; 403 if the phone is revoked)
- heartbeat updates battery / thermal / queue depth / glasses state; a revoked device gets 403
- config is versioned with ETag / If-None-Match (304)
- revoke requires If-Match, records revoked_at, writes a device.revoked notification; revoked
  device tokens are refused by authentication (deps.get_principal), closing T1.038
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission, require_principal
from field_api.errors import FieldError
from field_api.http.etag import generate_etag, verify_if_match
from field_api.rows import fetch_dict, fetch_dicts

router = APIRouter(prefix="/v1/devices", tags=["Devices"])

STALE_AFTER = timedelta(minutes=15)
COLS = ("id, tenant_id, kind, serial_no, model, os_version, app_version, firmware_version, status, paired_with, "
        "battery_pct, thermal_status, queue_depth, glasses_state, last_seen_at, revoked_at, config_version, "
        "version, created_at, updated_at")
ERR_DEV_NOT_FOUND = FieldError(code="FIELD-DEV-404-NOT-FOUND", status=404, title="Device not found")
ERR_DEV_REVOKED = FieldError(code="FIELD-DEV-403-REVOKED", status=403, title="Device revoked")
ERR_DEV_EXISTS = FieldError(code="FIELD-DEV-409-EXISTS", status=409, title="Device already bound")
ERR_ALREADY_PAIRED = FieldError(code="FIELD-DEV-409-ALREADY-PAIRED", status=409,
                                title="Phone already has an active glasses pairing")
ERR_ALREADY_REVOKED = FieldError(code="FIELD-DEV-409-ALREADY-REVOKED", status=409, title="Device already revoked")


class DeviceRegister(BaseModel):
    kind: Literal["phone", "glasses"]
    serial_no: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)
    os_version: str | None = None
    app_version: str | None = None
    firmware_version: str | None = None
    paired_with: str | None = Field(None, description="phone device id (glasses only)")
    replace: bool = False


class DeviceHeartbeat(BaseModel):
    battery_pct: int | None = Field(None, ge=0, le=100)
    thermal_status: str | None = Field(None, max_length=32)
    queue_depth: int = Field(0, ge=0)
    glasses_state: str | None = Field(None, max_length=32)
    app_version: str | None = None
    firmware_version: str | None = None


class DeviceRecord(BaseModel):
    id: str
    tenant_id: str
    kind: str
    serial_no: str
    model: str
    os_version: str | None = None
    app_version: str | None = None
    firmware_version: str | None = None
    status: str
    paired_with: str | None = None
    pairing_id: str | None = None
    battery_pct: int | None = None
    thermal_status: str | None = None
    queue_depth: int | None = 0
    glasses_state: str | None = None
    last_seen_at: str | None = None
    revoked_at: str | None = None
    config_version: int = 1
    version: int = 1
    is_stale: bool = False
    created_at: str
    updated_at: str


class RevokeIn(BaseModel):
    reason: str = Field("unspecified", max_length=200)


def _stale(row: dict[str, Any]) -> bool:
    seen = row.get("last_seen_at")
    return seen is None or datetime.now(UTC) - datetime.fromisoformat(seen) > STALE_AFTER


def _record(row: dict[str, Any], pairing_id: str | None = None) -> DeviceRecord:
    return DeviceRecord.model_validate({**row, "is_stale": _stale(row), "pairing_id": pairing_id,
                                        "config_version": row.get("config_version") or 1})


def _get(cur: Any, device_id: str) -> dict[str, Any]:
    cur.execute(f"SELECT {COLS} FROM field.device WHERE id = %s::uuid", (device_id,))  # noqa: S608
    row = fetch_dict(cur)
    if not row:
        raise ERR_DEV_NOT_FOUND
    return row


@router.post("", response_model=DeviceRecord, status_code=201)
async def register_device(
    dev_in: DeviceRegister,
    response: Response,
    principal: Principal = Depends(require_permission("field.device.register")),
) -> DeviceRecord:
    if dev_in.kind == "phone" and dev_in.paired_with:
        raise FieldError(code="FIELD-HTTP-422-VALIDATION", status=422, title="Only glasses pair with a phone")
    pairing_id = None
    try:
        with principal_tx(principal) as cur:
            if dev_in.paired_with:
                phone = _get(cur, dev_in.paired_with)
                if phone["kind"] != "phone":
                    raise FieldError(code="FIELD-HTTP-422-VALIDATION", status=422, title="paired_with must be a phone")
                if phone["status"] != "active":
                    raise ERR_DEV_REVOKED
                cur.execute("SELECT id FROM field.device_pairing WHERE phone_id = %s::uuid AND status = 'active'"
                            " FOR UPDATE", (dev_in.paired_with,))
                existing = cur.fetchall()
                if existing and not dev_in.replace:
                    raise ERR_ALREADY_PAIRED
                cur.execute("UPDATE field.device_pairing SET status = 'unpaired', unpaired_at = NOW()"
                            " WHERE phone_id = %s::uuid AND status = 'active'", (dev_in.paired_with,))
            cur.execute(
                f"""
                INSERT INTO field.device (tenant_id, kind, serial_no, model, os_version, app_version, firmware_version,
                       status, paired_with, glasses_state, last_seen_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, NOW()) RETURNING {COLS}
                """,  # noqa: S608
                (principal.tenant_id, dev_in.kind, dev_in.serial_no, dev_in.model, dev_in.os_version,
                 dev_in.app_version, dev_in.firmware_version, dev_in.paired_with,
                 "connected" if dev_in.kind == "glasses" else None),
            )
            row = fetch_dict(cur) or {}
            if dev_in.paired_with:
                cur.execute(
                    "INSERT INTO field.device_pairing (tenant_id, phone_id, glasses_id, status, paired_at)"
                    " VALUES (%s, %s, %s, 'active', NOW()) RETURNING id",
                    (principal.tenant_id, dev_in.paired_with, row["id"]),
                )
                pairing_id = str(cur.fetchone()[0])
    except psycopg.errors.UniqueViolation as e:
        raise ERR_DEV_EXISTS from e
    response.headers["ETag"] = generate_etag(row["id"], row["version"])
    return _record(row, pairing_id)


@router.get("", response_model=list[DeviceRecord])
async def list_devices(
    kind: str | None = Query(None),
    model: str | None = Query(None),
    status: str | None = Query(None),
    stale_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission("field.device.read")),
) -> list[DeviceRecord]:
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT {COLS} FROM field.device
             WHERE (%s::text IS NULL OR kind = %s) AND (%s::text IS NULL OR model = %s)
               AND (%s::text IS NULL OR status = %s)
             ORDER BY id LIMIT %s
            """,  # noqa: S608
            (kind, kind, model, model, status, status, limit),
        )
        rows = fetch_dicts(cur)
    out = [_record(r) for r in rows]
    return [d for d in out if d.is_stale] if stale_only else out


@router.get("/{device_id}", response_model=DeviceRecord)
async def get_device(
    device_id: str,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceRecord:
    with principal_tx(principal) as cur:
        row = _get(cur, device_id)
    response.headers["ETag"] = generate_etag(device_id, int(row["version"]))
    return _record(row)


@router.post("/{device_id}/heartbeat")
async def record_heartbeat(
    device_id: str,
    hb: DeviceHeartbeat,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        row = _get(cur, device_id)
        if row["status"] != "active":
            raise ERR_DEV_REVOKED
        cur.execute(
            """
            UPDATE field.device SET last_seen_at = NOW(), updated_at = NOW(), queue_depth = %s,
                   battery_pct = COALESCE(%s, battery_pct), thermal_status = COALESCE(%s, thermal_status),
                   glasses_state = COALESCE(%s, glasses_state), app_version = COALESCE(%s, app_version),
                   firmware_version = COALESCE(%s, firmware_version)
             WHERE id = %s::uuid RETURNING config_version
            """,
            (hb.queue_depth, hb.battery_pct, hb.thermal_status, hb.glasses_state, hb.app_version,
             hb.firmware_version, device_id),
        )
        cv = cur.fetchone()
    return {"config_version": int(cv[0]) if cv and cv[0] else 1}


@router.get("/{device_id}/config")
async def get_device_config(
    device_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> Any:
    with principal_tx(principal) as cur:
        row = _get(cur, device_id)
    if row["status"] != "active":
        raise ERR_DEV_REVOKED
    version = int(row.get("config_version") or 1)
    etag = generate_etag(device_id, version)
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    # Spec API2.04 keys. Gen 2 glasses have no display: lens prompts are spoken (audio_only).
    return {
        "device_id": device_id,
        "version": version,
        "config_version": version,
        "preview_fps": 15,
        "auto_capture": True,
        "walking_quiet": False,
        "phone_camera_mode_allowed": True,
        "voice_locale": "en",
        "voice_conf_floor": 0.80,
        "confirm_timeout_s": 10,
        "outbox_max_items": 2000,
        "audio_only_prompts": True,
    }


@router.post("/{device_id}/revoke", response_model=DeviceRecord)
async def revoke_device(
    device_id: str,
    request: Request,
    response: Response,
    body: RevokeIn | None = None,
    principal: Principal = Depends(require_permission("field.device.revoke")),
) -> DeviceRecord:
    with principal_tx(principal) as cur:
        row = _get(cur, device_id)
        if row["status"] == "revoked":
            raise ERR_ALREADY_REVOKED
        verify_if_match(request, int(row["version"]), device_id)
        cur.execute(
            f"""
            UPDATE field.device SET status = 'revoked', revoked_at = NOW(), version = version + 1, updated_at = NOW()
             WHERE id = %s::uuid RETURNING {COLS}
            """,  # noqa: S608
            (device_id,),
        )
        row = fetch_dict(cur) or {}
        cur.execute("UPDATE field.device_pairing SET status = 'unpaired', unpaired_at = NOW()"
                    " WHERE (phone_id = %s::uuid OR glasses_id = %s::uuid) AND status = 'active'",
                    (device_id, device_id))
        cur.execute(
            "INSERT INTO field.device_notification (tenant_id, device_id, event_id, tick_type, payload, expires_at)"
            " VALUES (%s, %s, gen_random_uuid()::text, 'device.revoked', %s, NOW() + INTERVAL '7 days')",
            (principal.tenant_id, device_id, Jsonb({"reason": (body.reason if body else "unspecified")})),
        )
    response.headers["ETag"] = generate_etag(device_id, int(row["version"]))
    return _record(row)
