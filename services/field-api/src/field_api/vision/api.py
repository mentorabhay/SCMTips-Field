"""Vision look routes (docs/design/M5_CONTRACT.md §2; stream V).

POST /v1/vision/looks {task_id, line_id?, capture_id, object?, case}   (field.task.execute; Idempotency-Key)
    -> 200 the look (always 200 once the task and capture are found: model failures degrade to source rules)
GET  /v1/vision/looks/{look_id}                                       (field.task.read) -> 200 the same body

Besides the contract's keys the body carries task_id, line_id, capture_id, case, object, created_at and
erp_document_id (the receipt document the look was posted with, null until then).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header

from field_api.auth.jwt import Principal
from field_api.deps import require_permission
from field_api.vision.ports import VisionPorts
from field_api.vision.service import LookIn, create_look, get_look, get_vision_ports

router = APIRouter(prefix="/v1/vision", tags=["Vision (M5)"])


@router.post("/looks", status_code=200)
def post_look(
    body: LookIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.task.execute")),
    ports: VisionPorts = Depends(get_vision_ports),
) -> dict[str, Any]:
    return create_look(principal, body, idempotency_key, ports)


@router.get("/looks/{look_id}")
def read_look(
    look_id: str,
    principal: Principal = Depends(require_permission("field.task.read")),
) -> dict[str, Any]:
    return get_look(principal, look_id)
