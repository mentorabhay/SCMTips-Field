"""Device Binding and Revocation Endpoints (API1.11)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_permission, require_principal
from field_api.errors import ERR_NOT_FOUND
from field_api.http.etag import generate_etag, verify_if_match

router = APIRouter(prefix="/v1/devices", tags=["Devices"])


class DeviceRegister(BaseModel):
    kind: str = Field(..., description="phone or glasses")
    serial_no: str
    model: str
    os_version: str | None = None
    app_version: str | None = None


class DeviceRecord(BaseModel):
    id: str
    tenant_id: str
    kind: str
    serial_no: str
    model: str
    status: str
    version: int
    created_at: str
    updated_at: str


DEVICES_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()


@router.post("", response_model=DeviceRecord, status_code=201)
async def register_device(
    dev_in: DeviceRegister,
    response: Response,
    principal: Principal = Depends(require_principal),
) -> DeviceRecord:
    """Register a new device binding."""
    dev_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()
    record: dict[str, Any] = {
        "id": dev_id,
        "tenant_id": principal.tenant_id,
        "kind": dev_in.kind,
        "serial_no": dev_in.serial_no,
        "model": dev_in.model,
        "status": "active",
        "version": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    DEVICES_STORE.insert(principal.tenant_id, dev_id, record)
    response.headers["ETag"] = generate_etag(dev_id, 1)
    return DeviceRecord.model_validate(record)


@router.post("/{device_id}/revoke", response_model=DeviceRecord)
async def revoke_device(
    device_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission("field.device.revoke")),
) -> DeviceRecord:
    """Revoke a device binding (requires If-Match tag)."""
    device = DEVICES_STORE.get(principal.tenant_id, device_id)
    if not device:
        raise ERR_NOT_FOUND

    verify_if_match(request, int(device["version"]), device_id)

    device["version"] = int(device["version"]) + 1
    device["status"] = "revoked"
    device["updated_at"] = datetime.now(UTC).isoformat()

    DEVICES_STORE.update(principal.tenant_id, device_id, device)
    response.headers["ETag"] = generate_etag(device_id, int(device["version"]))
    return DeviceRecord.model_validate(device)
