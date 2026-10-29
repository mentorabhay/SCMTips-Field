"""Replay Conflict Detection and Tower Queue Holding Engine (Task T4.064 / TC4.152 / FR4.060).

Handles:
- Compares replayed offline event preconditions (expected current FL/status of serial) with current ERP state.
- Detects conflicts (e.g. equipment dismantled or moved during offline visit).
- Opens an S2 exception case in field.exception_case.
- Emits MSG4.23 ('replay.conflict_detected') event to outbox.
- Holds the tower queue in field.queue_hold, preventing further replay for that tower while other towers continue independently (PR4.12).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from field_common.uuid7 import uuid7_str

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def is_queue_held(
    tenant_id: str,
    queue_key: str,
    db_url: str = DATABASE_URL,
    cur: Any | None = None,
) -> bool:
    """Check if a specific tower posting queue is currently held due to a conflict (PR4.12 / TC4.152)."""
    def _exec(c: Any) -> bool:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        c.execute(
            """
            SELECT id FROM field.queue_hold
            WHERE tenant_id = %s AND queue_key = %s AND is_held = true;
            """,
            (tenant_id, queue_key),
        )
        return c.fetchone() is not None

    if cur is not None:
        return _exec(cur)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as c:
            return _exec(c)


def check_and_handle_replay_conflict(
    tenant_id: str,
    site_id: str,
    tower_fl: str,
    equipment_no: str,
    serial_no: str,
    operation: str,
    expected_precondition_fl: str | None,
    current_erp_state: dict[str, Any],
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Check if replayed event conflicts with current ERP truth; if so hold queue and open S2 case (TC4.152)."""
    queue_key = f"EQUIP:{tower_fl}"
    has_conflict = False
    conflict_reason = ""

    erp_status = current_erp_state.get("status", "installed")
    erp_location = current_erp_state.get("current_fl") or current_erp_state.get("location")

    # Conflict logic
    if operation == "dismantle":
        # Precondition: Equipment was expected to be installed at expected_precondition_fl
        if erp_status == "dismantled":
            has_conflict = True
            conflict_reason = (
                f"Serial '{serial_no}' (Eq: {equipment_no}) was already dismantled in ERP during offline visit. "
                f"Expected FL was '{expected_precondition_fl}'."
            )
        elif expected_precondition_fl and erp_location and erp_location != expected_precondition_fl:
            has_conflict = True
            conflict_reason = (
                f"Serial '{serial_no}' location mismatch: ERP reports '{erp_location}', "
                f"offline event expected '{expected_precondition_fl}'."
            )
    elif operation == "install":
        # Precondition: Equipment was in store / dismantled and ready to install
        if erp_status == "installed" and erp_location != expected_precondition_fl:
            has_conflict = True
            conflict_reason = (
                f"Serial '{serial_no}' is already installed at '{erp_location}' in ERP; "
                f"cannot install at '{expected_precondition_fl}'."
            )

    if not has_conflict:
        return {"conflict": False, "queue_key": queue_key}

    # Conflict detected: open S2 exception case and hold queue
    case_id = uuid7_str()
    hold_id = uuid7_str()
    dedupe_key = f"conflict:{tenant_id}:{equipment_no}:{tower_fl}"

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Open S2 Exception Case in field.exception_case
            cur.execute(
                """
                INSERT INTO field.exception_case (
                    id, tenant_id, site_id, type, dedupe_key, status, severity,
                    rule_id, subject, facts, version
                ) VALUES (
                    %s, %s, %s, 'replay_conflict', %s, 'open', 'S2',
                    'RULE-REPLAY-CONFLICT',
                    %s, %s, 1
                )
                ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'closed'
                DO UPDATE SET
                    occurrence_count = field.exception_case.occurrence_count + 1,
                    facts = EXCLUDED.facts
                RETURNING id;
                """,
                (
                    case_id,
                    tenant_id,
                    site_id,
                    dedupe_key,
                    json.dumps({
                        "equipment_no": equipment_no,
                        "serial_no": serial_no,
                        "tower_fl": tower_fl,
                        "operation": operation,
                    }),
                    json.dumps({
                        "reason": conflict_reason,
                        "expected_fl": expected_precondition_fl,
                        "erp_status": erp_status,
                        "erp_location": erp_location,
                    }),
                ),
            )
            case_row = cur.fetchone()
            actual_case_id = str(case_row[0]) if case_row else str(case_id)

            # 2. Hold tower queue in field.queue_hold
            cur.execute(
                """
                INSERT INTO field.queue_hold (
                    id, tenant_id, queue_key, tower_fl, is_held,
                    conflict_reason, exception_case_id, held_at
                ) VALUES (
                    %s, %s, %s, %s, true,
                    %s, %s, NOW()
                )
                ON CONFLICT (tenant_id, queue_key) WHERE is_held = true
                DO UPDATE SET
                    conflict_reason = EXCLUDED.conflict_reason,
                    held_at = NOW();
                """,
                (
                    hold_id,
                    tenant_id,
                    queue_key,
                    tower_fl,
                    conflict_reason,
                    actual_case_id,
                ),
            )

            # 3. Emit outbox event MSG4.23 ('replay.conflict_detected')
            outbox_payload = {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "tower_fl": tower_fl,
                "queue_key": queue_key,
                "equipment_no": equipment_no,
                "serial_no": serial_no,
                "operation": operation,
                "exception_case_id": actual_case_id,
                "reason": conflict_reason,
                "occurred_at": datetime.now(UTC).isoformat(),
            }
            cur.execute(
                """
                INSERT INTO field.outbox (
                    id, tenant_id, aggregate_id, event_type, payload
                ) VALUES (
                    %s, %s, %s, 'replay.conflict_detected', %s
                );
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    actual_case_id,
                    json.dumps(outbox_payload),
                ),
            )
            conn.commit()

    logger.warn(
        "Replay conflict detected - tower queue held",
        tower_fl=tower_fl,
        queue_key=queue_key,
        exception_case_id=actual_case_id,
        reason=conflict_reason,
    )

    return {
        "conflict": True,
        "exception_case_id": actual_case_id,
        "queue_held": True,
        "queue_key": queue_key,
        "reason": conflict_reason,
    }


def release_queue_hold(
    tenant_id: str,
    queue_key: str,
    released_by: str,
    db_url: str = DATABASE_URL,
) -> bool:
    """Release hold on tower queue after conflict resolution."""
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                UPDATE field.queue_hold
                SET is_held = false,
                    released_at = NOW(),
                    released_by = %s
                WHERE tenant_id = %s AND queue_key = %s AND is_held = true;
                """,
                (released_by, tenant_id, queue_key),
            )
            conn.commit()
            return cur.rowcount > 0
