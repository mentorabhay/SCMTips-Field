"""Audit Report & Evidence Gate API (Task T4.060 / API4.17 / TC4.153 / FR4.061).

Exposes:
- POST /v1/audits/{task_id}/report (API4.17 - request PDF or CSV export)
- GET  /v1/reports/{id}
- GET  /v1/reports/{id}/download
- GET  /v1/evidence/{id} (TC4.153 - signed authenticated evidence endpoint)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from field_api.auth.jwt import Principal
from field_api.crops import crop_store
from field_api.db import get_conn, tenant_tx
from field_api.deps import get_principal, require_principal
from field_worker.jobs.audit_report import (
    generate_audit_report,
    verify_signed_evidence_url,
)
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Audit Reports & Authenticated Evidence"])


class AuditReportRequest(BaseModel):
    format: str = Field("csv", description="'csv' or 'pdf'")


@router.post(
    "/v1/audits/{task_id}/report",
    status_code=status.HTTP_200_OK,
    summary="Request PDF or CSV audit report export (API4.17)",
)
def api_request_audit_report(
    task_id: str,
    body: AuditReportRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """API4.17: Generate audit findings report with authenticated evidence links."""
    fmt = (body.format if body else "csv").lower()
    res = generate_audit_report(
        tenant_id=principal.tenant_id,
        task_id=task_id,
        report_format=fmt,
        created_by=principal.id,
    )
    return {
        "report_id": res["report_id"],
        "status": res["status"],
        "format": res["format"],
        "size_bytes": res["file_size_bytes"],
        "sha256": res["sha256_hash"],
        "download_url": res["download_url"],
    }


@router.get(
    "/v1/reports/{id}",
    status_code=status.HTTP_200_OK,
    summary="Get audit report metadata",
)
def api_get_audit_report_metadata(
    id: str,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (principal.tenant_id,))
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true);", (principal.tenant_id,)
            )
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                SELECT id, task_id, format, status, file_size_bytes, sha256_hash,
                       download_url, created_at, expires_at
                FROM field.audit_report
                WHERE tenant_id = %s AND id = %s;
                """,
                (principal.tenant_id, id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error_code": "FIELD-RPT-404", "message": f"Report '{id}' not found"},
                )

    return {
        "id": str(row[0]),
        "task_id": str(row[1]),
        "format": row[2],
        "status": row[3],
        "file_size_bytes": row[4],
        "sha256": row[5],
        "download_url": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
        "expires_at": row[8].isoformat() if row[8] else None,
    }


@router.get(
    "/v1/evidence/{id}",
    summary="Access authenticated audit evidence (TC4.153)",
)
def api_access_evidence(
    id: str,
    tenant: str | None = Query(None),
    exp: int | None = Query(None),
    sig: str | None = Query(None),
    principal: Principal | None = Depends(get_principal),
) -> Response:
    """TC4.153: Evidence access gate. Requires either valid tenant bearer session OR valid HMAC signature."""
    # Case 1: Authenticated via bearer session
    if principal is not None:
        if tenant and tenant != principal.tenant_id:
            # Cross-tenant access attempt: forbidden
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "FIELD-EVD-404-CROSS-TENANT",
                    "message": "Evidence not found in tenant realm",
                },
            )
        target_tenant = principal.tenant_id
    elif tenant and exp and sig:
        # Case 2: Authenticated via signed token
        if not verify_signed_evidence_url(
            tenant_id=tenant, evidence_id=id, expires_at_timestamp=exp, provided_signature=sig
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "FIELD-EVD-401-INVALID-TOKEN",
                    "message": "Invalid or expired evidence signature",
                },
            )
        target_tenant = tenant
    else:
        # Unauthenticated: no token and no session
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "FIELD-EVD-401-UNAUTHENTICATED",
                "message": "Valid session or signed URL token required",
            },
        )

    # The evidence itself: the stored (blurred) crop of this tenant, read under RLS. Unknown or
    # foreign ids are 404; expired crops (retention, no legal hold) are 410. (Previously a constant
    # 1x1 PNG was returned for any id.)
    try:
        uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error_code": "FIELD-EVD-404-NOT-FOUND", "message": "Evidence not found"}) from None
    with tenant_tx(target_tenant, ("*",)) as cur:
        cur.execute("SELECT crop_s3_uri, retention_until, is_legal_hold FROM field.capture_evidence WHERE id = %s::uuid",
                    (id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error_code": "FIELD-EVD-404-NOT-FOUND", "message": "Evidence not found"})
    uri, until, hold = row
    store = crop_store()
    if (datetime.now(UTC) > until and not hold) or not store.exists(uri):
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail={"error_code": "FIELD-EVD-410-EXPIRED", "message": "Evidence deleted by retention"})
    return Response(
        content=store.get(uri),
        media_type="image/jpeg",
        headers={"X-Tenant-Id": target_tenant, "X-Evidence-Id": id, "Cache-Control": "private, no-store"},
    )
