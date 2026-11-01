"""Supplier claims HTTP API (M5 contract section 3).

POST /v1/claims {look_id}                          field.claim.create (operator, supervisor)
     -> 201 a new claim, 200 the existing claim of this look; ETag
GET  /v1/claims?status=draft|pending|approved|rejected&limit=   field.claim.read
GET  /v1/claims/{id}                               field.claim.read; ETag
POST /v1/claims/{id}/decision {decision, reason?}  field.claim.decide (supervisor); If-Match
     -> {status: "pending_confirm", say, confirm_by}; ETag
POST /v1/claims/{id}/confirm {words?}              field.claim.decide, the same person, within 10 s; If-Match
     -> {status: "approved" | "rejected", say}; ETag
Every POST needs an Idempotency-Key (middleware). Sending to the supplier is SIMULATED (a claim.sent outbox record).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field

from field_api.assistant.model import ModelRouter, get_router
from field_api.auth.jwt import Principal
from field_api.claims import service
from field_api.claims.looks import LookPort, get_look_port
from field_api.deps import require_permission

router = APIRouter(tags=["Supplier claims (M5)"])

Reason = Literal["damaged", "short", "pack_size", "expired", "near_expiry"]


class ClaimIn(BaseModel):
    look_id: str = Field(min_length=36, max_length=36, description="the look (POST /v1/vision/looks)")


class ClaimLineOut(BaseModel):
    reason: Reason
    units: int
    pieces: int


class ClaimOut(BaseModel):
    claim_id: str
    status: Literal["draft", "pending_confirm", "approved", "rejected"]
    lines: list[ClaimLineOut]
    text: str
    source: Literal["model", "template"]
    reasons: list[str]
    evidence_url: str = Field(description="the JSON evidence pack of the posted receipt; empty until it is posted")
    look_id: str
    task_id: str | None
    site_id: str
    created_by: str
    created_at: str | None
    decision: Literal["approve", "reject"] | None
    decision_reason: str | None
    decided_by: str | None
    decided_at: str | None
    confirm_by: str | None
    confirmed_by: str | None
    confirmed_at: str | None
    confirm_words: str | None
    sent: bool = Field(description="approved and recorded as sent (SIMULATED: an outbox record, no e-mail)")
    version: int


class ClaimList(BaseModel):
    items: list[ClaimOut]
    count: int


class ClaimDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class ClaimDecisionOut(BaseModel):
    status: Literal["pending_confirm"]
    say: str
    confirm_by: str | None


class ClaimConfirmIn(BaseModel):
    words: str | None = Field(default=None, max_length=500, description="the words heard, e.g. \"confirm\"")


class ClaimConfirmOut(BaseModel):
    status: Literal["approved", "rejected"]
    say: str


@router.post("/v1/claims", response_model=ClaimOut, status_code=201)
def post_claim(
    body: ClaimIn,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission("field.claim.create")),
    looks: LookPort = Depends(get_look_port),
    model_router: ModelRouter = Depends(get_router),
) -> dict[str, Any]:
    out, created = service.create_claim(principal, body.look_id, looks=looks, router=model_router,
                                        request_id=getattr(request.state, "request_id", None))
    if not created:
        response.status_code = 200
    response.headers["ETag"] = service.etag(out)
    response.headers["Location"] = f"/v1/claims/{out['claim_id']}"
    return out


@router.get("/v1/claims", response_model=ClaimList)
def get_claims(
    status: Literal["draft", "pending", "pending_confirm", "approved", "rejected"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission("field.claim.read")),
) -> dict[str, Any]:
    return service.list_claims(principal, status, limit)


@router.get("/v1/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: str,
    response: Response,
    principal: Principal = Depends(require_permission("field.claim.read")),
) -> dict[str, Any]:
    out = service.get_claim(principal, claim_id)
    response.headers["ETag"] = service.etag(out)
    return out


@router.post("/v1/claims/{claim_id}/decision", response_model=ClaimDecisionOut)
def post_decision(
    claim_id: str,
    body: ClaimDecisionIn,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
    principal: Principal = Depends(require_permission("field.claim.decide")),
) -> dict[str, Any]:
    answer, out = service.decide(principal, claim_id, body.decision, body.reason, if_match)
    response.headers["ETag"] = service.etag(out)
    return answer


@router.post("/v1/claims/{claim_id}/confirm", response_model=ClaimConfirmOut)
def post_confirm(
    claim_id: str,
    response: Response,
    body: ClaimConfirmIn | None = None,
    if_match: str | None = Header(None, alias="If-Match"),
    principal: Principal = Depends(require_permission("field.claim.decide")),
) -> dict[str, Any]:
    answer, out = service.confirm(principal, claim_id, if_match, body.words if body else None)
    response.headers["ETag"] = service.etag(out)
    return answer
