"""Sandbox routes (M3 contract section 3). Every one is refused on a production site: 403 FIELD-SBX-403-PRODUCTION.

POST /v1/sandbox/receipts {site_id}                     -> 201 {task_id, ref_doc_no}
POST /v1/sandbox/counts {site_id, bin, simulated?}      -> 201 {task_id, ref_doc_no}   (an empty count of one bin)
POST /v1/sandbox/tasks/{task_id}/items {code, description, qty?}  (Idempotency-Key)
                                                        -> 201 {line_id, material, created_material}

Permission field.task.execute (operators and technicians; field.admin by its wildcard).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.deps import require_permission
from field_api.sandbox.service import (
    SandboxItemResult,
    SandboxTaskResult,
    add_item,
    create_count,
    create_receipt,
)

router = APIRouter(prefix="/v1/sandbox", tags=["Sandbox (M3)"])


class ReceiptIn(BaseModel):
    site_id: str


class CountIn(BaseModel):
    site_id: str
    bin: str = Field(min_length=1, max_length=64)
    simulated: bool = Field(default=False, description="set by `stack home --simulate-differences`: its ERP documents"
                                                       " are marked simulated")


class ItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=128, description="the scanned barcode (or a material number)")
    description: str = Field(default="", max_length=120, description="what the operator says it is")
    qty: Decimal | None = Field(default=None, ge=0, description="receipt: delivery quantity; count: the count")


@router.post("/receipts", status_code=201)
def post_receipt(
    body: ReceiptIn,
    principal: Principal = Depends(require_permission("field.task.execute")),
) -> SandboxTaskResult:
    return create_receipt(principal, body.site_id)


@router.post("/counts", status_code=201)
def post_count(
    body: CountIn,
    principal: Principal = Depends(require_permission("field.task.execute")),
) -> SandboxTaskResult:
    return create_count(principal, body.site_id, body.bin, body.simulated)


@router.post("/tasks/{task_id}/items", status_code=201)
def post_item(
    task_id: str,
    body: ItemIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.task.execute")),
) -> SandboxItemResult:
    return add_item(principal, task_id, body.code, body.description, body.qty, idempotency_key)
