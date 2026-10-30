"""Voice events, count records and the voice confirm gate (API2.12-2.14 / FR2.038, FR2.050, FR2.055).

BRIEF §1.3: the system never posts on speech alone. A post request is accepted only when an accepted
``post`` voice event is followed, on the same device and task, by an accepted ``confirm`` voice event
within FIELD_CONFIRM_TIMEOUT_S (10 s), and the client's ``staged_hash`` equals the server's hash of
exactly the lines being posted (so the operator confirmed what is posted). The posting itself is the
same atomic staging as API3.06.

staged_hash = sha256("|".join(sorted(f"{line_id}:{qty:.3f}"))) over the lines in the request, where
qty is the line's counted (receive) or picked (pick) quantity on the server.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
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


class PostRequest(BaseModel):
    operation: Literal["post"] = "post"
    lines: list[str] = Field(min_length=1)
    staged_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    post_voice_event_id: str
    confirm_voice_event_id: str


@router.post("/tasks/{task_id}/post-requests", status_code=202)
async def submit_post_request(
    task_id: str,
    req: PostRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.post.request")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(
            "SELECT id, device_id, task_id, intent, is_accepted, confidence, client_timestamp"
            " FROM field.voice_event WHERE id = ANY(%s::uuid[])",
            ([req.post_voice_event_id, req.confirm_voice_event_id],),
        )
        evs = {str(r[0]): r for r in cur.fetchall()}
        post, conf = evs.get(req.post_voice_event_id), evs.get(req.confirm_voice_event_id)
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
        cur.execute("SELECT 1 FROM field.erp_document WHERE payload->>'post_voice_event_id' = %s",
                    (req.post_voice_event_id,))
        if cur.fetchone():
            raise FieldError(status=409, code="FIELD-POST-409-ALREADY-REQUESTED", title="Already requested")
        cur.execute(
            """
            SELECT l.id, CASE WHEN t.type = 'pick' THEN l.picked_qty ELSE l.counted_qty END
              FROM field.task_line l JOIN field.task t ON t.id = l.task_id
             WHERE l.task_id = %s::uuid AND l.id = ANY(%s::uuid[])
            """,
            (task_id, req.lines),
        )
        rows = [(str(r[0]), Decimal(r[1])) for r in cur.fetchall()]
        if len(rows) != len(set(req.lines)) or staged_hash(rows) != req.staged_hash:
            raise FieldError(status=422, code="FIELD-POST-422-NO-CONFIRM", title="Staged lines changed",
                             detail="staged_hash does not match the server's lines; re-read and confirm again")
    try:
        out = confirm_task(task_id, ConfirmIn(lines=req.lines), idempotency_key, principal,
                           extra_payload={"post_voice_event_id": req.post_voice_event_id,
                                          "confirm_voice_event_id": req.confirm_voice_event_id})
    except psycopg.errors.UniqueViolation as e:  # concurrent request for the same voice turn
        raise FieldError(status=409, code="FIELD-POST-409-ALREADY-REQUESTED", title="Already requested") from e
    return {"posting_request_id": out["erp_document_id"], "status": "queued", "event": "posting.requested",
            "queue_key": out["queue_key"]}
