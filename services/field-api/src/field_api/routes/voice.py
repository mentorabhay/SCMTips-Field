"""Voice events, count records and the voice confirm gate (API2.12-2.14 / FR2.038, FR2.050, FR2.055).

BRIEF §1.3: the system never posts on speech alone. A post request is accepted only when an accepted
``post`` voice event is followed, on the same device and task, by an accepted ``confirm`` voice event
within FIELD_CONFIRM_TIMEOUT_S (10 s), and the client's ``staged_hash`` equals the server's hash of
exactly the lines being posted (so the operator confirmed what is posted). The posting itself is the
same atomic staging as API3.06.

staged_hash = sha256("|".join(sorted(f"{line_id}:{qty:.3f}"))) over the lines in the request, where
qty is, per task type (M2 jobs contract §4): counted_qty for receive and count, picked_qty for pick,
expected_qty for putaway, audit and swap. The confirmation is voice (the turn pair above) or touch
(``confirm: {method: "touch"}``: the operator pressed "Yes, post it" on the review screen).

M5 (docs/design/M5_CONTRACT.md §2, receipts only): ``look_id`` links a vision look of this task to the receipt, and
``flag_qty`` ({line id: units}, needs ``look_id``) flags part of a line's counted quantity: those units post 101 to
the quality storage location (101Q), the rest 101 to the delivery's storage location, in one material document.
The counted quantity (and so staged_hash) stays the whole received quantity, good plus flagged: "receive 18, flag 2"
is a count of 20 with flag_qty 2. A flag is at most the counted minus the damaged quantity of its line. A look that
is already linked to a document that did not fail is refused (409 FIELD-VIS-409-POSTED). Without both fields the
request is the M4 one.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Header
from psycopg import sql
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.jobs.finish import finish_audit, finish_count, finish_putaway, finish_swap
from field_api.jobs.status import hash_quantity_column
from field_api.tasks.api import ConfirmIn, CountIn, confirm_task, record_count

router = APIRouter(prefix="/v1", tags=["Voice and posting"])

VOICE_FLOOR = float(os.getenv("FIELD_VOICE_CONF_FLOOR", "0.80"))
CONFIRM_TIMEOUT_S = float(os.getenv("FIELD_CONFIRM_TIMEOUT_S", "10"))
ERR_NO_CONFIRM = FieldError(status=422, code="FIELD-POST-422-NO-CONFIRM", title="Confirm turn missing or invalid")


def staged_hash(lines: list[tuple[str, Decimal]]) -> str:
    return hashlib.sha256("|".join(sorted(f"{lid}:{Decimal(q):.3f}" for lid, q in lines)).encode()).hexdigest()


class VoiceEventRequest(BaseModel):
    device_id: str
    task_id: str | None = None
    capture_id: str | None = None
    transcript: str = Field(min_length=1, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
    intent: str = Field(min_length=1, max_length=32)
    is_accepted: bool = True
    locale: str = "en"
    client_timestamp: datetime | None = None


@router.post("/voice-events", status_code=201)
async def record_voice_event(
    req: VoiceEventRequest,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    if principal.device_id and principal.device_id != req.device_id:
        raise FieldError(status=403, code="FIELD-AUTH-401-BINDING", title="Device binding mismatch")
    if req.is_accepted and req.confidence < VOICE_FLOOR:
        raise FieldError(status=422, code="FIELD-VOICE-422-ACCEPTED-BELOW-FLOOR",
                         title=f"Accepted voice event below {VOICE_FLOOR:.2f} confidence")
    with principal_tx(principal) as cur:
        cur.execute(
            """
            INSERT INTO field.voice_event (tenant_id, device_id, task_id, capture_id, transcript, confidence, intent,
                   is_accepted, locale, client_timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, NOW())) RETURNING id, created_at
            """,
            (principal.tenant_id, req.device_id, req.task_id, req.capture_id, req.transcript, req.confidence,
             req.intent, req.is_accepted, req.locale, req.client_timestamp),
        )
        row = cur.fetchone()
    return {"id": str(row[0]), "created_at": row[1].isoformat()}


class CountRecordRequest(BaseModel):
    task_line_id: str
    capture_id: str | None = None
    kind: Literal["count"] = "count"
    value: Decimal = Field(ge=0)
    unit: str
    voice_event_id: str | None = None
    source: Literal["voice", "scan", "manual"] = "voice"


@router.post("/count-records", status_code=201)
async def create_count_record(
    req: CountRecordRequest,
    principal: Principal = Depends(require_permission("field.count.create")),
) -> dict[str, Any]:
    if req.source == "voice" and req.value > 9999:
        raise FieldError(status=422, code="FIELD-COUNT-422-RANGE", title="Voice count outside 0-9999")
    confidence = None
    with principal_tx(principal) as cur:
        cur.execute("SELECT task_id FROM field.task_line WHERE id = %s::uuid", (req.task_line_id,))
        row = cur.fetchone()
        if not row:
            raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title="Task line not found")
        task_id = str(row[0])
        cur.execute("SELECT status FROM field.task WHERE id = %s::uuid", (task_id,))
        if (cur.fetchone() or ["completed"])[0] in ("completed", "cancelled"):
            raise FieldError(status=410, code="FIELD-CAP-410-TASK-CLOSED", title="Task closed")
        if req.voice_event_id:
            cur.execute("SELECT confidence FROM field.voice_event WHERE id = %s::uuid AND is_accepted",
                        (req.voice_event_id,))
            v = cur.fetchone()
            confidence = float(v[0]) if v else 0.0
    out = record_count(
        task_id, req.task_line_id,
        CountIn(qty=req.value, uom=req.unit, source=req.source, confidence=confidence,
                voice_event_id=req.voice_event_id, capture_id=req.capture_id),
        principal,
    )
    return {"id": out["line_id"], **out}


class ConfirmMethod(BaseModel):
    """How the operator confirmed (contract §4): ``touch`` = saw the review screen and pressed
    "Yes, post it"; ``voice`` = an accepted ``post`` turn followed by ``confirm`` within 10 s."""

    method: Literal["touch", "voice"]
    post_voice_event_id: str | None = None
    confirm_voice_event_id: str | None = None


class PostRequest(BaseModel):
    operation: Literal["post"] = "post"
    lines: list[str] = Field(min_length=1)
    staged_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: ConfirmMethod | None = None
    # Pre-M2 shape (top-level voice turn ids): still accepted, means method "voice".
    post_voice_event_id: str | None = None
    confirm_voice_event_id: str | None = None
    # M5 (receipts): the vision look this receipt was checked with, and flagged units per line id (to 101Q).
    look_id: str | None = None
    flag_qty: dict[str, Decimal] = Field(default_factory=dict)


def _voice_ids(req: PostRequest) -> tuple[str, str] | None:
    """The voice turn pair to check, or None for a touch confirmation. 422 when neither is valid."""
    if req.confirm is not None and req.confirm.method == "touch":
        return None
    post = (req.confirm.post_voice_event_id if req.confirm else None) or req.post_voice_event_id
    conf = (req.confirm.confirm_voice_event_id if req.confirm else None) or req.confirm_voice_event_id
    if not post or not conf:
        raise ERR_NO_CONFIRM
    return post, conf


def _check_voice_turns(cur: Any, principal: Principal, task_id: str, post_id: str, conf_id: str) -> None:
    cur.execute(
        "SELECT id, device_id, task_id, intent, is_accepted, confidence, client_timestamp"
        " FROM field.voice_event WHERE id = ANY(%s::uuid[])",
        ([post_id, conf_id],),
    )
    evs = {str(r[0]): r for r in cur.fetchall()}
    post, conf = evs.get(post_id), evs.get(conf_id)
    if not post or not conf:
        raise ERR_NO_CONFIRM
    if not (post[3] == "post" and conf[3] == "confirm" and post[4] and conf[4]):
        raise ERR_NO_CONFIRM
    if post[1] != conf[1] or str(post[2]) != task_id or str(conf[2]) != task_id:
        raise ERR_NO_CONFIRM
    if principal.device_id and str(post[1]) != principal.device_id:
        raise ERR_NO_CONFIRM
    delta = (conf[6] - post[6]).total_seconds()
    if not 0 <= delta <= CONFIRM_TIMEOUT_S:
        raise ERR_NO_CONFIRM
    cur.execute("SELECT 1 FROM field.erp_document WHERE payload->>'post_voice_event_id' = %s", (post_id,))
    if cur.fetchone():
        raise FieldError(status=409, code="FIELD-POST-409-ALREADY-REQUESTED", title="Already requested")


@router.post("/tasks/{task_id}/post-requests", status_code=202)
async def submit_post_request(
    task_id: str,
    req: PostRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.post.request")),
) -> dict[str, Any]:
    """Finish a job (contract §4): two-step confirmation (touch or voice) + staged_hash, then per type.

    receive / pick: staged ERP posting (API3.06); 202 {status: queued}.
    putaway / audit: 202 {status: completed}; count: {status: queued | awaiting_approval};
    swap: {status: queued}. The ERP result arrives as a live event.
    """
    voice = _voice_ids(req)
    method = "voice" if voice else "touch"
    finished: dict[str, Any] | None = None
    with principal_tx(principal) as cur:
        cur.execute("SELECT id, site_id, type, status, ref_doc_no FROM field.task WHERE id = %s::uuid FOR UPDATE",
                    (task_id,))
        trow = cur.fetchone()
        if not trow:
            raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title="Task not found")
        task = {"id": str(trow[0]), "site_id": str(trow[1]), "type": trow[2], "status": trow[3], "ref_doc_no": trow[4]}
        if task["status"] in ("completed", "cancelled", "posting", "awaiting_approval"):
            raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="This job is already finished",
                             detail=f"task status is {task['status']}")
        if voice:
            _check_voice_turns(cur, principal, task_id, *voice)
        qty_col = hash_quantity_column(task["type"])
        cur.execute(
            sql.SQL("SELECT l.id, l.{} FROM field.task_line l WHERE l.task_id = %s::uuid AND l.id = ANY(%s::uuid[])")
            .format(sql.Identifier(qty_col)),
            (task_id, req.lines),
        )
        rows = [(str(r[0]), Decimal(r[1])) for r in cur.fetchall()]
        if len(rows) != len(set(req.lines)) or staged_hash(rows) != req.staged_hash:
            raise FieldError(status=422, code="FIELD-POST-422-NO-CONFIRM", title="Staged lines changed",
                             detail="staged_hash does not match the server's lines; re-read and confirm again")
        flags = _check_look(cur, task, req) if (req.look_id is not None or req.flag_qty) else None
        if task["type"] == "pick":
            _require_pick_scans(cur, task_id, req.lines)
        if task["type"] == "putaway":
            finished = finish_putaway(cur, principal, task, req.lines)
        elif task["type"] == "count":
            finished = finish_count(cur, principal, task, req.lines, idempotency_key)
        elif task["type"] == "audit":
            finished = finish_audit(cur, principal, task, req.lines)
        elif task["type"] == "swap":
            finished = finish_swap(cur, principal, task, req.lines, idempotency_key)
    if finished is not None:
        return {"task_id": task_id, "type": task["type"], "confirm_method": method, "posting_request_id": None,
                **finished}
    extra: dict[str, Any] = {"confirm_method": method}
    if voice:
        extra.update({"post_voice_event_id": voice[0], "confirm_voice_event_id": voice[1]})
    if flags is not None:
        extra.update({"look_id": req.look_id, "flag_qty": {k: f"{v:.3f}" for k, v in flags.items() if v > 0}})
    try:
        out = confirm_task(task_id, ConfirmIn(lines=req.lines), idempotency_key, principal, extra_payload=extra,
                           flags=flags, look_id=req.look_id)
    except psycopg.errors.UniqueViolation as e:  # concurrent request for the same voice turn
        raise FieldError(status=409, code="FIELD-POST-409-ALREADY-REQUESTED", title="Already requested") from e
    return {"task_id": task_id, "type": task["type"], "confirm_method": method,
            "posting_request_id": out["erp_document_id"], "status": "queued", "event": "posting.requested",
            "queue_key": out["queue_key"]}


def _require_pick_scans(cur: Any, task_id: str, line_ids: list[str]) -> None:
    """FR3.018: a pick line with a picked quantity needs its source bin and product scanned first."""
    cur.execute(
        "SELECT line_no FROM field.task_line WHERE task_id = %s::uuid AND id = ANY(%s::uuid[]) AND picked_qty > 0"
        " AND (confirmed_bin IS NULL OR confirmed_product IS NULL) ORDER BY line_no",
        (task_id, line_ids),
    )
    missing = [r[0] for r in cur.fetchall()]
    if missing:
        raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="Scan the bin and the product first",
                         detail=f"lines {missing} have no bin and product scan")

def _check_look(cur: Any, task: dict[str, Any], req: PostRequest) -> dict[str, Decimal]:
    """M5: the look and the flagged quantities of a receipt post; returns the flag per posted line (0 if none)."""
    if req.look_id is None:
        raise FieldError(status=422, code="FIELD-POST-422-LOOK-REQUIRED", title="Flagged units need the look",
                         detail="flag_qty is sent with the look_id of the look that found them")
    if task["type"] != "receive":
        raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="A look is posted with receipts only",
                         detail=f"this is a {task['type']} job")
    unknown = sorted(set(req.flag_qty) - set(req.lines))
    if unknown:
        raise FieldError(status=422, code="FIELD-POST-422-FLAG-LINE", title="A flagged line is not being posted",
                         detail=f"flag_qty names lines not in lines: {unknown}")
    if any(v < 0 for v in req.flag_qty.values()):
        raise FieldError(status=422, code="FIELD-POST-422-FLAG-QTY", title="A flagged quantity cannot be negative")
    cur.execute(
        "SELECT l.task_id, d.status FROM field.vision_look l LEFT JOIN field.erp_document d ON d.id = l.erp_document_id"
        " WHERE l.id::text = %s", (req.look_id,))
    look = cur.fetchone()
    if not look:
        raise FieldError(status=404, code="FIELD-VIS-404-LOOK", title="Look not found or out of scope")
    if str(look[0]) != task["id"]:
        raise FieldError(status=422, code="FIELD-VIS-422-TASK", title="The look belongs to another task")
    if look[1] is not None and look[1] != "failed":
        raise FieldError(status=409, code="FIELD-VIS-409-POSTED", title="This look is already posted",
                         detail=f"its document is {look[1]}")
    cur.execute("SELECT id, counted_qty, damaged_qty FROM field.task_line WHERE id = ANY(%s::uuid[])", (req.lines,))
    room = {str(r[0]): Decimal(r[1] or 0) - Decimal(r[2] or 0) for r in cur.fetchall()}
    flags = {lid: Decimal(req.flag_qty.get(lid, 0)) for lid in req.lines}
    over = [lid for lid, q in flags.items() if q > room.get(lid, Decimal(0))]
    if over:
        raise FieldError(status=422, code="FIELD-POST-422-FLAG-QTY", title="More flagged than counted",
                         detail=f"lines {over}: flag_qty is more than the counted (less damaged) quantity")
    return flags
