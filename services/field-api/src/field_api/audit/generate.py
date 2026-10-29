"""Audit Task Generation Engine (Task T4.013 / FR4.014 / TC4.112).

Generates an audit task with one expected task_line per installed equipment
at the site, grouped and sorted by tower, sector, and level, with snapshot version recorded.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


def generate_audit_task(
    tenant_id: str,
    site_id: str,
    assigned_to: str | None = None,
    due_at: datetime | None = None,
    snapshot_version: str | None = None,
) -> dict[str, Any]:
    """Generate an audit task with task_line per installed equipment at the site."""
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    snap_ver = snapshot_version or f"erp-{now.strftime('%Y-%m-%dT%H:%MZ')}#{uuid.uuid4().hex[:4]}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Set RLS context
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 2. Verify site exists
            cur.execute(
                "SELECT id, code, name FROM field.site WHERE tenant_id = %s AND id = %s;",
                (tenant_id, site_id),
            )
            site_row = cur.fetchone()
            if not site_row:
                raise ValueError(f"Site {site_id} not found for tenant {tenant_id}")

            site_code = site_row[1]

            # 3. Fetch installed equipment at the site, grouped/ordered by tower, sector, level height
            cur.execute(
                """
                SELECT
                    e.id AS equipment_id,
                    e.serial_no,
                    e.material,
                    e.equipment_class,
                    l.id AS location_id,
                    l.code AS location_code,
                    l.fl_code,
                    COALESCE(l.sector_code, '') AS sector_code,
                    COALESCE(l.height_m, 0.0) AS height_m,
                    l.path
                FROM field.equipment e
                JOIN field.location l ON e.current_location_id = l.id
                WHERE e.tenant_id = %s
                  AND l.site_id = %s
                  AND e.status = 'installed'
                ORDER BY
                    COALESCE(l.sector_code, '') ASC,
                    COALESCE(l.height_m, 0.0) ASC,
                    e.serial_no ASC;
                """,
                (tenant_id, site_id),
            )
            equipment_rows = cur.fetchall()

            # 4. Create the task record
            task_title = f"Tower Audit - {site_code}"
            cur.execute(
                """
                INSERT INTO field.task (
                    id, tenant_id, site_id, type, status, priority,
                    title, assigned_to, due_at, snapshot_version, version
                ) VALUES (
                    %s, %s, %s, 'audit', 'pending', 'medium',
                    %s, %s, %s, %s, 1
                );
                """,
                (
                    task_id,
                    tenant_id,
                    site_id,
                    task_title,
                    assigned_to,
                    due_at,
                    snap_ver,
                ),
            )

            # 5. Create task_line per installed equipment
            lines = []
            for idx, eq in enumerate(equipment_rows, start=1):
                line_id = str(uuid.uuid4())
                eq_id = eq[0]
                serial_no = eq[1]
                mat_name = eq[2]
                eq_class = eq[3]
                loc_id = eq[4]
                loc_code = eq[5]
                fl_code = eq[6]
                sector_code = eq[7]
                height_m = float(eq[8])

                # Resolve or query material_id if available
                cur.execute(
                    "SELECT id FROM field.material WHERE tenant_id = %s AND (erp_material_no = %s OR description = %s) LIMIT 1;",
                    (tenant_id, mat_name, mat_name),
                )
                mat_row = cur.fetchone()
                mat_id = mat_row[0] if mat_row else None

                cur.execute(
                    """
                    INSERT INTO field.task_line (
                        id, tenant_id, site_id, task_id, line_no,
                        material_id, expected_qty, uom, captured_qty,
                        status, expected_serial, location_id, version
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, 1, 'EA', 0,
                        'pending', %s, %s, 1
                    );
                    """,
                    (
                        line_id,
                        tenant_id,
                        site_id,
                        task_id,
                        idx,
                        mat_id,
                        serial_no,
                        loc_id,
                    ),
                )

                lines.append(
                    {
                        "id": line_id,
                        "line_no": idx,
                        "equipment_id": str(eq_id),
                        "serial_no": serial_no,
                        "material": mat_name,
                        "equipment_class": eq_class,
                        "location_id": str(loc_id),
                        "location_code": loc_code,
                        "fl_code": fl_code,
                        "sector_code": sector_code,
                        "height_m": height_m,
                        "status": "pending",
                    }
                )

            # 6. Emit outbox event
            outbox_payload = {
                "task_id": task_id,
                "site_id": site_id,
                "site_code": site_code,
                "type": "audit",
                "snapshot_version": snap_ver,
                "line_count": len(lines),
            }
            cur.execute(
                """
                INSERT INTO field.outbox (
                    id, tenant_id, aggregate_id, event_type, payload
                ) VALUES (
                    %s, %s, %s, 'task.created', %s
                );
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    task_id,
                    json.dumps(outbox_payload),
                ),
            )

        conn.commit()

    logger.info(
        "audit_task_generated",
        task_id=task_id,
        site_id=site_id,
        line_count=len(lines),
        snapshot_version=snap_ver,
    )

    return {
        "id": task_id,
        "tenant_id": tenant_id,
        "site_id": site_id,
        "type": "audit",
        "status": "pending",
        "title": task_title,
        "snapshot_version": snap_ver,
        "line_count": len(lines),
        "lines": lines,
    }
