"""Audit Progress and Completeness Service (Task T4.014 / FR4.024, FR4.063 / PR4.03 / API4.07).

Computes audit completeness as count(captured intersect expected) / count(expected)
per site, tower, sector, and level. If expected is empty, completeness is 1.0 with empty_scope=True.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


@dataclass
class CompletenessMetric:
    scope_code: str
    expected_count: int
    captured_count: int
    value: float
    empty_scope: bool


def calculate_completeness(expected: set[str], captured: set[str]) -> tuple[float, bool]:
    """Pure mathematical completeness function (PR4.03).

    Invariants:
    1. Result lies strictly in [0.0, 1.0].
    2. Equals 1.0 only if expected <= captured, or expected is empty.
    3. If expected is empty, value is 1.0 with empty_scope=True.
    """
    if not expected:
        return 1.0, True

    intersect_count = len(expected.intersection(captured))
    ratio = float(intersect_count) / float(len(expected))
    return min(1.0, max(0.0, ratio)), False


def get_audit_progress(tenant_id: str, task_id: str) -> dict[str, Any]:
    """Compute hierarchical audit progress for task_id (API4.07)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Verify task exists
            cur.execute(
                "SELECT id, site_id, type, status, snapshot_version FROM field.task WHERE tenant_id = %s AND id = %s;",
                (tenant_id, task_id),
            )
            task_row = cur.fetchone()
            if not task_row:
                raise ValueError(f"FIELD-TASK-404: Task {task_id} not found")

            site_id = task_row[1]

            # 2. Fetch all expected task_lines with location metadata
            cur.execute(
                """
                SELECT
                    tl.id,
                    tl.expected_serial,
                    tl.captured_qty,
                    COALESCE(tl.status, 'pending') AS status,
                    l.id AS location_id,
                    COALESCE(l.sector_code, 'UNASSIGNED') AS sector_code,
                    COALESCE(l.height_m, 0.0) AS height_m,
                    COALESCE(tl_tow.code, 'T01') AS tower_code
                FROM field.task_line tl
                LEFT JOIN field.location l ON tl.location_id = l.id
                LEFT JOIN field.location tl_tow ON tl_tow.id = l.parent_id AND tl_tow.kind = 'tower'
                WHERE tl.tenant_id = %s AND tl.task_id = %s;
                """,
                (tenant_id, task_id),
            )
            task_lines = cur.fetchall()

            # 3. Fetch all verified/matched captures on this task
            cur.execute(
                """
                SELECT DISTINCT c.code_value
                FROM field.capture c
                WHERE c.tenant_id = %s
                  AND c.task_id = %s
                  AND c.verify_status IN ('verified', 'not_needed')
                  AND c.superseded_by IS NULL
                  AND c.code_value IS NOT NULL;
                """,
                (tenant_id, task_id),
            )
            captured_serials = {r[0] for r in cur.fetchall()}

            # Also consider task_lines marked as captured or confirmed
            for r in task_lines:
                exp_s = r[1]
                st = r[3]
                if st in ('captured', 'done') and exp_s:
                    captured_serials.add(exp_s)

    # 4. Group expected items hierarchically
    site_expected: set[str] = set()
    towers: dict[str, dict[str, set[str]]] = {}  # tower_code -> {sector_code -> set(serials)}

    for r in task_lines:
        serial = r[1]
        sec = r[5]
        tow = r[7]
        if serial:
            site_expected.add(serial)
            if tow not in towers:
                towers[tow] = {}
            if sec not in towers[tow]:
                towers[tow][sec] = set()
            towers[tow][sec].add(serial)

    # 5. Compute metrics
    site_val, site_empty = calculate_completeness(site_expected, captured_serials)

    tower_outputs = []
    for tow_code, sectors_map in sorted(towers.items()):
        tow_expected: set[str] = set()
        sector_outputs = []

        for sec_code, sec_serials in sorted(sectors_map.items()):
            tow_expected.update(sec_serials)
            sec_val, sec_empty = calculate_completeness(sec_serials, captured_serials)
            sector_outputs.append({
                "code": sec_code,
                "value": round(sec_val, 3),
                "expected_count": len(sec_serials),
                "captured_count": len(sec_serials.intersection(captured_serials)),
                "empty_scope": sec_empty,
            })

        tow_val, tow_empty = calculate_completeness(tow_expected, captured_serials)
        tower_outputs.append({
            "code": tow_code,
            "value": round(tow_val, 3),
            "empty_scope": tow_empty,
            "sectors": sector_outputs,
        })

    # Default if no lines
    if not tower_outputs:
        tower_outputs.append({
            "code": "T01",
            "value": 1.0,
            "empty_scope": True,
            "sectors": [],
        })

    return {
        "site": round(site_val, 3),
        "site_id": site_id,
        "empty_scope": site_empty,
        "towers": tower_outputs,
    }
