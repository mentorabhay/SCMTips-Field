"""Finishing a job (M2 jobs contract §4) for the types that do not go through API3.06 staging.

receive and pick keep the API3.06 path (tasks/api.py confirm_task). Here:

- putaway: no SAP posting (IM plant, FR3.014). The confirmed bin receives the quantity in
  field.bin_stock, lines are done; status ``completed``, live event ``task.completed``.
- count: within tolerance the PI difference is staged for the worker (701/702 in erp-sim, queue
  PID:<doc>), status ``queued``; beyond tolerance an approval request for the console, task
  ``awaiting_approval``, live event ``count.awaiting_approval``; nothing posts.
  On a sandbox site (M3 contract section 3) a counted item with no book stock is opening stock: it posts
  movement 561 (initial entry) for the counted quantity, in the same queue, instead of a PI difference;
  the other items follow the rules above. Production never posts 561 from the field.
- audit: positions are reconciled (audit/reconcile.py); mismatches and missing units become open
  findings for the console (GET /v1/mismatches). Nothing posts to SAP. ``completed`` + ``task.completed``.
- swap: dismantle old + install new, two jobs with consecutive seq in the tower equipment queue
  EQUIP:<tower FL> (FR4.031 / FR4.036). The worker posts them to erp-sim; status ``queued``.

All of it runs in the caller's transaction (RLS-scoped to the principal).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from field_common.bin_stock import change_stock
from field_common.uuid7 import uuid7_str

from field_api.audit.reconcile import reconcile_task
from field_api.auth.jwt import Principal
from field_api.errors import FieldError
from field_api.jobs.counting import count_outcome, earlier_counters, pi_of_line
from field_api.pi.api import band_for, stage_pi_posting
from field_api.posting.staging import JobSpec, stage_document
from field_api.routes.live import emit_device_tick

COUNT_REASON = "count differed from the books"


def _state(title: str, detail: str | None = None) -> FieldError:
    return FieldError(status=409, code="FIELD-TASK-409-STATE", title=title, detail=detail)


def _tick(cur: Any, principal: Principal, kind: str, payload: dict[str, Any]) -> None:
    if principal.device_id:
        emit_device_tick(cur, principal.tenant_id, principal.device_id, kind, payload)


def _lines(cur: Any, task_id: str, line_ids: list[str]) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT l.id, l.line_no, l.status, l.expected_qty, l.counted_qty, l.storage_bin, l.confirmed_bin,
               l.material_id, m.erp_material_no, l.uom, l.expected_serial, l.captured_serial, l.new_serial,
               l.location_id, l.equipment_no
          FROM field.task_line l LEFT JOIN field.material m ON m.id = l.material_id
         WHERE l.task_id = %s::uuid AND l.id = ANY(%s::uuid[]) ORDER BY l.line_no FOR UPDATE OF l
        """,
        (task_id, line_ids),
    )
    keys = ("id", "line_no", "status", "expected_qty", "counted_qty", "bin", "confirmed_bin", "material_id",
            "material", "uom", "expected_serial", "captured_serial", "new_serial", "location_id", "equipment_no")
    return [dict(zip(keys, r, strict=True)) for r in cur.fetchall()]


def _all_line_ids(cur: Any, task_id: str) -> set[str]:
    cur.execute("SELECT id FROM field.task_line WHERE task_id = %s::uuid", (task_id,))
    return {str(r[0]) for r in cur.fetchall()}


def _complete_if_all_done(cur: Any, task_id: str) -> bool:
    cur.execute(
        """
        UPDATE field.task t SET status = CASE
                 WHEN NOT EXISTS (SELECT 1 FROM field.task_line l WHERE l.task_id = t.id
                                   AND l.status NOT IN ('done', 'posted', 'cancelled', 'waived'))
                 THEN 'completed' ELSE 'in_progress' END,
               version = version + 1, updated_at = NOW()
         WHERE t.id = %s::uuid RETURNING status
        """,
        (task_id,),
    )
    row = cur.fetchone()
    return bool(row and row[0] == "completed")


