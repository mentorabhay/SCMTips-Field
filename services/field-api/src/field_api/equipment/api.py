"""FastAPI Router for Equipment Events, History, and Reversal (WS4.4).

Exposes:
- POST /v1/equipment-events (API4.08)
- POST /v1/equipment-events/{id}/reverse (API4.09)
- GET  /v1/equipment/{serial_no}/history (API4.10)
"""

from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.deps import require_principal
from field_api.equipment.events import record_equipment_event
from field_api.equipment.history import (
    SingleLocationViolationError,
    get_serial_history,
)
from field_api.equipment.reverse import (
    EquipmentAlreadyReversedError,
    reverse_equipment_event,
)

router = APIRouter(tags=["equipment", "equipment-events"])


class EquipmentEventRequest(BaseModel):
    event_type: str = Field(..., description="'install', 'dismantle', 'replace', or 'move'")
    serial_no: str
    site_id: str
    location_id: Optional[str] = None
    material: Optional[str] = None
    old_serial_no: Optional[str] = None
    task_id: Optional[str] = None
    evidence_crop_ref: Optional[str] = None
    notes: Optional[str] = None


class ReverseEventRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/v1/equipment-events", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def api_record_equipment_event(
    body: EquipmentEventRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.08: Execute equipment lifecycle event (install, dismantle, replace, move)."""
    try:
        return record_equipment_event(
            tenant_id=principal.tenant_id,
            event_type=body.event_type,
            serial_no=body.serial_no,
            site_id=body.site_id,
            location_id=body.location_id,
            material=body.material,
            old_serial_no=body.old_serial_no,
            task_id=body.task_id,
            created_by=principal.id,
            evidence_crop_ref=body.evidence_crop_ref,
            notes=body.notes,
            idempotency_key=idempotency_key,
        )
    except SingleLocationViolationError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": e.code, "message": str(e), "current_location": e.current_location_id},
        )
    except ValueError as e:
        if "400" in str(e) or "NOT-INSTALLED" in str(e):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/v1/equipment-events/{id}/reverse", response_model=dict[str, Any])
def api_reverse_equipment_event(
    id: str,
    body: Optional[ReverseEventRequest] = None,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.09: Reverse a posted equipment event with compensating operation and ref_doc_no."""
    try:
        reason = body.reason if body else None
        return reverse_equipment_event(
            tenant_id=principal.tenant_id,
            event_ref=id,
            reversed_by=principal.id,
            reason=reason,
        )
    except EquipmentAlreadyReversedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": e.code, "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/v1/equipment/{serial_no}/history", response_model=list[dict[str, Any]])
def api_get_equipment_history(
    serial_no: str,
    principal: Principal = Depends(require_principal),
) -> list[dict[str, Any]]:
    """API4.10: Retrieve full chronological history of serial events."""
    return get_serial_history(tenant_id=principal.tenant_id, serial_no=serial_no)
