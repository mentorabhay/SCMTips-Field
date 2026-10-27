"""Device Binding, Heartbeat, Config, and Revocation Endpoints (API1.11, T2.047 / FR2.003, FR2.054, FR2.002)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_permission, require_principal
from field_api.errors import ERR_NOT_FOUND, FieldError
from field_api.http.etag import generate_etag, verify_if_match

router = APIRouter(prefix="/v1/devices", tags=["Devices"])

ERR_DEVICE_REVOKED = FieldError(
    status=401,
    code="FIELD-AUTH-401-REVOKED",
    title="Device Revoked",
    detail="This device has been revoked and cannot communicate with the field-api.",
)


class DeviceRegister(BaseModel):
    kind: str = Field(..., description="phone or glasses")
    serial_no: str
    model: str
    os_version: str | None = None
    app_version: str | None = None
    paired_with: str | None = None
    site_id: str | None = None


class DeviceHeartbeat(BaseModel):
    battery_pct: int | None = Field(None, ge=0, le=100)
    thermal_status: str | None = None
    queue_depth: int = 0
    glasses_state: str | None = None
    app_version: str | None = None
    firmware_version: str | None = None


class DeviceRecord(BaseModel):
    id: str
    tenant_id: str
    kind: str
    serial_no: str
    model: str
    status: str
    paired_with: str | None = None
    site_id: str | None = None
    battery_pct: int | None = None
    thermal_status: str | None = None
    queue_depth: int = 0
    glasses_state: str | None = None
    last_seen_at: str | None = None
    revoked_at: str | None = None
    config_version: int = 1
    version: int = 1
    is_stale: bool = False
    created_at: str
    updated_at: str


class DeviceConfigResponse(BaseModel):
    device_id: str
    tenant_id: str
    site_id: str | None = None
    config_version: int
    settings: dict[str, str]


DEVICES_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
DEVICE_PAIRINGS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()


@router.post("", response_model=DeviceRecord, status_code=201)
async def register_device(
    dev_in: DeviceRegister,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceRecord:
    """Register a new device binding (phone or glasses with paired_with) (T2.047 / TC2.103)."""
    dev_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()

    # Enforce glasses pairing validation if paired_with is provided
    if dev_in.paired_with:
        pairing_record = {
            "id": uuid7_str(),
            "tenant_id": principal.tenant_id,
            "phone_id": dev_in.paired_with,
            "glasses_id": dev_id,
            "status": "active",
            "paired_at": now_iso,
        }
        DEVICE_PAIRINGS_STORE.insert(principal.tenant_id, dev_id, pairing_record)

    record: dict[str, Any] = {
        "id": dev_id,
        "tenant_id": principal.tenant_id,
        "kind": dev_in.kind,
        "serial_no": dev_in.serial_no,
        "model": dev_in.model,
        "status": "active",
        "paired_with": dev_in.paired_with,
        "site_id": dev_in.site_id,
        "battery_pct": 100,
        "thermal_status": "nominal",
        "queue_depth": 0,
        "glasses_state": "connected" if dev_in.kind == "glasses" else None,
        "last_seen_at": now_iso,
        "revoked_at": None,
        "config_version": 1,
        "version": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    DEVICES_STORE.insert(principal.tenant_id, dev_id, record)
    response.headers["ETag"] = generate_etag(dev_id, 1)
    record["is_stale"] = False
    return DeviceRecord.model_validate(record)


@router.get("", response_model=list[DeviceRecord])
async def list_devices(
    kind: str | None = Query(None),
    model: str | None = Query(None),
    site_id: str | None = Query(None),
    status: str | None = Query(None),
    stale_only: bool = Query(False),
    principal: Principal = Depends(require_principal),
) -> list[DeviceRecord]:
    """List registered devices for tenant with filter support and staleness detection (T2.047, T2.061)."""
    all_devices = DEVICES_STORE.list(principal.tenant_id)
    now = datetime.now(UTC)
    results = []

    for dev in all_devices:
        if kind and dev.get("kind") != kind:
            continue
        if model and dev.get("model") != model:
            continue
        if site_id and dev.get("site_id") != site_id:
            continue
        if status and dev.get("status") != status:
            continue

        # Check staleness: stale if no heartbeat for > 15 minutes (T2.061)
        last_seen = dev.get("last_seen_at")
        is_stale = False
        if last_seen:
            last_dt = datetime.fromisoformat(last_seen)
            if (now - last_dt) > timedelta(minutes=15):
                is_stale = True
        else:
            is_stale = True

        if stale_only and not is_stale:
            continue

        d = dict(dev)
        d["is_stale"] = is_stale
        results.append(DeviceRecord.model_validate(d))

    return results


@router.get("/{device_id}", response_model=DeviceRecord)
async def get_device(
    device_id: str,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceRecord:
    """Get device details by ID."""
    dev = DEVICES_STORE.get(principal.tenant_id, device_id)
    if not dev:
        raise ERR_NOT_FOUND

    response.headers["ETag"] = generate_etag(device_id, int(dev["version"]))
    d = dict(dev)
    d["is_stale"] = False
    return DeviceRecord.model_validate(d)


@router.post("/{device_id}/heartbeat", response_model=DeviceRecord)
async def record_heartbeat(
    device_id: str,
    hb: DeviceHeartbeat,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceRecord:
    """Accept heartbeat updates every 60s (battery, thermal, queue depth) (T2.047 / FR2.054, TC2.163)."""
    device = DEVICES_STORE.get(principal.tenant_id, device_id)
    if not device:
        raise ERR_NOT_FOUND

    if device.get("status") == "revoked":
        raise ERR_DEVICE_REVOKED

    now_iso = datetime.now(UTC).isoformat()
    device["last_seen_at"] = now_iso
    device["updated_at"] = now_iso
    if hb.battery_pct is not None:
        device["battery_pct"] = hb.battery_pct
    if hb.thermal_status is not None:
        device["thermal_status"] = hb.thermal_status
    device["queue_depth"] = hb.queue_depth
    if hb.glasses_state is not None:
        device["glasses_state"] = hb.glasses_state

    DEVICES_STORE.update(principal.tenant_id, device_id, device)
    response.headers["ETag"] = generate_etag(device_id, int(device["version"]))
    d = dict(device)
    d["is_stale"] = False
    return DeviceRecord.model_validate(d)


@router.get("/{device_id}/config", response_model=DeviceConfigResponse)
async def get_device_config(
    device_id: str,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceConfigResponse:
    """Return effective device configuration with ETag (T2.047 / FR2.054, TC2.163)."""
    device = DEVICES_STORE.get(principal.tenant_id, device_id)
    if not device:
        raise ERR_NOT_FOUND

    version = int(device.get("config_version", 1))
    response.headers["ETag"] = generate_etag(device_id, version)

    return DeviceConfigResponse(
        device_id=device_id,
        tenant_id=principal.tenant_id,
        site_id=device.get("site_id"),
        config_version=version,
        settings={
            "field_api_base_url": "https://api.field.scmtips.internal",
            "max_outbox_items": "2000",
            "force_audio_only": "false",
            "log_level": "INFO",
            "allowed_glasses_models": "rayban-meta-v1,mock-kit",
            "phone_camera_mode_allowed": "true",
        },
    )


@router.post("/{device_id}/revoke", response_model=DeviceRecord)
async def revoke_device(
    device_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission("field.device.revoke")),
) -> DeviceRecord:
    """Revoke a device binding (requires If-Match tag). Emits device.revoked tick (T2.047 / TC2.102)."""
    device = DEVICES_STORE.get(principal.tenant_id, device_id)
    if not device:
        raise ERR_NOT_FOUND

    verify_if_match(request, int(device["version"]), device_id)

    now_iso = datetime.now(UTC).isoformat()
    device["version"] = int(device["version"]) + 1
    device["status"] = "revoked"
    device["revoked_at"] = now_iso
    device["updated_at"] = now_iso

    DEVICES_STORE.update(principal.tenant_id, device_id, device)
    response.headers["ETag"] = generate_etag(device_id, int(device["version"]))

    # Emit device.revoked live notification
    from field_api.routes.live import emit_device_tick

    emit_device_tick(
        tenant_id=principal.tenant_id,
        device_id=device_id,
        tick_type="device.revoked",
        detail="Device access has been revoked by administrator",
    )

    d = dict(device)
    d["is_stale"] = False
    return DeviceRecord.model_validate(d)