# --------------------------------------------------------------------------- putaway
def finish_putaway(cur: Any, principal: Principal, task: dict[str, Any], line_ids: list[str]) -> dict[str, Any]:
    lines = _lines(cur, task["id"], line_ids)
    for ln in lines:
        if not ln["confirmed_bin"] or ln["status"] != "confirmed":
            raise _state(f"Scan the bin for line {ln['line_no']} first")
    stored = []
    for ln in lines:
        change_stock(cur, tenant_id=principal.tenant_id, site_id=task["site_id"], storage_bin=ln["confirmed_bin"],
                     material_no=ln["material"] or "", material_id=str(ln["material_id"]) if ln["material_id"] else None,
                     delta=Decimal(ln["expected_qty"]), uom=ln["uom"])
        stored.append({"line_id": str(ln["id"]), "bin": ln["confirmed_bin"], "qty": float(ln["expected_qty"])})
    cur.execute("UPDATE field.task_line SET status = 'done', version = version + 1, updated_at = NOW()"
                " WHERE id = ANY(%s::uuid[])", (line_ids,))
    done = _complete_if_all_done(cur, task["id"])
    if done:
        _tick(cur, principal, "task.completed", {"task_id": task["id"], "type": "putaway"})
    return {"status": "completed" if done else "in_progress", "stored": stored}


