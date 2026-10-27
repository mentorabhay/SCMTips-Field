"""Serial Event History and Single-Location Invariant (Task T4.025 / FR4.033 / FR4.034 / PR4.01 / PR4.02).

Manages append-only serial_event timeline with per-serial sequence monotonicity (PR4.02),
database trigger immutability enforcement (PR4.01), and single-location invariant checks.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional
import structlog

from field_api.db import get_conn

logger = structlog.get_logger(__name__)


class SingleLocationViolationError(Exception):
    """Raised when an active serial is already installed at a different location."""

    def __init__(self, serial_no: str, current_location_id: str, current_fl: Optional[str] = None):
        fl_msg = f" ({current_fl})" if current_fl else ""
        super().__init__(
            f"Serial '{serial_no}' is already actively installed at location {current_location_id}{fl_msg} [FIELD-EQ-409-ALREADY-INSTALLED]"
        )
        self.code = "FIELD-EQ-409-ALREADY-INSTALLED"
        self.serial_no = serial_no
        self.current_location_id = current_location_id
        self.current_fl = current_fl


def append_serial_event(
    tenant_id: str,
    serial_no: str,
    event_type: str,
    location_id: Optional[str] = None,
    equipment_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    created_by: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    cur: Optional[Any] = None,
) -> dict[str, Any]:
    """Append a serial event with monotonic per-serial sequence (FR4.033 / PR4.02)."""
    def _execute_append(c: Any) -> dict[str, Any]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        # Resolve or create equipment record
        eq_id = equipment_id
        if not eq_id:
            c.execute(
                "SELECT id FROM field.equipment WHERE tenant_id = %s AND serial_no = %s LIMIT 1;",
                (tenant_id, serial_no),
            )
            eq_row = c.fetchone()
            if eq_row:
                eq_id = eq_row[0]
            else:
                c.execute(
                    """
                    INSERT INTO field.equipment (tenant_id, serial_no, material, status)
                    VALUES (%s, %s, 'GENERIC-EQUIPMENT', 'installed')
                    RETURNING id;
                    """,
                    (tenant_id, serial_no),
                )
                eq_id = c.fetchone()[0]

        # Monotonic sequence per (tenant_id, equipment_id)
        c.execute(
            """
            SELECT COALESCE(MAX(seq), 0) + 1
            FROM field.serial_event
            WHERE tenant_id = %s AND equipment_id = %s;
            """,
            (tenant_id, eq_id),
        )
        next_seq = c.fetchone()[0]

        # Map event_type to allowed CHECK constraint ('issue', 'install', 'dismantle', 'move', 'return', 'audit_seen', 'reversal')
        op_type = event_type
        if op_type not in ('issue', 'install', 'dismantle', 'move', 'return', 'audit_seen', 'reversal'):
            op_type = 'install'

        to_loc = location_id if op_type in ('install', 'issue', 'move') else None
        from_loc = location_id if op_type in ('dismantle', 'return') else None
        idem_key = idempotency_key or f"se-{uuid.uuid4()}"

        c.execute(
            """
            INSERT INTO field.serial_event (
                tenant_id, equipment_id, serial_no, seq, type,
                to_location_id, from_location_id, occurred_at, recorded_at, idempotency_key
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, NOW(), NOW(), %s
            )
            RETURNING id, seq, recorded_at;
            """,
            (
                tenant_id,
                eq_id,
                serial_no,
                next_seq,
                op_type,
                to_loc,
                from_loc,
                idem_key,
            ),
        )
        row = c.fetchone()
        return {
            "event_id": str(row[0]),
            "serial_no": serial_no,
            "seq": row[1],
            "event_type": event_type,
            "location_id": str(location_id) if location_id else None,
            "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        }

    if cur is not None:
        return _execute_append(cur)

    with get_conn() as conn:
        with conn.cursor() as local_cur:
            res = _execute_append(local_cur)
        conn.commit()

    return res


def get_serial_history(tenant_id: str, serial_no: str) -> list[dict[str, Any]]:
    """Retrieve full chronological history for a given serial number (API4.10)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                SELECT
                    se.id,
                    se.seq,
                    se.type,
                    COALESCE(se.to_location_id, se.from_location_id) AS location_id,
                    l.fl_code,
                    se.idempotency_key,
                    se.recorded_at
                FROM field.serial_event se
                LEFT JOIN field.location l ON COALESCE(se.to_location_id, se.from_location_id) = l.id
                WHERE se.tenant_id = %s AND se.serial_no = %s
                ORDER BY se.seq ASC;
                """,
                (tenant_id, serial_no),
            )
            rows = cur.fetchall()

            history: list[dict[str, Any]] = []
            for r in rows:
                history.append({
                    "id": str(r[0]),
                    "seq": r[1],
                    "event_type": r[2],
                    "location_id": str(r[3]) if r[3] else None,
                    "fl_code": r[4],
                    "created_by": None,
                    "details": {"idempotency_key": r[5]},
                    "created_at": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                })

            return history


def check_single_location_invariant(
    tenant_id: str,
    serial_no: str,
    target_location_id: Optional[str] = None,
    cur: Optional[Any] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Verify that serial_no is not currently installed at any other location (PR4.01 / FR4.034).

    Returns (is_allowed, current_location_id, current_fl_code).
    """
    def _execute_check(c: Any) -> tuple[bool, Optional[str], Optional[str]]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        c.execute(
            """
            SELECT e.current_location_id, l.fl_code
            FROM field.equipment e
            LEFT JOIN field.location l ON e.current_location_id = l.id
            WHERE e.tenant_id = %s AND e.serial_no = %s AND e.status = 'installed';
            """,
            (tenant_id, serial_no),
        )
        row = c.fetchone()

        if not row or not row[0]:
            return True, None, None

        curr_loc_id = str(row[0])
        curr_fl = row[1]

        # If already at the exact target location, it's not a collision
        if target_location_id and curr_loc_id == str(target_location_id):
            return True, curr_loc_id, curr_fl

        return False, curr_loc_id, curr_fl

    if cur is not None:
        return _execute_check(cur)

    with get_conn() as conn:
        with conn.cursor() as local_cur:
            return _execute_check(local_cur)
