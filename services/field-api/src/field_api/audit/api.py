"""Audit, Progress, Reconciliation, and Mismatch FastApi Router (WS4.3).

Exposes:
- GET  /v1/audits/{task_id}/progress (API4.07)
- POST /v1/tasks/{id}/audit/reconcile (API4.06)
- POST /v1/tasks/{id}/audit/signoff
- POST /v1/tasks/{id}/audit/findings/missing
- POST /v1/tasks/{id}/audit/findings/unknown
- GET  /v1/mismatches (API4.16)
- POST /v1/mismatches/{id}/decision (API4.16)
- POST /v1/mismatches/approvals/{id}/approve
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from field_api.audit.decisions import (
    MismatchAlreadyResolvedError,
    SoDViolationError,
    approve_mismatch_decision,
    submit_mismatch_decision,
)
from field_api.audit.findings_api import mark_item_missing, record_unknown_equipment
from field_api.audit.mismatch_api import list_mismatches
from field_api.audit.progress import get_audit_progress
from field_api.audit.reconcile import run_audit_reconciliation
from field_api.audit.signoff import AuditSignoffConflict, sign_off_audit_task
from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.deps import require_principal
from pydantic import BaseModel

router = APIRouter(tags=["audits", "reconciliation", "mismatches"])


# Request models
class ReconcileRequest(BaseModel):
    tower_location_id: str | None = None


class SignoffRequest(BaseModel):
    waiver_reason: str | None = None
    supervisor_waiver: bool = False


class MissingFindingRequest(BaseModel):
    expected_serial: str
    equipment_class: str
    reason: str
    location_id: str | None = None


class UnknownFindingRequest(BaseModel):
    found_serial: str
    equipment_class: str
    location_id: str | None = None
    crop_ref: str | None = None


class MismatchDecisionRequest(BaseModel):
    decision: str
    note: str | None = None
    capturing_technician_id: str | None = None


@router.get("/v1/audits/{task_id}/progress", response_model=dict[str, Any])
def api_get_audit_progress(
    task_id: str,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.07: Audit completeness per site, tower, sector, and level."""
    try:
        return get_audit_progress(tenant_id=principal.tenant_id, task_id=task_id)
    except ValueError as e:
        if "404" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/v1/tasks/{id}/audit/reconcile", response_model=dict[str, Any])
def api_reconcile_audit(
    id: str,
    body: ReconcileRequest | None = None,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.06: Run reconciliation for a tower or whole audit task."""
    try:
        tower_loc_id = body.tower_location_id if body else None
        return run_audit_reconciliation(
            tenant_id=principal.tenant_id,
            task_id=id,
            tower_location_id=tower_loc_id,
        )
    except ValueError as e:
        if "FIELD-AUD-409-SIGNED" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        if "404" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/v1/tasks/{id}/audit/signoff", response_model=dict[str, Any])
def api_signoff_audit(
    id: str,
    body: SignoffRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Sign-off an audit task enforcing completeness or supervisor waiver (FR4.028 / TC4.122).

    A waiver is a supervisor decision: it needs field.override.grant. (Previously any
    authenticated user could send supervisor_waiver=true.)
    """
    if body.supervisor_waiver and not has_permission(principal.permissions, "field.override.grant"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "FIELD-AUTH-403-FORBIDDEN", "message": "A sign-off waiver needs a supervisor"},
        )
    try:
        return sign_off_audit_task(
            tenant_id=principal.tenant_id,
            task_id=id,
            signed_by=principal.id,
            waiver_reason=body.waiver_reason,
            supervisor_waiver=body.supervisor_waiver,
        )
    except AuditSignoffConflict as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": e.error_code,
                "message": str(e),
                "unresolved_count": e.unresolved_count,
            },
        )
    except ValueError as e:
        if "404" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        if "409" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/v1/tasks/{id}/audit/findings/missing", response_model=dict[str, Any])
def api_mark_missing_finding(
    id: str,
    body: MissingFindingRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Record an expected equipment item as missing (FR4.023 / TC4.121)."""
    try:
        return mark_item_missing(
            tenant_id=principal.tenant_id,
            task_id=id,
            expected_serial=body.expected_serial,
            equipment_class=body.equipment_class,
            reason=body.reason,
            location_id=body.location_id,
            reported_by=principal.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/v1/tasks/{id}/audit/findings/unknown", response_model=dict[str, Any])
def api_record_unknown_finding(
    id: str,
    body: UnknownFindingRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Record unknown unexpected equipment found on tower (FR4.022 / TC4.120)."""
    try:
        return record_unknown_equipment(
            tenant_id=principal.tenant_id,
            task_id=id,
            found_serial=body.found_serial,
            equipment_class=body.equipment_class,
            location_id=body.location_id,
            crop_ref=body.crop_ref,
            reported_by=principal.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/v1/mismatches", response_model=dict[str, Any])
def api_list_mismatches(
    site_id: str | None = Query(None),
    finding_class: str | None = Query(None, alias="class"),
    verify_status: str | None = Query(None),
    min_age_h: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.16: Mismatch queue with filters and cursor pagination (FR4.064)."""
    return list_mismatches(
        tenant_id=principal.tenant_id,
        site_id=site_id,
        finding_class=finding_class,
        verify_status=verify_status,
        min_age_h=min_age_h,
        limit=limit,
        cursor=cursor,
    )


@router.post("/v1/mismatches/{id}/decision", response_model=dict[str, Any])
def api_submit_mismatch_decision(
    id: str,
    body: MismatchDecisionRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.16: Submit mismatch decision with Segregation of Duties (SoD) (FR4.027 / TC4.123)."""
    try:
        return submit_mismatch_decision(
            tenant_id=principal.tenant_id,
            finding_id=id,
            decider_id=principal.id,
            decision=body.decision,
            note=body.note,
            capturing_technician_id=body.capturing_technician_id,
        )
    except SoDViolationError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": e.error_code, "message": str(e)},
        )
    except MismatchAlreadyResolvedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": e.error_code, "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/v1/mismatches/approvals/{id}/approve", response_model=dict[str, Any])
def api_approve_mismatch(
    id: str,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Approve a pending mismatch decision."""
    try:
        return approve_mismatch_decision(
            tenant_id=principal.tenant_id,
            approval_id=id,
            approver_id=principal.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
