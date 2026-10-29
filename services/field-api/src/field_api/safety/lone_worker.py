"""Lone Worker Timer, Heartbeat Monitoring and Escalation Logic (Task T4.045 / FR4.043 / FR4.044 / PR4.19).

Features:
- Periodic heartbeat monitoring (default 20 min interval, 5 min grace period)
- Warning deferral while climbing
- Automated escalation sweep emitting field.visit.escalated outbox events
- Supervisor acknowledgment recording (field.visit.ack)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)

DEFAULT_TIMER_INTERVAL_MIN = 20
DEFAULT_GRACE_PERIOD_MIN = 5


def checkin_lone_worker(
    tenant_id: str,
    visit_id: str,
    user_id: str,
    altitude_m: float | None = None,
    tower_fl: str | None = None,
    cur: Any | None = None,
) -> dict[str, Any]:
    """Record a lone-worker check-in, restarting the countdown timer (FR4.043 / PR4.19)."""
    now = datetime.now(UTC)

    def _execute(c: Any) -> dict[str, Any]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        c.execute(
            """
            SELECT id, status, timer_interval_min
            FROM field.site_visit
            WHERE tenant_id = %s AND id = %s;
            """,
            (tenant_id, visit_id),
        )
        row = c.fetchone()
        if not row:
            raise ValueError(f"Site visit '{visit_id}' not found [FIELD-VIS-404-NOT-FOUND]")

        current_status = row[1]
        interval_min = row[2] or DEFAULT_TIMER_INTERVAL_MIN

        # Restore to on_structure if altitude > 2m, else checked_in
        new_status = current_status
        if current_status in ("overdue", "escalated"):
            new_status = "on_structure" if (altitude_m and altitude_m > 2.0) else "checked_in"

        alt_clause = ", last_altitude_m = %s" if altitude_m is not None else ""
        tower_clause = ", last_tower_fl = %s" if tower_fl is not None else ""

        params: list[Any] = [now, new_status]
        if altitude_m is not None:
            params.append(altitude_m)
        if tower_fl is not None:
            params.append(tower_fl)
        params.extend([tenant_id, visit_id])

        c.execute(
            f"""
            UPDATE field.site_visit
            SET last_heartbeat_at = %s,
                status = %s
                {alt_clause}
                {tower_clause},
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            RETURNING id, status, last_heartbeat_at;
            """,
            tuple(params),
        )
        upd_row = c.fetchone()

        # Emit outbox event
        evt_payload = {
            "visit_id": visit_id,
            "user_id": user_id,
            "checkin_at": now.isoformat(),
            "altitude_m": altitude_m,
            "tower_fl": tower_fl,
            "status": new_status,
        }
        c.execute(
            """
            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, 'field.visit.checkin', %s);
            """,
            (str(uuid.uuid4()), tenant_id, visit_id, json.dumps(evt_payload)),
        )

        return {
            "visit_id": str(upd_row[0]),
            "status": upd_row[1],
            "last_heartbeat_at": upd_row[2].isoformat()
            if hasattr(upd_row[2], "isoformat")
            else str(upd_row[2]),
            "next_warning_in_s": max(0, (interval_min - 2) * 60),
            "timer_interval_min": interval_min,
        }

    if cur is not None:
        return _execute(cur)

    with get_conn() as conn:
        with conn.cursor() as local_cur:
            res = _execute(local_cur)
        conn.commit()
    return res


def acknowledge_lone_worker_escalation(
    tenant_id: str,
    visit_id: str,
    acknowledged_by: str,
    notes: str | None = None,
    cur: Any | None = None,
) -> dict[str, Any]:
    """Acknowledge an escalated lone-worker visit from the supervisor console (SCR4.13 / FR4.044)."""
    now = datetime.now(UTC)

    def _execute(c: Any) -> dict[str, Any]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        c.execute(
            """
            UPDATE field.site_visit
            SET acked_at = %s,
                ack_notes = %s,
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            RETURNING id, status, acked_at;
            """,
            (now, notes, tenant_id, visit_id),
        )
        row = c.fetchone()
        if not row:
            raise ValueError(f"Site visit '{visit_id}' not found [FIELD-VIS-404-NOT-FOUND]")

        # Emit field.visit.ack
        evt_payload = {
            "visit_id": visit_id,
            "acknowledged_by": acknowledged_by,
            "acked_at": now.isoformat(),
            "notes": notes,
        }
        c.execute(
            """
            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, 'field.visit.ack', %s);
            """,
            (str(uuid.uuid4()), tenant_id, visit_id, json.dumps(evt_payload)),
        )

        return {
            "visit_id": str(row[0]),
            "status": row[1],
            "acked_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "acknowledged_by": acknowledged_by,
        }

    if cur is not None:
        return _execute(cur)

    with get_conn() as conn:
        with conn.cursor() as local_cur:
            res = _execute(local_cur)
        conn.commit()
    return res


def run_lone_worker_escalation_sweep(
    tenant_id: str,
    current_time: datetime | None = None,
    cur: Any | None = None,
) -> list[dict[str, Any]]:
    """Sweep active visits and transition to 'overdue' or 'escalated' (TC4.139 / FR4.044 / PR4.19)."""
    now = current_time or datetime.now(UTC)

    def _execute(c: Any) -> list[dict[str, Any]]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        c.execute(
            """
            SELECT v.id, v.site_id, v.user_id, v.status, v.timer_interval_min,
                   v.last_heartbeat_at, v.last_altitude_m, v.last_tower_fl,
                   s.code as site_code, s.name as site_name
            FROM field.site_visit v
            JOIN field.site s ON v.site_id = s.id
            WHERE v.tenant_id = %s
              AND v.status IN ('checked_in', 'on_structure', 'overdue');
            """,
            (tenant_id,),
        )
        rows = c.fetchall()
        transitions: list[dict[str, Any]] = []

        for r in rows:
            v_id = str(r[0])
            site_id = str(r[1])
            user_id = str(r[2])
            status = r[3]
            interval_min = r[4] or DEFAULT_TIMER_INTERVAL_MIN
            last_hb = r[5]
            last_alt = float(r[6]) if r[6] is not None else 0.0
            last_tower = r[7] or "T01"
            site_code = r[8]

            elapsed_s = (now - last_hb).total_seconds()
            interval_s = interval_min * 60
            grace_s = DEFAULT_GRACE_PERIOD_MIN * 60

            # Condition 1: Exceeded interval + grace -> ESCALATED
            if elapsed_s > (interval_s + grace_s):
                if status != "escalated":
                    c.execute(
                        """
                        UPDATE field.site_visit
                        SET status = 'escalated',
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (v_id,),
                    )

                    # Emit field.visit.escalated
                    esc_payload = {
                        "visit_id": v_id,
                        "site_id": site_id,
                        "site_code": site_code,
                        "tower_fl": last_tower,
                        "user_id": user_id,
                        "last_altitude_m": last_alt,
                        "last_checkin_at": last_hb.isoformat(),
                        "escalated_at": now.isoformat(),
                        "message": f"Overdue check-in at {site_code} ({last_tower}) - Last altitude: {last_alt}m [MSG4.10]",
                    }
                    c.execute(
                        """
                        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                        VALUES (%s, %s, %s, 'field.visit.escalated', %s);
                        """,
                        (str(uuid.uuid4()), tenant_id, v_id, json.dumps(esc_payload)),
                    )

                    transitions.append(
                        {
                            "visit_id": v_id,
                            "site_code": site_code,
                            "previous_status": status,
                            "new_status": "escalated",
                            "elapsed_min": round(elapsed_s / 60, 1),
                            "last_altitude_m": last_alt,
                        }
                    )

            # Condition 2: Exceeded interval but within grace -> OVERDUE
            elif elapsed_s > interval_s and status not in ("overdue", "escalated"):
                c.execute(
                    """
                        UPDATE field.site_visit
                        SET status = 'overdue',
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                    (v_id,),
                )
                transitions.append(
                    {
                        "visit_id": v_id,
                        "site_code": site_code,
                        "previous_status": status,
                        "new_status": "overdue",
                        "elapsed_min": round(elapsed_s / 60, 1),
                    }
                )

        return transitions

    if cur is not None:
        return _execute(cur)

    with get_conn() as conn:
        with conn.cursor() as local_cur:
            res = _execute(local_cur)
        conn.commit()
    return res
