"""Consent API Endpoints and Privacy Gates (Task T2.048 / FR2.064, TC2.154)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_principal

router = APIRouter(prefix="/v1/consents", tags=["Consents"])

CONSENTS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()


class ConsentRequest(BaseModel):
    site_id: str
    user_id: str
    device_id: str
    consent_version: str = "v1"
    consent_type: str = "site_and_bystander_privacy"
    granted: bool = True


class ConsentRecord(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    user_id: str
    device_id: str
    consent_version: str
    consent_type: str
    granted: bool
    granted_at: str | None = None
    withdrawn_at: str | None = None
    created_at: str


@router.post("", response_model=ConsentRecord, status_code=201)
async def record_consent(
    req: ConsentRequest,
    principal: Principal = Depends(require_principal),
) -> ConsentRecord:
    """Record or update site privacy and bystander consent (T2.048 / TC2.154)."""
    now_iso = datetime.now(UTC).isoformat()
    record_id = uuid7_str()

    record: dict[str, Any] = {
        "id": record_id,
        "tenant_id": principal.tenant_id,
        "site_id": req.site_id,
        "user_id": req.user_id,
        "device_id": req.device_id,
        "consent_version": req.consent_version,
        "consent_type": req.consent_type,
        "granted": req.granted,
        "granted_at": now_iso if req.granted else None,
        "withdrawn_at": now_iso if not req.granted else None,
        "created_at": now_iso,
    }

    # Key by (tenant, site_id, user_id, device_id)
    key = f"{req.site_id}:{req.user_id}:{req.device_id}"
    CONSENTS_STORE.insert(principal.tenant_id, key, record)
    return ConsentRecord.model_validate(record)


def has_active_consent(tenant_id: str, site_id: str, user_id: str, device_id: str) -> bool:
    """Check if valid, non-withdrawn consent exists for (site, user, device) (FR2.064, TC2.154)."""
    key = f"{site_id}:{user_id}:{device_id}"
    record = CONSENTS_STORE.get(tenant_id, key)
    return bool(record and record.get("granted") is True and record.get("withdrawn_at") is None)
