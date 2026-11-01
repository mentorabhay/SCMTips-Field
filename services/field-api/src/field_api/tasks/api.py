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
from field_api.codes.resolve import barcodes_of
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.http.pagination import decode_cursor, encode_cursor
from field_api.jobs.counting import record_blind_count
from field_api.jobs.status import (
    TASK_TYPES,
    compose_subtitle,
    line_state_out,
    split_list,
    task_state_out,
    to_db_task_states,
)
from field_api.posting.staging import JobSpec, StagedDocument, stage_document
from field_api.warehouse.receiving.post import (
    GR_DOC_TYPE,
    GR_MOVEMENT_TYPE,
    goods_receipt_jobs,
    goods_receipt_queue_key,
    quality_storage_location,
)
from field_api.warehouse.receiving.tolerance import (
    VALID_UNDER_DELIVERY_REASONS,
    evaluate_receipt_tolerance,
)

router = APIRouter(tags=["Warehouse tasks (API3.xx)"])

VOICE_CONF_FLOOR = float(os.getenv("FIELD_VOICE_CONF_FLOOR", "0.80"))
UNDO_WINDOW_MIN = int(os.getenv("FIELD_UNDO_WINDOW_MIN", "30"))
COUNTABLE_LINE_STATES = frozenset({"pending", "in_progress", "counted", "confirmed", "flagged"})


def _err(status: int, code: str, title: str, detail: str | None = None) -> FieldError:
    return FieldError(code=code, status=status, title=title, detail=detail)


def _scope_check(principal: Principal, site_id: str | None) -> None:
    if site_id and "*" not in principal.site_ids and site_id not in principal.site_ids:
        raise _err(403, "FIELD-AUTH-403-SCOPE", "Site not in scope")


