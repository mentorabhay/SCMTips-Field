"""Console (supervisor) endpoints of the M2 jobs contract §7 that did not exist before.

GET  /v1/approval-requests?status=pending   count differences (and other approvals) awaiting a decision
POST /v1/tasks/{task_id}/recount              a recount count task with a reason (FR3.031 - FR3.033)

The console is not operator-facing, so a PI approval shows book, counted and difference per item
(FR3.029 forbids that only on operator surfaces). The decision itself stays
POST /v1/approval-requests/{id}/decide (pi/api.py, SoD enforced there).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.http.pagination import decode_cursor, encode_cursor
from field_api.jobs.status import split_list, task_state_out
from field_api.pi.api import MAX_COUNTS, count_title

router = APIRouter(tags=["Console (M2)"])

APPROVAL_STATES = frozenset({"pending", "approved", "rejected", "cancelled"})
DEFAULT_RECOUNT_REASON = "Requested by an exception case: count differed from the books"


@router.get("/v1/approval-requests")
def list_approval_requests(
    status: str | None = Query("pending", description="one state or a comma list"),
    site_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission("field.discrepancy.approve")),
) -> dict[str, Any]:
    states = split_list(status) or ["pending"]
    if not set(states) <= APPROVAL_STATES:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Unknown approval status",
                         detail=f"status must be among {sorted(APPROVAL_STATES)}")
    after = decode_cursor(cursor) if cursor else None
    with principal_tx(principal) as cur:
        cur.execute(
            """
            SELECT a.id, a.approval_type, a.status, a.task_id, t.title, t.type, t.site_id, t.status, a.reason,
                   a.band, a.value_abs, a.currency, a.requested_by, a.created_at, a.pi_document_id,
                   a.excluded_principals, d.count_round
              FROM field.approval_request a
              JOIN field.task t ON t.id = a.task_id
              LEFT JOIN field.pi_document d ON d.id = a.pi_document_id
             WHERE a.status = ANY(%s) AND (%s::uuid IS NULL OR t.site_id = %s::uuid)
               AND (%s::uuid IS NULL OR a.id > %s::uuid)
             ORDER BY a.id LIMIT %s
            """,
            (states, site_id, site_id, after, after, limit + 1),
        )
        rows = cur.fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for r in rows:
            lines: list[dict[str, Any]] = []
            if r[14]:
                cur.execute(
                    """
                    SELECT l.id, l.storage_bin, m.erp_material_no, m.description, b.book_qty, l.counted_qty, l.uom
                      FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
                      LEFT JOIN field.material m ON m.id = l.material_id
                     WHERE b.pi_document_id = %s ORDER BY l.line_no
                    """,
                    (r[14],),
                )
                lines = [{"line_id": str(x[0]), "bin": x[1], "material": x[2], "description": x[3],
                          "book_qty": float(x[4]), "counted_qty": float(x[5]),
                          "difference": float(Decimal(x[5]) - Decimal(x[4])), "uom": x[6]} for x in cur.fetchall()]
            excluded = list(r[15] or [])
            own = principal.id == r[12] or principal.id in excluded
            one = lines[0] if len(lines) == 1 else None
            book = sum(x["book_qty"] for x in lines) if lines else None
            counted = sum(x["counted_qty"] for x in lines) if lines else None
            items.append({
                "id": str(r[0]), "task_id": str(r[3]), "title": r[4],
                "bin": (lines[0]["bin"] if lines and len({x["bin"] for x in lines}) == 1 else None),
                "material": one["material"] if one else None,
                "description": one["description"] if one else None,
                "uom": one["uom"] if one else None,
                "book_qty": book, "counted_qty": counted,
                "difference_qty": (counted - book) if lines and book is not None and counted is not None else None,
                "value_abs": float(r[10]) if r[10] is not None else None, "currency": r[11], "band": r[9],
                "recount_count": max(0, int(r[16] or 1) - 1), "requested_by": r[12], "excluded_principals": excluded,
                "can_decide": not own,
                "sod_note": ("You requested or counted this; another supervisor must decide (separation of duties)."
                             if own else None),
                "created_at": r[13].isoformat(),
                # beyond the integrator's shape (kept for the console and the smoke):
                "type": r[1], "status": r[2], "task_type": r[5], "site_id": str(r[6]),
                "task_status": task_state_out(r[7]), "reason": r[8], "lines": lines,
            })
    return {"items": items, "next_cursor": encode_cursor(str(rows[-1][0])) if more and rows else None}


class RecountIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.post("/v1/tasks/{task_id}/recount", status_code=201)
def request_recount(
    task_id: str,
    body: RecountIn | None = None,
    principal: Principal = Depends(require_permission("field.recount.assign")),
) -> dict[str, Any]:
    """New count task for the same bins and materials, a new PI document round with the frozen book of
    the first (FR3.035); the old task and document are cancelled and their pending approval closed.
    The recount must be counted by someone else (FR3.032); round 3 by an inventory controller (FR3.033)."""
    reason = (body.reason if body and body.reason else None) or DEFAULT_RECOUNT_REASON
    with principal_tx(principal) as cur:
        cur.execute("SELECT id, site_id, type, status FROM field.task WHERE id = %s::uuid FOR UPDATE", (task_id,))
        t = cur.fetchone()
        if not t:
            raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title="Task not found")
        if t[2] != "count":
            raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="Only a count can be recounted")
        if t[3] not in ("awaiting_approval", "in_progress"):
            raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="This count cannot be recounted now",
                             detail=f"task status is {task_state_out(t[3])}")
        cur.execute(
            "SELECT id, doc_number, fiscal_year, plant, storage_location, posting_blocked, freeze_book, count_round"
            " FROM field.pi_document WHERE task_id = %s::uuid AND status IN ('open', 'counted', 'recount') FOR UPDATE",
            (task_id,),
        )
        d = cur.fetchone()
        if not d:
            raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="This count has no open inventory document")
        new_round = int(d[7]) + 1
        if new_round > MAX_COUNTS:
            raise FieldError(status=409, code="FIELD-PI-409-MAX-COUNTS", title=f"At most {MAX_COUNTS} counts per item",
                             detail="Decide the approval request instead")
        cur.execute(
            """
            SELECT l.line_no, l.material_id, l.uom, l.storage_bin, b.book_qty, b.unit_price, b.currency
              FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
             WHERE b.pi_document_id = %s ORDER BY l.line_no
            """,
            (d[0],),
        )
        items = cur.fetchall()
        bins = {str(i[3]) for i in items if i[3]}
        doc_no = f"{str(d[1]).split('-R')[0]}-R{new_round}"
        cur.execute(
            """
            INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle, reason,
                   recount_of)
            VALUES (%s, %s, 'count', 'pending', 'high', %s, %s, %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, t[1], count_title(bins, recount=True), doc_no, f"PI {doc_no}", reason, task_id),
        )
        new_task = str(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO field.pi_document (tenant_id, doc_number, fiscal_year, plant, storage_location, posting_blocked,
                   freeze_book, status, site_id, task_id, requested_by, count_round, recount_of)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, doc_no, d[2], d[3], d[4], d[5], d[6], t[1], new_task, principal.id, new_round, d[0]),
        )
        new_pi = str(cur.fetchone()[0])
        for it in items:
            cur.execute(
                "INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,"
                " storage_bin, status) VALUES (%s, %s, %s, %s, %s, 0, %s, %s, 'pending') RETURNING id",
                (principal.tenant_id, t[1], new_task, it[0], it[1], it[2], it[3]),
            )
            line = str(cur.fetchone()[0])
            cur.execute(  # frozen book of the first count (freeze semantics, FR3.035)
                "INSERT INTO field.pi_book (tenant_id, pi_document_id, task_line_id, book_qty, unit_price, currency)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (principal.tenant_id, new_pi, line, it[4], it[5], it[6]),
            )
        cur.execute("UPDATE field.pi_document SET status = 'cancelled', closed_at = NOW() WHERE id = %s", (d[0],))
        cur.execute("UPDATE field.approval_request SET status = 'cancelled', decided_at = NOW(), approved_by = %s,"
                    " reason = COALESCE(reason, '') || ' | superseded by recount'"
                    " WHERE pi_document_id = %s AND status = 'pending'", (principal.id, d[0]))
        cur.execute("UPDATE field.task_line SET status = 'cancelled', version = version + 1, updated_at = NOW()"
                    " WHERE task_id = %s::uuid", (task_id,))
        cur.execute("UPDATE field.task SET status = 'cancelled', version = version + 1, updated_at = NOW()"
                    " WHERE id = %s::uuid", (task_id,))
    return {"task_id": new_task, "recount_of": task_id, "count_round": new_round, "reason": reason,
            "status": "open", "requested_at": datetime.now(UTC).isoformat()}
