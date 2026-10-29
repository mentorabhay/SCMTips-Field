"""Exception Case Management and Deduplication Engine (Task T4.016 / FR4.026 / TC4.124).

Opens and deduplicates exception cases for unresolved audit findings keyed by
(site, serial, class) and emits exception.opened outbox events.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


def open_and_deduplicate_exceptions(
    tenant_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    """Scan unresolved audit findings for task_id, open exception cases, and emit outbox events."""
    opened_cases = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch unresolved findings on this task (mismatch, tower_only, erp_only, misplaced)
            cur.execute(
                """
                SELECT
                    af.id,
                    af.site_id,
                    af.class,
                    COALESCE(af.found_serial, af.expected_serial) AS serial_no,
                    af.expected_serial,
                    af.found_serial,
                    af.reason,
                    af.location_id,
                    af.dedupe_key
                FROM field.audit_finding af
                WHERE af.tenant_id = %s
                  AND af.task_id = %s
                  AND af.status = 'open'
                  AND af.class IN ('serial_mismatch', 'tower_only', 'erp_only', 'misplaced');
                """,
                (tenant_id, task_id),
            )
            findings = cur.fetchall()

            for f in findings:
                finding_id = f[0]
                site_id = f[1]
                f_class = f[2]
                serial_no = f[3]
                exp_serial = f[4]
                found_serial = f[5]
                reason = f[6]
                loc_id = f[7]
                dedupe_key = f[8] or f"{site_id}:{serial_no}:{f_class}"
                case_id = str(uuid.uuid4())

                # Check if an open exception case already exists for this dedupe_key (TC4.124)
                cur.execute(
                    """
                    SELECT id FROM field.exception_case
                    WHERE tenant_id = %s AND dedupe_key = %s AND status <> 'closed';
                    """,
                    (tenant_id, dedupe_key),
                )
                existing_case = cur.fetchone()

                if existing_case:
                    # Link existing case to finding
                    cur.execute(
                        """
                        UPDATE field.audit_finding
                        SET exception_case_id = %s, updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (existing_case[0], finding_id),
                    )
                    continue

                # Create new exception case
                subject_data = {
                    "site_id": site_id,
                    "serial_no": serial_no,
                    "finding_class": f_class,
                    "expected_serial": exp_serial,
                    "found_serial": found_serial,
                    "location_id": str(loc_id) if loc_id else None,
                }
                fact_data = {
                    "task_id": task_id,
                    "finding_id": finding_id,
                    "reason": reason,
                }

                cur.execute(
                    """
                    INSERT INTO field.exception_case (
                        id, tenant_id, site_id, type, dedupe_key,
                        status, severity, subject, facts, rule_id, version
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        'open', 'S2', %s, %s, 'RULE-RECONCILE-001', 1
                    )
                    ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'closed'
                    DO NOTHING
                    RETURNING id;
                    """,
                    (
                        case_id,
                        tenant_id,
                        site_id,
                        f"tower_{f_class}",
                        dedupe_key,
                        json.dumps(subject_data, default=str),
                        json.dumps(fact_data, default=str),
                    ),
                )
                inserted = cur.fetchone()

                if inserted:
                    actual_case_id = inserted[0]
                    # Link finding to case
                    cur.execute(
                        """
                        UPDATE field.audit_finding
                        SET exception_case_id = %s, updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (actual_case_id, finding_id),
                    )

                    # Emit exception.opened event to outbox
                    event_payload = {
                        "case_id": str(actual_case_id),
                        "site_id": str(site_id),
                        "type": f"tower_{f_class}",
                        "serial_no": serial_no,
                        "dedupe_key": dedupe_key,
                    }
                    cur.execute(
                        """
                        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                        VALUES (%s, %s, %s, 'exception.opened', %s);
                        """,
                        (
                            str(uuid.uuid4()),
                            tenant_id,
                            str(actual_case_id),
                            json.dumps(event_payload, default=str),
                        ),
                    )

                    opened_cases.append({
                        "case_id": str(actual_case_id),
                        "finding_id": finding_id,
                        "dedupe_key": dedupe_key,
                        "class": f_class,
                    })

        conn.commit()

    logger.info("exception_cases_processed", count=len(opened_cases), task_id=task_id)
    return opened_cases