# --------------------------------------------------------------------------- API3.01
@router.get("/v1/tasks")
def list_tasks(
    site_id: str | None = None,
    type: str | None = Query(None, description="one type or a comma list, e.g. receive,putaway"),  # noqa: A002 - spec query parameter name
    status: str | None = Query(None, description="one state or a comma list, e.g. open,in_progress"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission("field.task.read")),
) -> dict[str, Any]:
    """Task list at M2 jobs contract §2. Operators see their sites (RLS); a '*' token sees all."""
    _scope_check(principal, site_id)
    types = split_list(type)
    unknown = sorted(set(types) - TASK_TYPES)
    if unknown:
        raise _err(422, "FIELD-HTTP-422-VALIDATION", "Unknown task type", f"type must be among {sorted(TASK_TYPES)}")
    states = to_db_task_states(split_list(status))
    if states is None:
        raise _err(422, "FIELD-HTTP-422-VALIDATION", "Unknown task status",
                   "status must be among open, in_progress, awaiting_posting, awaiting_approval, done, failed")
    after = decode_cursor(cursor) if cursor else None
    clauses: list[str] = ["TRUE"]
    params: list[Any] = []
    if site_id is not None:
        clauses.append("t.site_id::text = %s")
        params.append(site_id)
    if types:
        clauses.append("t.type = ANY(%s)")
        params.append(types)
    if states:
        clauses.append("t.status = ANY(%s)")
        params.append(states)
    if after:
        clauses.append("t.id > %s::uuid")
        params.append(after)
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT t.id, t.site_id, t.type, t.status, t.title, t.ref_doc_no, t.version, t.subtitle, t.reason,
                   t.due_at, t.updated_at, t.completed_at
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
        pieces: dict[str, Decimal] = {}
        if ids:
            cur.execute(
                """
                SELECT l.task_id, l.id, l.line_no, l.storage_bin, m.erp_material_no, l.uom,
                       l.expected_qty, l.counted_qty, l.status, l.version, t.type, l.picked_qty,
                       COALESCE(m.description, e.equipment_class), l.position, l.expected_serial,
                       COALESCE(m.erp_material_no, e.material), l.material_id
                  FROM field.task_line l
                  JOIN field.task t ON t.id = l.task_id
                  LEFT JOIN field.material m ON m.id = l.material_id
                  LEFT JOIN LATERAL (
                       SELECT eq.equipment_class, eq.material FROM field.equipment eq
                        WHERE l.expected_serial IS NOT NULL AND eq.serial_no = l.expected_serial
                        ORDER BY eq.updated_at DESC LIMIT 1) e ON TRUE
                 WHERE l.task_id = ANY(%s)
                 ORDER BY l.task_id, CASE WHEN t.type = 'pick' THEN l.storage_bin END NULLS LAST, l.line_no
                """,  # pick stops in walking order (bin code order, field_common.bin_stock.walking_order)
                (ids,),
            )
            line_rows = cur.fetchall()
            # M3: every barcode of the line's material, so the phone matches a scan on either (contract §2)
            codes = barcodes_of(cur, [str(r[16]) for r in line_rows if r[16]])
            for r in line_rows:
                ttype = r[10]
                item: dict[str, Any] = {
                    "id": str(r[1]),
                    "line_no": r[2],
                    "material": r[15],
                    "description": r[12],
                    "uom": r[5],
                    "bin": r[3],
                    "position": r[13],
                    "expected_serial": r[14],
                    "status": line_state_out(r[8]),
                    "version": r[9],
                    "barcodes": codes.get(str(r[16]), []) if r[16] else [],
                }
                if ttype != "count":  # blind count: never expected/book quantities (FR3.029)
                    item["expected_qty"] = float(r[6])
                    item["counted_qty"] = float(r[11] if ttype == "pick" else r[7])
                    pieces[str(r[0])] = pieces.get(str(r[0]), Decimal(0)) + Decimal(r[6])
                lines.setdefault(str(r[0]), []).append(item)
    items = []
    for r in rows:
        tid = str(r[0])
        tlines = lines.get(tid, [])
        items.append({
            "id": tid,
            "type": r[2],
            "status": task_state_out(r[3]),
            "title": r[4],
            "subtitle": compose_subtitle(r[2], r[7], len(tlines), pieces.get(tid, Decimal(0))),
            "ref_doc_no": r[5],
            "erp_ref": r[5],  # pre-M2 name, kept for older phone builds
            "reason": r[8],
            "due": r[9].isoformat() if r[9] else None,
            "site_id": str(r[1]),
            "version": r[6],
            "updated_at": r[10].isoformat() if r[10] else None,
            "completed_at": r[11].isoformat() if r[11] else None,
            "lines": tlines,
        })
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
        if ttype not in ("receive", "pick", "count"):
            raise _err(409, "FIELD-TASK-409-STATE", f"{ttype.capitalize()} jobs are not counted",
                       "Use the confirmations endpoint for put-away, audit and swap lines")
        if status not in COUNTABLE_LINE_STATES:
            raise _err(409, "FIELD-TASK-409-STATE", "Line already posted or in posting", f"line status is {status}")
        if body.uom != uom:
            raise _err(422, "FIELD-TASK-422-UOM", "Unit of measure mismatch", f"line uom is {uom}")
        if ttype == "count":
            version = record_blind_count(cur, principal, task_id, line_id, body.qty, body.uom, body.source,
                                         body.voice_event_id)
            return {"line_id": line_id, "counted_qty": float(body.qty), "source": body.source, "version": version}
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
    out: dict[str, Any] = {"line_id": line_id, "counted_qty": float(body.qty), "source": body.source,
                           "version": version}
    if ttype == "pick":
        out["picked_qty"] = float(body.qty)
    return out


# --------------------------------------------------------------------------- API3.05
class FlagIn(BaseModel):
    """``missing`` (any job; audit reasons not_found / removed_by_other / inaccessible), ``short``
    (pick: bin_empty / damaged / not_found, FR3.020; receive: an under-delivery reason), ``damaged``
    (receive: photo evidence and quantity, FR3.009), ``under`` (receive). ``reason`` is the contract
    name of ``reason_code``."""

    flag: Literal["damaged", "short", "under", "missing"]
    qty: Decimal | None = Field(default=None, ge=0)
    reason_code: str | None = None
    reason: str | None = None
    capture_id: str | None = None
    evidence_id: str | None = None


MISSING_REASONS = frozenset({"not_found", "removed_by_other", "inaccessible"})
SHORT_PICK_REASONS = frozenset({"bin_empty", "damaged", "not_found"})


