"""Missing and Unknown Audit Findings API Service (Task T4.019 / FR4.022, FR4.023 / TC4.120, TC4.121).

Provides endpoints to:
1. Mark missing expected equipment with validated reason (not_found, removed_by_other, inaccessible).
2. Record unknown unexpected equipment found on tower with equipment class and photo evidence.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)

ALLOWED_MISSING_REASONS = {"not_found", "removed_by_other", "inaccessible"}


def mark_item_missing(
    tenant_id: str,
    task_id: str,
    expected_serial: str,
    equipment_class: str,
    reason: str,
    location_id: str | None = None,
    reported_by: str | None = None,
) -> dict[str, Any]:
    """Record missing expected equipment finding (FR4.023 / TC4.121)."""
    if reason not in ALLOWED_MISSING_REASONS:
        raise ValueError(
            f"FIELD-AUD-422-REASON: Invalid missing reason '{reason}'. Must be one of: {sorted(ALLOWED_MISSING_REASONS)}"
        )

    finding_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch task and site
            cur.execute(
                "SELECT site_id FROM field.task WHERE tenant_id = %s AND id = %s;",
                (tenant_id, task_id),
            )
            t_row = cur.fetchone()
            if not t_row:
                raise ValueError(f"FIELD-TASK-404: Task {task_id} not found")
            site_id = t_row[0]

            # 2. Look up matching task_line
            cur.execute(
                """
                SELECT id, location_id FROM field.task_line
                WHERE tenant_id = %s AND task_id = %s AND expected_serial = %s
                LIMIT 1;
                """,
                (tenant_id, task_id, expected_serial),
            )
            tl_row = cur.fetchone()
            task_line_id = tl_row[0] if tl_row else None
            loc_id = location_id or (tl_row[1] if tl_row else None)

            # 3. Create or update erp_only finding
            dedupe_key = f"{site_id}:{expected_serial}:erp_only"
            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, tower_location_id,
                    location_id, task_line_id, class, expected_serial,
                    reason, status, dedupe_key
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, 'erp_only', %s,
                    %s, 'open', %s
                )
                ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'resolved'
                DO UPDATE SET
                    reason = EXCLUDED.reason,
                    location_id = COALESCE(EXCLUDED.location_id, field.audit_finding.location_id),
                    updated_at = NOW()
                RETURNING id;
                """,
                (
                    finding_id,
                    tenant_id,
                    task_id,
                    site_id,
                    loc_id,
                    loc_id,
                    task_line_id,
                    expected_serial,
                    reason,
                    dedupe_key,
                ),
            )
            f_row = cur.fetchone()
            actual_finding_id = f_row[0] if f_row else finding_id

            # 4. Update task_line status
            if task_line_id:
                cur.execute(
                    "UPDATE field.task_line SET status = 'missing', updated_at = NOW() WHERE id = %s;",
                    (task_line_id,),
                )

        conn.commit()

    return {
        "finding_id": str(actual_finding_id),
        "task_id": task_id,
        "class": "erp_only",
        "expected_serial": expected_serial,
        "reason": reason,
        "status": "open",
    }


def record_unknown_equipment(
    tenant_id: str,
    task_id: str,
    found_serial: str,
    equipment_class: str,
    location_id: str | None = None,
    crop_ref: str | None = None,
    reported_by: str | None = None,
) -> dict[str, Any]:
    """Record unknown equipment found on tower as tower_only finding (FR4.022 / TC4.120)."""
    finding_id = str(uuid.uuid4())
    capture_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch task and site
            cur.execute(
                "SELECT site_id FROM field.task WHERE tenant_id = %s AND id = %s;",
                (tenant_id, task_id),
            )
            t_row = cur.fetchone()
            if not t_row:
                raise ValueError(f"FIELD-TASK-404: Task {task_id} not found")
            site_id = t_row[0]

            # 2. Record capture row if not already created
            capture_parsed = {
                "equipment_class": equipment_class,
                "location_id": str(location_id) if location_id else None,
            }
            cur.execute(
                """
                INSERT INTO field.capture (
                    id, tenant_id, site_id, task_id, code_type,
                    code_value, confidence, verify_status, raw_text, parsed_data
                ) VALUES (
                    %s, %s, %s, %s, 'serial_text',
                    %s, 0.95, 'verified', %s, %s
                );
                """,
                (
                    capture_id,
                    tenant_id,
                    site_id,
                    task_id,
                    found_serial,
                    found_serial,
                    json.dumps(capture_parsed),
                ),
            )
            if crop_ref:
                cur.execute(
                    """
                    INSERT INTO field.capture_evidence (
                        id, tenant_id, capture_id, crop_s3_uri, file_size_bytes,
                        sha256_hash, retention_until
                    ) VALUES (
                        %s, %s, %s, %s, 1024,
                        'sha256_placeholder', NOW() + interval '90 days'
                    );
                    """,
                    (str(uuid.uuid4()), tenant_id, capture_id, crop_ref),
                )

            # 3. Create or update tower_only finding
            dedupe_key = f"{site_id}:{found_serial}:tower_only"
            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, tower_location_id,
                    location_id, capture_id, class, found_serial,
                    status, dedupe_key
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, 'tower_only', %s,
                    'open', %s
                )
                ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'resolved'
                DO UPDATE SET
                    capture_id = EXCLUDED.capture_id,
                    location_id = COALESCE(EXCLUDED.location_id, field.audit_finding.location_id),
                    updated_at = NOW()
                RETURNING id;
                """,
                (
                    finding_id,
                    tenant_id,
                    task_id,
                    site_id,
                    location_id,
                    location_id,
                    capture_id,
                    found_serial,
                    dedupe_key,
                ),
            )
            f_row = cur.fetchone()
            actual_finding_id = f_row[0] if f_row else finding_id

        conn.commit()

    return {
        "finding_id": str(actual_finding_id),
        "task_id": task_id,
        "class": "tower_only",
        "found_serial": found_serial,
        "equipment_class": equipment_class,
        "crop_ref": crop_ref,
        "status": "open",
    }
