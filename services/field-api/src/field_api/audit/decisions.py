"""Mismatch Decision and Core Approvals Service (Task T4.026 / FR4.027, FR4.067 / TC4.123 / API4.16).

Enforces Segregation of Duties (SoD: decider cannot be capturing technician),
routes update_erp and record_move to core approvals, and logs audit events to outbox.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Optional
import structlog

from field_api.db import get_conn

logger = structlog.get_logger(__name__)

ALLOWED_DECISIONS = {"re_capture", "accept_erp", "update_erp", "record_move", "waived"}


class SoDViolationError(PermissionError):
    """Raised when the decider is the same technician who captured the serial (FR4.027 / TC4.123)."""

    def __init__(self, message: str = "FIELD-EXC-403-SOD: decider cannot be the capturing technician") -> None:
        super().__init__(message)
        self.error_code = "FIELD-EXC-403-SOD"


class MismatchAlreadyResolvedError(ValueError):
    """Raised when attempting to decide an already resolved finding (API4.16)."""

    def __init__(self, message: str = "FIELD-EXC-409-RESOLVED: finding is already resolved") -> None:
        super().__init__(message)
        self.error_code = "FIELD-EXC-409-RESOLVED"


def submit_mismatch_decision(
    tenant_id: str,
    finding_id: str,
    decider_id: str,
    decision: str,
    note: Optional[str] = None,
    capturing_technician_id: Optional[str] = None,
) -> dict[str, Any]:
    """Submit a decision for an unresolved audit finding with SoD and approval rules (API4.16)."""
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(
            f"FIELD-EXC-422-DECISION: Invalid decision '{decision}'. Must be one of: {sorted(ALLOWED_DECISIONS)}"
        )

    # Enforce Segregation of Duties (SoD)
    if capturing_technician_id and decider_id == capturing_technician_id:
        logger.warn("sod_violation_attempted", finding_id=finding_id, user=decider_id)
        raise SoDViolationError()

    now = datetime.now(UTC)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch finding
            cur.execute(
                """
                SELECT
                    af.id, af.task_id, af.site_id, af.status,
                    af.class, af.expected_serial, af.found_serial,
                    af.decision
                FROM field.audit_finding af
                WHERE af.tenant_id = %s AND af.id = %s;
                """,
                (tenant_id, finding_id),
            )
            finding_row = cur.fetchone()
            if not finding_row:
                raise ValueError(f"FIELD-EXC-404: Finding {finding_id} not found")

            task_id = finding_row[1]
            site_id = finding_row[2]
            current_status = finding_row[3]
            f_class = finding_row[4]
            exp_serial = finding_row[5]
            found_serial = finding_row[6]

            if current_status == "resolved":
                raise MismatchAlreadyResolvedError()

            # 2. Check if decision requires approval (update_erp, record_move)
            requires_approval = decision in ("update_erp", "record_move")
            new_status = "awaiting_approval" if requires_approval else "resolved"
            approval_id: Optional[str] = None

            if requires_approval:
                approval_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO field.approval_request (
                        id, tenant_id, task_id, approval_type, threshold_val,
                        status, requested_by, reason
                    ) VALUES (
                        %s, %s, %s, 'tower_mismatch', 1.00,
                        'pending', %s, %s
                    );
                    """,
                    (
                        approval_id,
                        tenant_id,
                        task_id,
                        decider_id,
                        note or f"Decision {decision} for {f_class}",
                    ),
                )

            # 3. Update audit finding
            cur.execute(
                """
                UPDATE field.audit_finding
                SET decision = %s,
                    decided_by = %s,
                    approval_ref = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (
                    decision,
                    decider_id,
                    approval_id,
                    new_status,
                    finding_id,
                ),
            )

            # 4. Emit audit event to outbox (FR4.067)
            audit_payload = {
                "finding_id": str(finding_id),
                "task_id": str(task_id),
                "site_id": str(site_id),
                "decision": decision,
                "decided_by": decider_id,
                "note": note,
                "requires_approval": requires_approval,
                "approval_id": approval_id,
                "status": new_status,
                "timestamp": now.isoformat(),
            }
            cur.execute(
                """
                INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, 'field.mismatch.decision', %s);
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    str(finding_id),
                    json.dumps(audit_payload, default=str),
                ),
            )

        conn.commit()

    return {
        "finding_id": str(finding_id),
        "decision": decision,
        "status": new_status,
        "requires_approval": requires_approval,
        "approval_id": approval_id,
        "decided_by": decider_id,
    }


def approve_mismatch_decision(
    tenant_id: str,
    approval_id: str,
    approver_id: str,
) -> dict[str, Any]:
    """Approve a pending mismatch decision and resolve the linked finding."""
    now = datetime.now(UTC)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Update approval request
            cur.execute(
                """
                UPDATE field.approval_request
                SET status = 'approved',
                    approved_by = %s,
                    decided_at = NOW()
                WHERE tenant_id = %s AND id = %s AND status = 'pending'
                RETURNING task_id, reason;
                """,
                (approver_id, tenant_id, approval_id),
            )
            appr_row = cur.fetchone()
            if not appr_row:
                raise ValueError(f"FIELD-APPR-404: Approval {approval_id} not found or not pending")

            task_id = str(appr_row[0])

            # 2. Update linked audit finding to resolved
            cur.execute(
                """
                UPDATE field.audit_finding
                SET status = 'resolved',
                    updated_at = NOW()
                WHERE tenant_id = %s AND approval_ref = %s
                RETURNING id, decision;
                """,
                (tenant_id, approval_id),
            )
            f_row = cur.fetchone()
            finding_id = str(f_row[0]) if f_row else None
            decision = f_row[1] if f_row else None

            # 3. Emit approval granted and mismatch resolved events
            cur.execute(
                """
                INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, 'field.mismatch.resolved', %s);
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    finding_id or approval_id,
                    json.dumps({
                        "approval_id": approval_id,
                        "finding_id": finding_id,
                        "approver_id": approver_id,
                        "decision": decision,
                        "timestamp": now.isoformat(),
                    }, default=str),
                ),
            )

        conn.commit()

    return {
        "approval_id": approval_id,
        "finding_id": finding_id,
        "status": "resolved",
        "approved_by": approver_id,
    }
