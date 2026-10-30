"""Warehouse task API at the spec contract, backed by Postgres with RLS (C4).

API3.01  GET  /v1/tasks                                   operator projection (FR3.029)
API3.04  POST /v1/tasks/{task_id}/lines/{line_id}/counts  voice/scan count (floor 0.80)
API3.05  POST /v1/tasks/{task_id}/lines/{line_id}/flags   damaged / short / under reason
API3.06  POST /v1/tasks/{task_id}/confirm                  stage erp_document + ordered posting jobs
API3.07  POST /v1/erp-documents/{id}/reverse               102 / 602 reversal (FR3.011, FR3.024)

Every handler runs inside ``principal_tx`` so tenant and site scope come from the token and RLS
does the isolation. No module-level state.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.http.pagination import decode_cursor, encode_cursor
from field_api.posting.staging import JobSpec, StagedDocument, stage_document
from field_api.warehouse.receiving.post import (
    GR_DOC_TYPE,
    GR_MOVEMENT_TYPE,
    goods_receipt_jobs,
    goods_receipt_queue_key,
)
from field_api.warehouse.receiving.tolerance import (
    VALID_UNDER_DELIVERY_REASONS,
    evaluate_receipt_tolerance,
)

router = APIRouter(tags=["Warehouse tasks (API3.xx)"])

VOICE_CONF_FLOOR = float(os.getenv("FIELD_VOICE_CONF_FLOOR", "0.80"))
UNDO_WINDOW_MIN = int(os.getenv("FIELD_UNDO_WINDOW_MIN", "30"))
TASK_TYPES = frozenset({"receive", "putaway", "pick", "count"})
COUNTABLE_LINE_STATES = frozenset({"pending", "in_progress", "counted"})


def _err(status: int, code: str, title: str, detail: str | None = None) -> FieldError:
    return FieldError(code=code, status=status, title=title, detail=detail)


def _scope_check(principal: Principal, site_id: str | None) -> None:
    if site_id and "*" not in principal.site_ids and site_id not in principal.site_ids:
        raise _err(403, "FIELD-AUTH-403-SCOPE", "Site not in scope")


# --------------------------------------------------------------------------- API3.01
@router.get("/v1/tasks")
def list_tasks(
    site_id: str | None = None,
    type: str | None = Query(None),  # noqa: A002 - spec query parameter name
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission("field.task.read")),
) -> dict[str, Any]:
    _scope_check(principal, site_id)
    if type is not None and type not in TASK_TYPES:
        raise _err(422, "FIELD-HTTP-422-VALIDATION", "Unknown task type", f"type must be one of {sorted(TASK_TYPES)}")
    after = decode_cursor(cursor) if cursor else None
    clauses, params = ["TRUE"], []
    for col, val in (("t.site_id::text", site_id), ("t.type", type), ("t.status", status)):
        if val is not None:
            clauses.append(f"{col} = %s")
            params.append(val)
    if after:
        clauses.append("t.id > %s::uuid")
        params.append(after)
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT t.id, t.site_id, t.type, t.status, t.title, t.ref_doc_no, t.version
              FROM field.task t
             WHERE {' AND '.join(clauses)}
             ORDER BY t.id
             LIMIT %s
            """,  # noqa: S608 - clauses are fixed strings; values are parameters
            (*params, limit + 1),
        )
        rows = cur.fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        ids = [r[0] for r in rows]
        lines: dict[str, list[dict[str, Any]]] = {}
        if ids:
            cur.execute(
                """
                SELECT l.task_id, l.id, l.line_no, l.storage_bin, m.erp_material_no, l.uom,
                       l.expected_qty, l.counted_qty, l.status, l.version, t.type
                  FROM field.task_line l
                  JOIN field.task t ON t.id = l.task_id
                  LEFT JOIN field.material m ON m.id = l.material_id
                 WHERE l.task_id = ANY(%s)
                 ORDER BY l.task_id, l.line_no
                """,
                (ids,),
            )
            for r in cur.fetchall():
                item: dict[str, Any] = {
                    "id": str(r[1]),
                    "line_no": r[2],
                    "bin": r[3],
                    "material": r[4],
                    "uom": r[5],
                    "status": r[8],
                    "version": r[9],
                }
                if r[10] != "count":  # blind count: never expected/book quantities (FR3.029)
                    item["expected_qty"] = float(r[6])
                    item["counted_qty"] = float(r[7])
                lines.setdefault(str(r[0]), []).append(item)
    items = [
        {
            "id": str(r[0]),
            "site_id": str(r[1]),
            "type": r[2],
            "status": r[3],
            "title": r[4],
            "erp_ref": r[5],
            "version": r[6],
            "lines": lines.get(str(r[0]), []),
        }
        for r in rows
    ]
    return {"items": items, "next_cursor": encode_cursor(str(rows[-1][0])) if more and rows else None}


