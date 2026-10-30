"""Audit Sign-off Enforcement Engine (Task T4.018 / FR4.028 / TC4.122).

Enforces sign-off rule: Sign-off allowed only when every expected line is captured,
explained by an erp_only finding with valid reason, or waived by a supervisor with reason.
Returns 409 Conflict with MSG4.21 count otherwise.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)

MSG4_21_TEMPLATE = "{n} expected items are not captured or explained. Resolve them to sign off."


class AuditSignoffConflict(Exception):
    """Raised when expected audit lines remain unexplained and unwaived (FR4.028 / TC4.122)."""

    def __init__(self, unresolved_count: int, message: str) -> None:
        super().__init__(message)
        self.unresolved_count = unresolved_count
        self.error_code = "FIELD-AUD-409-INCOMPLETE"


def sign_off_audit_task(
    tenant_id: str,
    task_id: str,
    signed_by: str,
    waiver_reason: str | None = None,
    supervisor_waiver: bool = False,
) -> dict[str, Any]:
    """Execute audit task sign-off if all lines are satisfied or waived."""
    now = datetime.now(UTC)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch task
            cur.execute(
                "SELECT id, site_id, status FROM field.task WHERE tenant_id = %s AND id = %s;",
                (tenant_id, task_id),
            )
            task_row = cur.fetchone()
            if not task_row:
                raise ValueError(f"FIELD-TASK-404: Task {task_id} not found")

            if task_row[2] in ("completed", "signed_off"):
                raise ValueError("FIELD-AUD-409-SIGNED: task already signed off")

            site_id = task_row[1]

            # 2. Fetch expected task lines and their status
            cur.execute(
                """
                SELECT tl.id, tl.expected_serial, tl.captured_qty, tl.status
                FROM field.task_line tl
                WHERE tl.tenant_id = %s AND tl.task_id = %s;
                """,
                (tenant_id, task_id),
            )
            lines = cur.fetchall()

            # 3. Fetch verified captures on this task
            cur.execute(
                """
                SELECT DISTINCT c.code_value
                FROM field.capture c
                WHERE c.tenant_id = %s AND c.task_id = %s AND c.verify_status IN ('verified', 'not_needed');
                """,
                (tenant_id, task_id),
            )
            captured_serials = {r[0] for r in cur.fetchall()}

            # 4. Fetch valid explanations from erp_only findings
            cur.execute(
                """
                SELECT expected_serial, reason
                FROM field.audit_finding
                WHERE tenant_id = %s AND task_id = %s AND class = 'erp_only' AND reason IS NOT NULL;
                """,
                (tenant_id, task_id),
            )
            explained_serials = {r[0] for r in cur.fetchall()}

            # 5. Evaluate unresolved lines
            unresolved_lines = []
            for line in lines:
                exp_serial = line[1]
                line_status = line[3]

                is_captured = (exp_serial in captured_serials) or (
                    line_status in ("captured", "done")
                )
                is_explained = exp_serial in explained_serials

                if not is_captured and not is_explained:
                    unresolved_lines.append(line[0])

            unresolved_count = len(unresolved_lines)

            # 6. Check waiver condition
            if unresolved_count > 0:
                if not supervisor_waiver or not waiver_reason or not waiver_reason.strip():
                    msg = MSG4_21_TEMPLATE.format(n=unresolved_count)
                    raise AuditSignoffConflict(unresolved_count=unresolved_count, message=msg)

                # Supervisor waiver applies: the unresolved lines are marked waived, so the record
                # shows exactly which lines were signed off unseen. (Previously this only logged.)
                cur.execute(
                    "UPDATE field.task_line SET status = 'waived', updated_at = NOW() "
                    "WHERE tenant_id = %s AND id = ANY(%s::uuid[])",
                    (tenant_id, [str(x) for x in unresolved_lines]),
                )
                logger.info(
                    "supervisor_waiver_applied",
                    task_id=task_id,
                    unresolved_count=unresolved_count,
                    reason=waiver_reason,
                    supervisor=signed_by,
                )

            # 7. Complete and sign off task
            cur.execute(
                """
                UPDATE field.task
                SET status = 'signed_off',
                    updated_at = NOW()
                WHERE tenant_id = %s AND id = %s;
                """,
                (tenant_id, task_id),
            )

            # 8. Emit audit.signed_off outbox event
            event_payload = {
                "task_id": str(task_id),
                "site_id": str(site_id),
                "signed_by": signed_by,
                "waiver_applied": supervisor_waiver and unresolved_count > 0,
                "waiver_reason": waiver_reason
                if (supervisor_waiver and unresolved_count > 0)
                else None,
                "unresolved_waived_count": unresolved_count,
                "waived_line_ids": [str(x) for x in unresolved_lines] if supervisor_waiver else [],
                "signed_off_at": now.isoformat(),
            }
            cur.execute(
                """
                INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, 'audit.signed_off', %s);
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    str(task_id),
                    json.dumps(event_payload, default=str),
                ),
            )

        conn.commit()

    return {
        "task_id": task_id,
        "status": "signed_off",
        "signed_by": signed_by,
        "signed_off_at": now.isoformat(),
        "waived_count": unresolved_count if (supervisor_waiver and unresolved_count > 0) else 0,
    }