# --------------------------------------------------------------------------- count
def finish_count(cur: Any, principal: Principal, task: dict[str, Any], line_ids: list[str],
                 idempotency_key: str) -> dict[str, Any]:
    if set(line_ids) != _all_line_ids(cur, task["id"]):
        raise _state("Count every item before you finish", "A count is posted for all its items together")
    lines = _lines(cur, task["id"], line_ids)
    for ln in lines:
        if ln["status"] != "counted":
            raise _state(f"Line {ln['line_no']} is not counted yet")
    pi_id, _round, _ = pi_of_line(cur, str(lines[0]["id"]))
    cur.execute("SELECT 1 FROM field.erp_document WHERE payload->>'pi_document_id' = %s", (pi_id,))
    if cur.fetchone():
        raise _state("This count was already sent")
    initial: dict[str, Any] | None = None
    if _site_mode(cur, task["site_id"]) == "sandbox":
        initial = stage_initial_entries(cur, principal, task, pi_id, len(lines), idempotency_key)
        if initial and initial["closes_pi"]:
            return {"status": "queued", "posting_request_id": initial["erp_document_id"],
                    "queue_key": initial["queue_key"], "initial_entry_request_id": initial["erp_document_id"]}
    extra = {"initial_entry_request_id": initial["erp_document_id"]} if initial else {}
    beyond, value, currency = count_outcome(cur, pi_id)
    if beyond:
        cur.execute("SELECT 1 FROM field.approval_request WHERE pi_document_id = %s::uuid AND status = 'pending'",
                    (pi_id,))
        if cur.fetchone():
            raise _state("This count is already waiting for a decision")
        cur.execute("SELECT DISTINCT counted_by FROM field.count_record WHERE pi_doc_id = %s", (pi_id,))
        excluded = sorted({principal.id, *{str(r[0]) for r in cur.fetchall() if r[0]}, *earlier_counters(cur, pi_id)})
        cur.execute(
            """
            INSERT INTO field.approval_request (tenant_id, task_id, approval_type, threshold_val, status, requested_by,
                   pi_document_id, value_abs, currency, band, excluded_principals, reason)
            VALUES (%s, %s, 'pi_variance', 0, 'pending', %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, task["id"], principal.id, pi_id, value, currency, band_for(value), excluded,
             COUNT_REASON),
        )
        apr = str(cur.fetchone()[0])
        cur.execute("UPDATE field.pi_document SET status = 'counted' WHERE id = %s::uuid", (pi_id,))
        cur.execute("UPDATE field.task SET status = 'awaiting_approval', version = version + 1, updated_at = NOW()"
                    " WHERE id = %s::uuid", (task["id"],))
        _tick(cur, principal, "count.awaiting_approval", {"task_id": task["id"]})
        # Never the value or the difference to the operator (FR3.029): only that a decision is pending.
        return {"status": "awaiting_approval", "approval_request_id": apr, **extra}
    erp_doc = stage_pi_posting(cur, principal.tenant_id, pi_id, idempotency_key, None, device_id=principal.device_id)
    return {"status": "queued", "posting_request_id": erp_doc, "queue_key": _queue_of(cur, erp_doc), **extra}


def _site_mode(cur: Any, site_id: str) -> str:
    cur.execute("SELECT mode FROM field.site WHERE id = %s::uuid", (site_id,))
    row = cur.fetchone()
    return str(row[0]) if row else "production"


def stage_initial_entries(cur: Any, principal: Principal, task: dict[str, Any], pi_id: str, line_count: int,
                          idempotency_key: str) -> dict[str, Any] | None:
    """Sandbox count: items counted with no book stock post movement 561 (initial entry), queue PID:<doc>.

    Returns {erp_document_id, queue_key, closes_pi} or None when no item is opening stock. ``closes_pi``:
    every item of the count is opening stock, so this document finishes the count and the task.
    """
    cur.execute(
        """
        SELECT l.id, m.erp_material_no, l.counted_qty, l.uom, l.storage_bin
          FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
          JOIN field.material m ON m.id = l.material_id
         WHERE b.pi_document_id = %s::uuid AND b.book_qty = 0 AND l.counted_qty > 0 AND l.status = 'counted'
         ORDER BY l.line_no
        """,
        (pi_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    cur.execute("SELECT doc_number, plant, storage_location, simulated FROM field.pi_document WHERE id = %s::uuid",
                (pi_id,))
    doc_no, plant, sloc, simulated = cur.fetchone()
    closes = len(rows) == line_count
    line_ids = [str(r[0]) for r in rows]
    staged = stage_document(
        cur, tenant_id=principal.tenant_id, site_id=task["site_id"], doc_type="INIT_STOCK", movement_type="561",
        queue_key=f"PID:{doc_no}", ref_doc_no=doc_no, plant=plant, idempotency_key=f"{idempotency_key}:561",
        payload={"task_id": task["id"], "line_ids": line_ids, "pi_document_id": pi_id, "closes_pi": closes,
                 "updates_task": closes, "line_status_after": "posted", "requested_by": principal.id,
                 "device_id": principal.device_id},
        jobs=[JobSpec("InitialStockEntry", {"StorageLocation": sloc, "Sandbox": True, "Simulated": bool(simulated)},
                      tuple({"Material": r[1], "QuantityInEntryUnit": f"{Decimal(r[2]):.3f}", "EntryUnit": r[3],
                             "StorageBin": r[4]} for r in rows))],
    )
    cur.execute("UPDATE field.task_line SET status = 'posting', version = version + 1, updated_at = NOW()"
                " WHERE id = ANY(%s::uuid[])", (line_ids,))
    if closes:
        cur.execute("UPDATE field.pi_document SET status = 'counted' WHERE id = %s::uuid", (pi_id,))
        cur.execute("UPDATE field.task SET status = 'posting', version = version + 1, updated_at = NOW()"
                    " WHERE id = %s::uuid", (task["id"],))
    return {"erp_document_id": staged.erp_document_id, "queue_key": staged.queue_key, "closes_pi": closes}


def _queue_of(cur: Any, erp_doc_id: str) -> str | None:
    cur.execute("SELECT queue_key FROM field.posting_job WHERE erp_doc_id = %s::uuid ORDER BY seq LIMIT 1",
                (erp_doc_id,))
    row = cur.fetchone()
    return str(row[0]) if row else None


# --------------------------------------------------------------------------- audit
def finish_audit(cur: Any, principal: Principal, task: dict[str, Any], line_ids: list[str]) -> dict[str, Any]:
    if set(line_ids) != _all_line_ids(cur, task["id"]):
        raise _state("Check every unit before you finish", "Scan each unit or mark it missing")
    lines = _lines(cur, task["id"], line_ids)
    open_ = [ln["line_no"] for ln in lines if not ln["captured_serial"] and ln["status"] != "flagged"]
    if open_:
        raise _state(f"{len(open_)} unit(s) not checked yet", f"lines {open_}: scan the serial or mark missing")
    summary = reconcile_task(cur, principal.tenant_id, task["id"])
    # Scanned units are done; units marked missing stay "flagged" (they are open findings now).
    cur.execute("UPDATE field.task_line SET status = 'done', version = version + 1, updated_at = NOW()"
                " WHERE task_id = %s::uuid AND status <> 'flagged'", (task["id"],))
    cur.execute("UPDATE field.task SET status = 'completed', version = version + 1, updated_at = NOW()"
                " WHERE id = %s::uuid", (task["id"],))
    _tick(cur, principal, "task.completed", {"task_id": task["id"], "type": "audit"})
    return {"status": "completed", "reconciliation": summary}


# --------------------------------------------------------------------------- swap
def _tower_and_position(cur: Any, location_id: Any) -> tuple[str, str]:
    """(tower FL = queue scope, position FL = install target) of a line's location."""
    cur.execute(
        """
        WITH RECURSIVE up(id, parent_id, kind, fl_code, depth) AS (
            SELECT id, parent_id, kind, fl_code, 0 FROM field.location WHERE id = %s::uuid
            UNION ALL
            SELECT l.id, l.parent_id, l.kind, l.fl_code, up.depth + 1 FROM field.location l JOIN up ON l.id = up.parent_id
        )
        SELECT kind, fl_code, depth FROM up ORDER BY depth
        """,
        (str(location_id),),
    )
    rows = cur.fetchall()
    if not rows or not rows[0][1]:
        raise _state("This position has no functional location", "The swap cannot be posted to SAP")
    position_fl = str(rows[0][1])
    tower = next((r for r in rows if r[0] in ("tower_site", "tower") and r[1]), rows[-1])
    return str(tower[1]), position_fl


def finish_swap(cur: Any, principal: Principal, task: dict[str, Any], line_ids: list[str],
                idempotency_key: str) -> dict[str, Any]:
    lines = _lines(cur, task["id"], line_ids)
    if len(lines) != 1:
        raise _state("A swap has exactly one line")
    ln = lines[0]
    if not ln["captured_serial"] or not ln["new_serial"] or ln["status"] != "confirmed":
        raise _state("Scan the old unit and the new unit first")
    if not ln["equipment_no"]:
        raise _state("The unit to remove has no SAP equipment number")
    tower_fl, position_fl = _tower_and_position(cur, ln["location_id"])
    queue_key = f"EQUIP:{tower_fl}"
    erp_doc_id = uuid7_str()
    cur.execute(
        """
        INSERT INTO field.erp_document (id, tenant_id, site_id, doc_type, movement_type, payload, status)
        VALUES (%s, %s, %s, 'EQ_SWAP', 'REPLACE', %s, 'pending')
        """,
        (erp_doc_id, principal.tenant_id, task["site_id"], json.dumps({
            "task_id": task["id"], "line_ids": [str(ln["id"])], "requested_by": principal.id,
            "device_id": principal.device_id, "old_serial": ln["captured_serial"], "new_serial": ln["new_serial"],
            "position_fl": position_fl, "location_id": str(ln["location_id"]), "line_status_after": "done",
        })),
    )
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{principal.tenant_id}:{queue_key}",))
    cur.execute("SELECT COALESCE(MAX(seq), 0) FROM field.posting_job WHERE queue_key = %s", (queue_key,))
    seq = int(cur.fetchone()[0])
    steps = (
        ("dismantle", ln["equipment_no"], ln["captured_serial"], False),
        ("install", None, ln["new_serial"], True),  # equipment no. of the new unit: the worker reads it from SAP
    )
    for i, (op, eq_no, serial, final) in enumerate(steps, start=1):
        seq += 1
        cur.execute(
            """
            INSERT INTO field.posting_job (id, tenant_id, erp_doc_id, queue_key, seq, ref_doc_no, payload, status,
                   next_attempt_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
            """,
            (uuid7_str(), principal.tenant_id, erp_doc_id, queue_key, seq, ln["equipment_no"], json.dumps({
                "site_id": task["site_id"], "operation": op, "equipment_no": eq_no, "serial_no": serial,
                "material": ln["material"], "tower_fl": tower_fl, "target_fl": position_fl,
                "expected_fl": position_fl if op == "dismantle" else None,
                "idempotency_key": f"{idempotency_key}:{i}", "final": final,
            })),
        )
    cur.execute("UPDATE field.task_line SET status = 'posting', version = version + 1, updated_at = NOW()"
                " WHERE id = %s::uuid", (str(ln["id"]),))
    cur.execute("UPDATE field.task SET status = 'posting', version = version + 1, updated_at = NOW()"
                " WHERE id = %s::uuid", (task["id"],))
    return {"status": "queued", "posting_request_id": erp_doc_id, "queue_key": queue_key}
