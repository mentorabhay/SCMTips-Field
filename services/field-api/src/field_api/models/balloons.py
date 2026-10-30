"""Balloon Registry and Monotonic Stability Engine (Task T4.056 / FR4.052 / PR4.10).

Maintains stable, unique balloon numbers per equipment class across semantic model versions:
- Unique within any model version.
- Stable across versions: same (part_no, node_path) retains its balloon number across version upgrades.
- Retired numbers are NEVER reused (PR4.10).
"""

from __future__ import annotations

from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


class MemoryBalloonRegistry:
    """In-memory balloon registry comparator for property-based hypothesis testing (PR4.10)."""

    def __init__(self) -> None:
        # (equipment_class, part_no, node_path) -> balloon_no
        self.registry: dict[tuple[str, str, str], int] = {}
        # equipment_class -> highest_balloon_ever_allocated
        self.max_allocated: dict[str, int] = {}
        # equipment_class -> set of all numbers ever allocated
        self.ever_allocated: dict[str, set[int]] = {}

    def assign_balloons_for_version(
        self,
        equipment_class: str,
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Assign balloon numbers to a version's BOM items.

        Returns:
            (items_with_balloons, balloons_assigned, balloons_kept)
        """
        current_max = self.max_allocated.get(equipment_class, 0)
        allocated_set = self.ever_allocated.setdefault(equipment_class, set())
        assigned_count = 0
        kept_count = 0

        version_balloons: set[int] = set()
        result_items = []

        for item in items:
            key = (equipment_class, item["part_no"], item.get("node_path", ""))
            if key in self.registry:
                b_no = self.registry[key]
                kept_count += 1
            else:
                current_max += 1
                b_no = current_max
                self.registry[key] = b_no
                allocated_set.add(b_no)
                assigned_count += 1

            assert b_no not in version_balloons, f"Duplicate balloon number {b_no} in same version"
            version_balloons.add(b_no)

            item_copy = dict(item)
            item_copy["balloon_no"] = b_no
            result_items.append(item_copy)

        self.max_allocated[equipment_class] = current_max
        return result_items, assigned_count, kept_count


def assign_model_balloons_in_db(
    tenant_id: str,
    model_id: str,
    cur: Any | None = None,
) -> tuple[int, int]:
    """Assign stable balloon numbers to a draft model's BOM items before publishing (FR4.052).

    Returns:
        (balloons_assigned, balloons_kept)
    """

    def _execute(c: Any) -> tuple[int, int]:
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
        c.execute("SELECT set_config('app.site_ids', '*', true);")

        # 1. Fetch model equipment_class
        c.execute(
            "SELECT equipment_class FROM field.asset_model WHERE tenant_id = %s AND id = %s;",
            (tenant_id, model_id),
        )
        m_row = c.fetchone()
        if not m_row:
            raise ValueError(f"Model {model_id} not found")
        eq_class = m_row[0]

        # 2. Fetch BOM items
        c.execute(
            """
            SELECT id, part_no, node_path
            FROM field.asset_model_bom
            WHERE tenant_id = %s AND model_id = %s
            ORDER BY part_no ASC, node_path ASC;
            """,
            (tenant_id, model_id),
        )
        bom_rows = c.fetchall()

        # 3. Fetch max allocated balloon number for this class
        c.execute(
            """
            SELECT COALESCE(MAX(balloon_no), 0)
            FROM field.balloon_registry
            WHERE tenant_id = %s AND equipment_class = %s;
            """,
            (tenant_id, eq_class),
        )
        max_balloon = c.fetchone()[0]

        assigned_count = 0
        kept_count = 0
        seen_keys = set()

        for bom_id, part_no, node_path in bom_rows:
            node_p = node_path or ""
            # Check existing registry entry
            c.execute(
                """
                SELECT balloon_no
                FROM field.balloon_registry
                WHERE tenant_id = %s AND equipment_class = %s AND part_no = %s AND node_path = %s;
                """,
                (tenant_id, eq_class, part_no, node_p),
            )
            reg_row = c.fetchone()

            if reg_row:
                b_no = reg_row[0]
                kept_count += 1
            else:
                max_balloon += 1
                b_no = max_balloon
                c.execute(
                    """
                    INSERT INTO field.balloon_registry (
                        tenant_id, equipment_class, part_no, node_path, balloon_no
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, equipment_class, part_no, node_path)
                    DO UPDATE SET is_retired = false
                    RETURNING balloon_no;
                    """,
                    (tenant_id, eq_class, part_no, node_p, b_no),
                )
                assigned_count += 1

            # Update BOM item with assigned balloon number
            c.execute(
                """
                UPDATE field.asset_model_bom
                SET balloon_no = %s
                WHERE tenant_id = %s AND id = %s;
                """,
                (b_no, tenant_id, bom_id),
            )
            seen_keys.add((part_no, node_p))

        # 4. Mark unreferenced registry items as retired for future versions
        c.execute(
            """
            SELECT part_no, node_path
            FROM field.balloon_registry
            WHERE tenant_id = %s AND equipment_class = %s AND is_retired = false;
            """,
            (tenant_id, eq_class),
        )
        for p_no, n_p in c.fetchall():
            if (p_no, n_p) not in seen_keys:
                c.execute(
                    """
                    UPDATE field.balloon_registry
                    SET is_retired = true
                    WHERE tenant_id = %s AND equipment_class = %s AND part_no = %s AND node_path = %s;
                    """,
                    (tenant_id, eq_class, p_no, n_p),
                )

        return assigned_count, kept_count

    if cur is not None:
        return _execute(cur)
    with get_conn() as conn:
        with conn.cursor() as cursor:
            res = _execute(cursor)
            conn.commit()
            return res
