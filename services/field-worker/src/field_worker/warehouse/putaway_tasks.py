"""Put-away task after a posted goods receipt (FR3.013 / T3.025; M2 jobs contract §4 "receive").

When the worker writes back the material document of a goods receipt (101), it creates one put-away
task for what was received: one line per received material, ``storage_bin`` = the proposed bin
(field_common.bin_stock.propose_bin: the material's fixed bin, else the first empty bin of the
site's bin tree, else the least-filled bin), ``expected_qty`` = the received quantity
(counted minus damaged, FIELD_DAMAGED_MODE=reject).

Idempotent per material document: the task's ref_doc_no is the GR material document number, so a
replayed finalize (pre-post probe adoption) never creates a second task.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg
from field_common.bin_stock import propose_bin


def create_putaway_task(
    cur: psycopg.Cursor[Any], tenant_id: str, gr_payload: dict[str, Any], doc_number: str
) -> tuple[str, str] | None:
    """Create the put-away task for a posted GR; returns (task_id, title) or None if nothing to store."""
    receive_task = gr_payload.get("task_id")
    line_ids = gr_payload.get("line_ids") or []
    if not receive_task or not line_ids or not doc_number:
        return None
    cur.execute("SELECT site_id, ref_doc_no FROM field.task WHERE id = %s AND tenant_id = %s", (receive_task, tenant_id))
    trow = cur.fetchone()
    if not trow:
        return None
    site_id, delivery = str(trow[0]), trow[1]
    # Scoped explicitly (not only by RLS): material document numbers repeat after an erp-sim reset.
    cur.execute("SELECT 1 FROM field.task WHERE tenant_id = %s AND site_id = %s AND type = 'putaway' AND ref_doc_no = %s",
                (tenant_id, site_id, doc_number))
    if cur.fetchone():
        return None
    cur.execute(
        """
        SELECT l.line_no, l.material_id, m.erp_material_no, l.uom, l.counted_qty - l.damaged_qty
          FROM field.task_line l LEFT JOIN field.material m ON m.id = l.material_id
         WHERE l.id = ANY(%s::uuid[]) ORDER BY l.line_no
        """,
        (line_ids,),
    )
    received = [r for r in cur.fetchall() if Decimal(r[4]) > 0]
    if not received:
        return None
    title = f"Put away delivery {delivery}" if delivery else f"Put away {doc_number}"
    cur.execute(
        """
        INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle)
        VALUES (%s, %s, 'putaway', 'pending', 'normal', %s, %s, %s) RETURNING id
        """,
        (tenant_id, site_id, title, doc_number, f"Goods receipt {doc_number}"),
    )
    row = cur.fetchone()
    if not row:
        return None
    task_id = str(row[0])
    chosen: set[str] = set()
    for n, (_line_no, material_id, material_no, uom, qty) in enumerate(received, start=1):
        bin_, _rule = propose_bin(cur, site_id, material_no or "", reserved=chosen)
        if bin_:
            chosen.add(bin_)
        cur.execute(
            """
            INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,
                   storage_bin, target_bin, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (tenant_id, site_id, task_id, n * 10, material_id, qty, uom, bin_, bin_),
        )
    return task_id, title
