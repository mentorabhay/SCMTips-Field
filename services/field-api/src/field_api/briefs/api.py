"""Spoken decision briefs HTTP API (M4 contract §4, F3).

POST /v1/briefs/spoken {decision_id, template_text}         field.assistant.use
  headers: Authorization (field token), Idempotency-Key (every POST), X-Core-Token (the app's core wearable token,
  forwarded to the core's check, never stored or logged), X-Device-Id
  -> 200 {text, source: "model" | "template", reasons: [...]}
The answer is always speakable: whatever fails, ``text`` is the template and ``reasons`` say why.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from field_api.assistant.model import ModelRouter, get_router
from field_api.auth.jwt import Principal
from field_api.briefs.core import CoreBriefCheck, get_core_check
from field_api.briefs.service import BriefIn, spoken_brief
from field_api.deps import require_permission

router = APIRouter(tags=["Spoken briefs (M4)"])


class SpokenBriefIn(BaseModel):
    decision_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    template_text: str = Field(min_length=1, max_length=4000, description="the core's template brief")


class SpokenBriefOut(BaseModel):
    text: str
    source: Literal["model", "template"]
    reasons: list[str]


@router.post("/v1/briefs/spoken", response_model=SpokenBriefOut)
def post_spoken_brief(
    body: SpokenBriefIn,
    request: Request,
    x_core_token: str | None = Header(None, alias="X-Core-Token", description="the app's core wearable token"),
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
    principal: Principal = Depends(require_permission("field.assistant.use")),
    model_router: ModelRouter = Depends(get_router),
    core: CoreBriefCheck = Depends(get_core_check),
) -> dict[str, Any]:
    b = BriefIn(decision_id=body.decision_id, template_text=body.template_text, core_token=x_core_token,
                device_id=x_device_id)
    return spoken_brief(principal, b, router=model_router, core=core,
                        request_id=getattr(request.state, "request_id", None))
