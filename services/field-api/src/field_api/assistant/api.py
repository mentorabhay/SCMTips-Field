"""Field Assistant HTTP API (M3 contract §4).

POST /v1/assistant/turns                                   field.assistant.use (operator, technician, supervisor)
GET  /v1/assistant/sessions?site_id=&limit=&cursor=        field.assistant.review (supervisor)
GET  /v1/assistant/sessions/{id}                           field.assistant.review
GET  /v1/assistant/sessions/{id}/export.csv                field.assistant.review
GET  /v1/assistant/sessions/{id}/turns/{turn_id}/photo     field.assistant.review (the console's photo view)

POST needs an Idempotency-Key like every write (the middleware enforces it; a retry replays the first answer).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from field_api.assistant import records
from field_api.assistant.model import ModelRouter, get_router
from field_api.assistant.photos import AssistantPhotoStore
from field_api.assistant.ports import AssistantPorts, get_ports
from field_api.assistant.service import ERR_SESSION_NOT_FOUND, TurnIn, run_turn
from field_api.auth.jwt import Principal
from field_api.deps import require_permission, require_site_scope
from field_api.errors import FieldError

router = APIRouter(tags=["Field Assistant (M3)"])

Event = Literal["session_start", "utterance", "scan", "unknown_code", "photo", "step_done", "pause", "resume",
                "session_end"]
MAX_PHOTO_B64 = 1_400_000  # 1 MB of JPEG in base64, plus slack; the decoded size is checked exactly

ERR_MISSING_KEY = FieldError(code="FIELD-IDEM-400-MISSING-KEY", status=400, title="Idempotency-Key header required")
ERR_ID = FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Invalid id")


class ClientState(BaseModel):
    task_id: uuid.UUID | None = None
    line_id: uuid.UUID | None = None
    step: str | None = Field(default=None, max_length=64)


class TurnRequest(BaseModel):
    session_id: uuid.UUID | None = None
    site_id: uuid.UUID
    event: Event
    text: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, max_length=128)
    photo_jpeg_b64: str | None = Field(default=None, max_length=MAX_PHOTO_B64)
    client_state: ClientState | None = None


class Card(BaseModel):
    title: str
    body: str


class TurnResponse(BaseModel):
    session_id: str
    say: str
    card: Card
    actions: list[dict[str, Any]]
    ai: Literal["model", "rules"]
    cost_usd: float


@router.post("/v1/assistant/turns", response_model=TurnResponse)
def post_turn(
    body: TurnRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.assistant.use")),
    ports: AssistantPorts = Depends(get_ports),
    model_router: ModelRouter = Depends(get_router),
) -> dict[str, Any]:
    if not idempotency_key:  # the idempotency middleware already refuses this; kept so the route never runs without
        raise ERR_MISSING_KEY
    cs = body.client_state or ClientState()
    t = TurnIn(
        session_id=str(body.session_id) if body.session_id else None, site_id=str(body.site_id), event=body.event,
        text=(body.text or "").strip() or None, code=(body.code or "").strip() or None,
        photo_jpeg_b64=body.photo_jpeg_b64 or None, task_id=str(cs.task_id) if cs.task_id else None,
        line_id=str(cs.line_id) if cs.line_id else None, step=cs.step,
    )
    return run_turn(principal, t, idempotency_key=idempotency_key, ports=ports, router=model_router,
                    request_id=getattr(request.state, "request_id", None))


def _uuid(v: str) -> str:
    try:
        return str(uuid.UUID(v))
    except ValueError:
        raise ERR_ID


@router.get("/v1/assistant/sessions")
def list_sessions(
    site_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="next_cursor of the previous page"),
    principal: Principal = Depends(require_permission("field.assistant.review")),
) -> dict[str, Any]:
    if site_id is not None:
        require_site_scope(str(site_id), principal)
    return records.list_sessions(principal, str(site_id) if site_id else None, limit, cursor)


def _detail(principal: Principal, session_id: str) -> dict[str, Any]:
    d = records.session_detail(principal, _uuid(session_id))
    if d is None:
        raise ERR_SESSION_NOT_FOUND
    return d


@router.get("/v1/assistant/sessions/{session_id}")
def get_session(session_id: str,
                principal: Principal = Depends(require_permission("field.assistant.review"))) -> dict[str, Any]:
    return _detail(principal, session_id)


@router.get("/v1/assistant/sessions/{session_id}/export.csv", response_class=Response)
def export_session(session_id: str,
                   principal: Principal = Depends(require_permission("field.assistant.review"))) -> Response:
    d = _detail(principal, session_id)
    return Response(content=records.turns_csv(d), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="assistant-session-{d["id"]}.csv"'})


@router.get("/v1/assistant/sessions/{session_id}/turns/{turn_id}/photo", response_class=Response)
def get_turn_photo(session_id: str, turn_id: str,
                   principal: Principal = Depends(require_permission("field.assistant.review"))) -> Response:
    ref = records.turn_photo_ref(principal, _uuid(session_id), _uuid(turn_id))
    store = AssistantPhotoStore()
    if ref is None or not store.exists(ref):
        raise FieldError(status=404, code="FIELD-AST-404-PHOTO", title="No photo for this turn")
    return Response(content=store.get(ref), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
