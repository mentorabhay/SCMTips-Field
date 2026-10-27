"""Voice Events, Count Records, and Confirmed Post Request Endpoints (Task T2.052 / FR2.038, FR2.050, FR2.055, TC2.133, TC2.162)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_principal
from field_api.errors import FieldError
from field_api.routes.live import emit_device_tick

router = APIRouter(prefix="/v1", tags=["Voice and Posting"])

# In-memory stores
VOICE_EVENTS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
COUNT_RECORDS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
POSTING_REQUESTS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()

ERR_CONFIRM_GATE_VIOLATION = FieldError(
    status=400,
    code="FIELD-POST-400-CONFIRM-REQUIRED",
    title="Confirmation Gate Violation",
    detail="Posting request rejected: requires an accepted 'confirm' voice event following 'post' within 10 seconds.",
)


class VoiceEventRequest(BaseModel):
    device_id: str
    task_id: str | None = None
    capture_id: str | None = None
    transcript: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    intent: str
    is_accepted: bool = True
    locale: str = "en-US"
    client_timestamp: str | None = None


class VoiceEventResponse(BaseModel):
    id: str
    tenant_id: str
    device_id: str
    intent: str
    is_accepted: bool
    created_at: str


class CountRecordRequest(BaseModel):
    task_id: str
    task_line_id: str | None = None
    capture_id: str | None = None
    voice_event_id: str | None = None
    quantity: float
    unit: str = "EA"
    is_reversal: bool = False


class CountRecordResponse(BaseModel):
    id: str
    tenant_id: str
    task_id: str
    task_line_id: str | None = None
    quantity: float
    unit: str
    is_reversal: bool
    created_at: str


class PostRequestIn(BaseModel):
    device_id: str
    staged_payload: dict[str, Any]
    post_voice_event_id: str
    confirm_voice_event_id: str
    is_reversal: bool = False


class PostRequestResponse(BaseModel):
    id: str
    tenant_id: str
    task_id: str
    status: str
    is_reversal: bool
    created_at: str


@router.post("/voice-events", response_model=VoiceEventResponse, status_code=201)
async def record_voice_event(
    req: VoiceEventRequest,
    principal: Principal = Depends(require_principal),
) -> VoiceEventResponse:
    """Record recognized voice utterance without persisting audio (T2.052 / FR2.038)."""
    event_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()

    record = {
        "id": event_id,
        "tenant_id": principal.tenant_id,
        "device_id": req.device_id,
        "task_id": req.task_id,
        "capture_id": req.capture_id,
        "transcript": req.transcript,
        "confidence": req.confidence,
        "intent": req.intent,
        "is_accepted": req.is_accepted,
        "locale": req.locale,
        "client_timestamp": req.client_timestamp or now_iso,
        "created_at": now_iso,
    }
    VOICE_EVENTS_STORE.insert(principal.tenant_id, event_id, record)

    return VoiceEventResponse(
        id=event_id,
        tenant_id=principal.tenant_id,
        device_id=req.device_id,
        intent=req.intent,
        is_accepted=req.is_accepted,
        created_at=now_iso,
    )


@router.post("/count-records", response_model=CountRecordResponse, status_code=201)
async def record_count(
    req: CountRecordRequest,
    principal: Principal = Depends(require_principal),
) -> CountRecordResponse:
    """Record counted or read quantity linked to task line / capture (T2.052 / FR2.050, TC2.162)."""
    count_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()

    record = {
        "id": count_id,
        "tenant_id": principal.tenant_id,
        "task_id": req.task_id,
        "task_line_id": req.task_line_id,
        "capture_id": req.capture_id,
        "voice_event_id": req.voice_event_id,
        "quantity": req.quantity,
        "unit": req.unit,
        "is_reversal": req.is_reversal,
        "created_at": now_iso,
    }
    COUNT_RECORDS_STORE.insert(principal.tenant_id, count_id, record)

    return CountRecordResponse(
        id=count_id,
        tenant_id=principal.tenant_id,
        task_id=req.task_id,
        task_line_id=req.task_line_id,
        quantity=req.quantity,
        unit=req.unit,
        is_reversal=req.is_reversal,
        created_at=now_iso,
    )


@router.post("/tasks/{task_id}/post-requests", response_model=PostRequestResponse, status_code=202)
async def submit_post_request(
    task_id: str,
    req: PostRequestIn,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_principal),
) -> PostRequestResponse:
    """Submit confirmed posting request to ERP, strictly validating confirm turn (T2.052 / FR2.055, TC2.133, PR2.11)."""
    post_ev = VOICE_EVENTS_STORE.get(principal.tenant_id, req.post_voice_event_id)
    confirm_ev = VOICE_EVENTS_STORE.get(principal.tenant_id, req.confirm_voice_event_id)

    # Validate confirm turn (10 second window)
    if not post_ev or not confirm_ev:
        raise ERR_CONFIRM_GATE_VIOLATION

    if not post_ev.get("is_accepted") or not confirm_ev.get("is_accepted"):
        raise ERR_CONFIRM_GATE_VIOLATION

    if post_ev.get("intent") != "post" or confirm_ev.get("intent") != "confirm":
        raise ERR_CONFIRM_GATE_VIOLATION

    t_post = datetime.fromisoformat(post_ev["created_at"])
    t_confirm = datetime.fromisoformat(confirm_ev["created_at"])
    delta_sec = (t_confirm - t_post).total_seconds()

    if delta_sec < 0 or delta_sec > 10.0:
        raise ERR_CONFIRM_GATE_VIOLATION

    post_req_id = idempotency_key or uuid7_str()
    now_iso = datetime.now(UTC).isoformat()

    record = {
        "id": post_req_id,
        "tenant_id": principal.tenant_id,
        "task_id": task_id,
        "device_id": req.device_id,
        "staged_payload": req.staged_payload,
        "post_voice_event_id": req.post_voice_event_id,
        "confirm_voice_event_id": req.confirm_voice_event_id,
        "status": "pending_erp",
        "is_reversal": req.is_reversal,
        "created_at": now_iso,
    }
    POSTING_REQUESTS_STORE.insert(principal.tenant_id, post_req_id, record)

    # Push Live Channel tick
    emit_device_tick(
        tenant_id=principal.tenant_id,
        device_id=req.device_id,
        tick_type="posted",
        task_id=task_id,
        detail=f"Posting requested for task {task_id} (reversal={req.is_reversal})",
    )

    return PostRequestResponse(
        id=post_req_id,
        tenant_id=principal.tenant_id,
        task_id=task_id,
        status="pending_erp",
        is_reversal=req.is_reversal,
        created_at=now_iso,
    )