# --------------------------------------------------------------------------- API3.04
class CountIn(BaseModel):
    qty: Decimal = Field(ge=0)
    uom: str
    source: Literal["voice", "scan", "manual"] = "voice"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    voice_event_id: str | None = None
    capture_id: str | None = None


def _load_line(cur: Any, task_id: str, line_id: str) -> tuple[Any, ...]:
    cur.execute(
        """
        SELECT l.id, l.status, l.uom, t.type, t.site_id, l.version
          FROM field.task_line l JOIN field.task t ON t.id = l.task_id
         WHERE l.id = %s::uuid AND l.task_id = %s::uuid
         FOR UPDATE OF l
        """,
        (line_id, task_id),
    )
    row = cur.fetchone()
    if not row:
        raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "Task line not found")
    return tuple(row)


@router.post("/v1/tasks/{task_id}/lines/{line_id}/counts")
def record_count(
    task_id: str,
    line_id: str,
    body: CountIn,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    if body.source == "voice" and (body.confidence is None or body.confidence < VOICE_CONF_FLOOR):
        raise _err(
            422, "FIELD-VOICE-422-CONFIDENCE", "Voice confidence below floor",
            f"confidence must be >= {VOICE_CONF_FLOOR:.2f}; ask the operator to repeat",
        )
    with principal_tx(principal) as cur:
        _, status, uom, ttype, _site, _v = _load_line(cur, task_id, line_id)
        if ttype not in ("receive", "pick"):
            raise _err(409, "FIELD-TASK-409-STATE", "Counts on this task type use the PI endpoint")
        if status not in COUNTABLE_LINE_STATES:
            raise _err(409, "FIELD-TASK-409-STATE", "Line already posted or in posting", f"line status is {status}")
        if body.uom != uom:
            raise _err(422, "FIELD-TASK-422-UOM", "Unit of measure mismatch", f"line uom is {uom}")
        qty_col = "picked_qty" if ttype == "pick" else "counted_qty"
        cur.execute(
            f"""
            UPDATE field.task_line SET {qty_col} = %s, status = 'counted', version = version + 1, updated_at = NOW()
             WHERE id = %s::uuid RETURNING version
            """,  # noqa: S608 - column chosen from a fixed pair
            (body.qty, line_id),
        )
        row = cur.fetchone()
        version = int(row[0]) if row else 0
        cur.execute(
            """
            INSERT INTO field.count_record
                (tenant_id, task_id, task_line_id, capture_id, voice_event_id, quantity, unit, counted_by, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (principal.tenant_id, task_id, line_id, body.capture_id, body.voice_event_id,
             body.qty, body.uom, principal.id, body.source),
        )
        cur.execute(
            "UPDATE field.task SET status = 'in_progress', updated_at = NOW() WHERE id = %s::uuid AND status = 'pending'",
            (task_id,),
        )
    return {"line_id": line_id, "counted_qty": float(body.qty), "source": body.source, "version": version}


# --------------------------------------------------------------------------- API3.05
class FlagIn(BaseModel):
    flag: Literal["damaged", "short", "under"]
    qty: Decimal | None = Field(default=None, ge=0)
    reason_code: str | None = None
    capture_id: str | None = None
    evidence_id: str | None = None


@router.post("/v1/tasks/{task_id}/lines/{line_id}/flags")
def flag_line(
    task_id: str,
    line_id: str,
    body: FlagIn,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        _, status, _uom, _ttype, _site, _v = _load_line(cur, task_id, line_id)
        if status not in COUNTABLE_LINE_STATES:
            raise _err(409, "FIELD-TASK-409-STATE", "Line already posted or in posting")
        if body.flag == "damaged":
            if not (body.capture_id and body.evidence_id) or body.qty is None:
                raise _err(422, "FIELD-RCV-422-EVIDENCE", "Photo evidence and damaged quantity required")
            cur.execute("SELECT 1 FROM field.capture WHERE id = %s::uuid", (body.capture_id,))
            if not cur.fetchone():
                raise _err(422, "FIELD-RCV-422-EVIDENCE", "Referenced capture does not exist")
            cur.execute(
                """
                UPDATE field.task_line SET damaged_qty = %s, damage_evidence_id = %s::uuid,
                       status = CASE WHEN status = 'pending' THEN 'in_progress' ELSE status END,
                       version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING damaged_qty, status
                """,
                (body.qty, body.evidence_id, line_id),
            )
        else:
            if body.reason_code not in VALID_UNDER_DELIVERY_REASONS:
                raise _err(422, "FIELD-RCV-422-REASON", "Reason code missing or unknown",
                           f"one of {sorted(VALID_UNDER_DELIVERY_REASONS)}")
            cur.execute(
                """
                UPDATE field.task_line SET reason_code = %s, version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING damaged_qty, status
                """,
                (body.reason_code, line_id),
            )
        row = cur.fetchone()
    return {"line_id": line_id, "damaged_qty": float(row[0]) if row else 0.0, "status": row[1] if row else status}


# --------------------------------------------------------------------------- API3.06
class ConfirmIn(BaseModel):
    stage_id: str | None = None
    lines: list[str] | None = None


@router.post("/v1/tasks/{task_id}/confirm")
def confirm_task_route(
    task_id: str,
    body: ConfirmIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.post.confirm")),
) -> dict[str, Any]:
    return confirm_task(task_id, body, idempotency_key, principal)


def confirm_task(
    task_id: str,
    body: ConfirmIn,
    idempotency_key: str,
    principal: Principal,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage the confirmed lines of a task (shared by API3.06 and the voice gate API2.14)."""
    with principal_tx(principal) as cur:
        cur.execute(
            "SELECT id, site_id, type, status, ref_doc_no FROM field.task WHERE id = %s::uuid FOR UPDATE",
            (task_id,),
        )
        task = cur.fetchone()
        if not task:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "Task not found")
        _, site_id, ttype, _tstatus, ref_doc = task
        if ttype not in ("receive", "pick"):
            raise _err(409, "FIELD-TASK-409-STATE", f"Confirm is not defined for {ttype} tasks here")
        cur.execute(
            """
            SELECT l.id, l.line_no, l.status, l.expected_qty, l.counted_qty, l.picked_qty, l.damaged_qty,
                   l.over_tolerance_pct, l.under_tolerance_pct, l.reason_code, l.storage_bin, l.material_id, l.uom
              FROM field.task_line l WHERE l.task_id = %s::uuid ORDER BY l.line_no FOR UPDATE
            """,
            (task_id,),
        )
        all_lines = cur.fetchall()
        wanted = set(body.lines) if body.lines else None
        lines = [r for r in all_lines if (wanted is None and r[2] == "counted") or (wanted and str(r[0]) in wanted)]
        if not lines:
            raise _err(409, "FIELD-TASK-409-STATE", "No counted lines to confirm")
        for r in lines:
            if r[2] != "counted":
                raise _err(409, "FIELD-TASK-409-STATE", f"Line {r[1]} is {r[2]}, not counted")
        cur.execute("SELECT erp_plant FROM field.site WHERE id = %s", (site_id,))
        srow = cur.fetchone()
        plant = (srow[0] if srow else None) or "1000"
        # FR3.036: no movements on bin/material pairs under an open PI with posting block.
        cur.execute(
            """
            SELECT tl.storage_bin, tl.material_id FROM field.pi_book b
              JOIN field.pi_document d ON d.id = b.pi_document_id
              JOIN field.task_line tl ON tl.id = b.task_line_id
             WHERE d.posting_blocked AND d.status IN ('open', 'counted', 'recount')
            """
        )
        blocked = {(r[0], r[1]) for r in cur.fetchall()}
        for r in lines:
            if (r[10], r[11]) in blocked:
                raise _err(423, "FIELD-PI-423-POSTING-BLOCKED", "Bin under count",
                           f"bin {r[10]} is on an open PI document with posting block")
        job_specs: list[JobSpec] = []
        over_where: str | None = None
        if ttype == "receive":
            received: list[tuple[int | str, float]] = []
            for r in lines:
                counted, damaged = float(r[4]), float(r[6])
                decision = evaluate_receipt_tolerance(
                    expected_qty=float(r[3]), counted_qty=counted,
                    over_tolerance_pct=float(r[7]), under_tolerance_pct=float(r[8]),
                    reason_code=r[9],
                )
                if decision.status == "OVER_DELIVERY_BLOCKED":
                    cur.execute(
                        """
                        INSERT INTO field.approval_request (tenant_id, task_id, approval_type, status, requested_by, reason)
                        VALUES (%s, %s, 'receipt_over_tolerance', 'pending', %s, %s)
                        """,
                        (principal.tenant_id, task_id, principal.id, f"line {r[1]}: counted {counted} > tolerance"),
                    )
                    # The case must survive the 409: stop staging, commit the case, raise after the tx.
                    over_where = f"line {r[1]}"
                    break
                if decision.status == "UNDER_DELIVERY_NEEDS_REASON":
                    raise _err(422, "FIELD-RCV-422-REASON", "Reason code missing", f"line {r[1]} is under-delivered")
                received.append((r[1], counted - damaged))  # FIELD_DAMAGED_MODE=reject (spec default)
            doc_type, mvt, queue_key = GR_DOC_TYPE, GR_MOVEMENT_TYPE, goods_receipt_queue_key(ref_doc)
            if not over_where:
                job_specs = goods_receipt_jobs(ref_doc, received)
        else:
            for r in lines:
                job_specs.append(JobSpec("OutboundDeliveryPick", {
                    "DeliveryDocument": ref_doc,
                    "DeliveryDocumentItem": str(r[1]).zfill(6),
                    "PickedQuantity": f"{float(r[5]):.3f}",
                }))
            job_specs.append(JobSpec("GoodsIssue", {"DeliveryDocument": ref_doc}))
            doc_type, mvt, queue_key = "GI", "601", f"OBD:{ref_doc}"
        staged: StagedDocument | None = None
        if not over_where:
            staged = _stage_confirm(cur, principal, task_id, str(site_id), doc_type, mvt, queue_key,
                                    ref_doc, plant, idempotency_key, job_specs, [str(r[0]) for r in lines],
                                    extra_payload or {})
    if staged is None:
        raise _OverTolerance(over_where or "")
    return {"erp_document_id": staged.erp_document_id, "queue_key": staged.queue_key,
            "jobs": len(staged.job_ids), "status": "queued"}


def _stage_confirm(
    cur: Any, principal: Principal, task_id: str, site_id: str, doc_type: str, mvt: str,
    queue_key: str, ref_doc: str, plant: str, idempotency_key: str,
    job_specs: list[JobSpec], line_ids: list[str], extra_payload: dict[str, Any],
) -> StagedDocument:
    staged = stage_document(
        cur,
        tenant_id=principal.tenant_id, site_id=site_id, doc_type=doc_type, movement_type=mvt,
        queue_key=queue_key, ref_doc_no=ref_doc, plant=plant, idempotency_key=idempotency_key,
        payload={"task_id": task_id, "line_ids": line_ids, "requested_by": principal.id,
                 "device_id": principal.device_id,
                 "requested_at": datetime.now(UTC).isoformat(), "delivery_document": ref_doc, **extra_payload},
        jobs=job_specs,
    )
    cur.execute(
        "UPDATE field.task_line SET status = 'posting', version = version + 1, updated_at = NOW()"
        " WHERE id = ANY(%s::uuid[])",
        (line_ids,),
    )
    cur.execute("UPDATE field.task SET status = 'posting', updated_at = NOW() WHERE id = %s::uuid", (task_id,))
    return staged


class _OverTolerance(FieldError):
    def __init__(self, where: str) -> None:
        super().__init__(code="FIELD-RCV-409-OVER-TOLERANCE", status=409,
                         title="Over-delivery beyond tolerance", detail=f"{where}: supervisor decision needed")


# --------------------------------------------------------------------------- API3.07
class ReverseIn(BaseModel):
    items: list[str] | None = None
    reason: str = Field(min_length=1)


@router.post("/v1/erp-documents/{doc_id}/reverse")
def reverse_document(
    doc_id: str,
    body: ReverseIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.post.confirm")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(
            """
            SELECT id, site_id, doc_type, status, doc_number, fiscal_year, payload, created_at
              FROM field.erp_document WHERE id = %s::uuid FOR UPDATE
            """,
            (doc_id,),
        )
        doc = cur.fetchone()
        if not doc:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "ERP document not found")
        _, site_id, doc_type, status, doc_no, year, payload, created_at = doc
        cur.execute("SELECT 1 FROM field.erp_document WHERE reversal_of_id = %s::uuid", (doc_id,))
        if status == "reversed" or cur.fetchone():
            raise _err(409, "FIELD-ERP-409-ALREADY-REVERSED", "Document already reversed")
        if status != "posted" or not doc_no:
            raise _err(409, "FIELD-ERP-409-NOT-POSTED", "Document not posted yet")
        if doc_type not in ("GR", "GI"):
            raise _err(409, "FIELD-ERP-409-NOT-REVERSIBLE", f"{doc_type} documents are not reversed here")
        own = payload.get("requested_by") == principal.id
        in_window = datetime.now(UTC) - created_at <= timedelta(minutes=UNDO_WINDOW_MIN)
        supervisor = has_permission(principal.permissions, "field.task.manage")
        if not ((own and in_window) or supervisor):
            raise _err(403, "FIELD-AUTH-403-PERMISSION", "Only the poster within the undo window, or a supervisor")
        rev_type, mvt, after = ("GR_REV", "102", "reversed") if doc_type == "GR" else ("GI_REV", "602", "picked")
        cur.execute("SELECT erp_plant FROM field.site WHERE id = %s", (site_id,))
        srow = cur.fetchone()
        staged = stage_document(
            cur,
            tenant_id=principal.tenant_id, site_id=str(site_id), doc_type=rev_type, movement_type=mvt,
            queue_key=f"{'IBD' if doc_type == 'GR' else 'OBD'}:{payload.get('delivery_document')}",
            ref_doc_no=doc_no, plant=(srow[0] if srow else None) or "1000", idempotency_key=idempotency_key,
            payload={"task_id": payload.get("task_id"), "line_ids": payload.get("line_ids", []),
                     "reverses": doc_id, "line_status_after": after, "reason": body.reason,
                     "requested_by": principal.id, "device_id": principal.device_id,
                     "delivery_document": payload.get("delivery_document")},
            jobs=[JobSpec("Cancellation", {"MaterialDocument": doc_no, "MaterialDocumentYear": year,
                                           "Items": body.items or []})],
            reversal_of_id=doc_id,
        )
    return {"erp_document_id": staged.erp_document_id, "doc_type": rev_type, "status": "queued"}