@router.post("/v1/tasks/{task_id}/lines/{line_id}/flags")
def flag_line(
    task_id: str,
    line_id: str,
    body: FlagIn,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    reason = body.reason_code or body.reason
    with principal_tx(principal) as cur:
        _, status, _uom, ttype, _site, _v = _load_line(cur, task_id, line_id)
        if status not in COUNTABLE_LINE_STATES:
            raise _err(409, "FIELD-TASK-409-STATE", "Line already posted or in posting")
        if body.flag == "missing":
            reason = reason or "not_found"
            if reason not in MISSING_REASONS:
                raise _err(422, "FIELD-RCV-422-REASON", "Reason code missing or unknown", f"one of {sorted(MISSING_REASONS)}")
            cur.execute(
                """
                UPDATE field.task_line SET reason_code = %s, status = 'flagged', version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING damaged_qty, status
                """,
                (reason, line_id),
            )
        elif body.flag == "damaged":
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
            if ttype == "pick":
                # FR3.020 codes bin_empty / damaged / not_found, or the phone's own words ("picked 3 of 5")
                if not reason or len(reason) > 120:
                    raise _err(422, "FIELD-RCV-422-REASON", "Say why the pick is short",
                               f"one of {sorted(SHORT_PICK_REASONS)} or a short text")
                allowed = frozenset({reason})
            else:
                allowed = VALID_UNDER_DELIVERY_REASONS
            if reason not in allowed:
                raise _err(422, "FIELD-RCV-422-REASON", "Reason code missing or unknown", f"one of {sorted(allowed)}")
            cur.execute(
                """
                UPDATE field.task_line SET reason_code = %s, version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING damaged_qty, status
                """,
                (reason, line_id),
            )
        row = cur.fetchone()
    return {"line_id": line_id, "flag": body.flag, "reason": reason,
            "damaged_qty": float(row[0]) if row else 0.0,
            "status": line_state_out(row[1]) if row else line_state_out(status)}


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
    flags: dict[str, Decimal] | None = None,
    look_id: str | None = None,
) -> dict[str, Any]:
    """Stage the confirmed lines of a task (shared by API3.06 and the voice gate API2.14).

    M5 (receipts posted with a vision look, voice.py checks the look and the quantities): ``flags`` = flagged units
    per line id; they are part of the received quantity and post 101 to the quality storage location (101Q), and
    are recorded on the line (task_line.flag_qty) when the receipt is staged. ``look_id`` is linked to the staged
    document (vision_look.erp_document_id). Both None: the M4 staging, unchanged."""
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
        cur.execute("SELECT erp_plant, mode FROM field.site WHERE id = %s", (site_id,))
        srow = cur.fetchone()
        plant = (srow[0] if srow else None) or "1000"
        sandbox = bool(srow and srow[1] == "sandbox")
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
            if sandbox:  # M3 soft pegging: a home receipt expects exactly what was counted
                cur.execute("UPDATE field.task_line SET expected_qty = counted_qty, version = version + 1,"
                            " updated_at = NOW() WHERE id = ANY(%s::uuid[])", ([str(r[0]) for r in lines],))
            for r in lines:
                counted, damaged = float(r[4]), float(r[6])
                decision = evaluate_receipt_tolerance(
                    expected_qty=counted if sandbox else float(r[3]), counted_qty=counted,
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
            if not over_where and flags is not None:
                quality = {r[1]: float(flags.get(str(r[0]), Decimal(0))) for r in lines}
                for r in lines:
                    cur.execute("UPDATE field.task_line SET flag_qty = %s WHERE id = %s",
                                (flags.get(str(r[0]), Decimal(0)), r[0]))
                job_specs = goods_receipt_jobs(ref_doc, received, soft_pegging=sandbox, quality=quality,
                                               quality_sloc=quality_storage_location())
            elif not over_where:
                job_specs = goods_receipt_jobs(ref_doc, received, soft_pegging=sandbox)
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
            if look_id is not None:
                cur.execute("UPDATE field.vision_look SET erp_document_id = %s WHERE id = %s::uuid",
                            (staged.erp_document_id, look_id))
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
