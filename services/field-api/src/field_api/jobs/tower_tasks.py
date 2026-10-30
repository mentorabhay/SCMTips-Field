"""Tower jobs: the swap task, and the position label shared with the audit generator (contract §2).

A swap task has exactly one line: ``position`` + ``expected_serial`` (the unit to remove) +
``material``, ``equipment_no`` (its SAP equipment) and ``location_id`` (whose functional location is
the install target). The new unit is captured on site (confirmations, role ``new``).
"""

from __future__ import annotations

from typing import Any

from field_api.db import tenant_tx


def position_label(sector_code: str | None, location_code: str | None) -> str | None:
    """'Sector A · slot 2' for a slot code S2 / P2 / 2 in sector A; the bare code otherwise."""
    if not location_code:
        return None
    code = str(location_code)
    slot = code[1:] if len(code) > 1 and code[0] in "SP" and code[1:].isdigit() else code
    if sector_code:
        return f"Sector {sector_code} · slot {slot}" if slot.isdigit() else f"Sector {sector_code} · {code}"
    return f"slot {slot}" if slot.isdigit() else code


def create_swap_task(tenant_id: str, site_id: str, serial_no: str, reason: str | None = None) -> dict[str, Any]:
    """A swap of the installed unit ``serial_no`` at its current position (raises ValueError if not installed)."""
    with tenant_tx(tenant_id) as cur:
        cur.execute(
            """
            SELECT e.serial_no, e.material, e.erp_equipment_no, e.equipment_class, l.id, l.code, l.sector_code, s.code
              FROM field.equipment e
              JOIN field.location l ON l.id = e.current_location_id
              JOIN field.site s ON s.id = l.site_id
             WHERE l.site_id = %s AND e.serial_no = %s AND e.status = 'installed'
            """,
            (site_id, serial_no),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"{serial_no} is not installed at site {site_id}")
        serial, material, eq_no, eq_class, loc_id, loc_code, sector, site_code = row
        position = position_label(sector, loc_code)
        title = f"Swap {eq_class if eq_class and eq_class != 'UNKNOWN' else material} at {position}"
        cur.execute(
            """
            INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle, reason)
            VALUES (%s, %s, 'swap', 'pending', 'normal', %s, %s, %s, %s) RETURNING id
            """,
            (tenant_id, site_id, title, eq_no, f"{site_code} · remove {serial}", reason),
        )
        task_row = cur.fetchone()
        if not task_row:
            raise RuntimeError("task insert returned no row")
        task_id = str(task_row[0])
        cur.execute(
            """
            INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, expected_qty, uom, status,
                   expected_serial, location_id, position, equipment_no)
            VALUES (%s, %s, %s, 10, 1, 'EA', 'pending', %s, %s, %s, %s) RETURNING id
            """,
            (tenant_id, site_id, task_id, serial, loc_id, position, eq_no),
        )
        line_row = cur.fetchone()
    return {"id": task_id, "type": "swap", "title": title, "line_id": str(line_row[0]) if line_row else None,
            "position": position, "expected_serial": serial, "equipment_no": eq_no}
