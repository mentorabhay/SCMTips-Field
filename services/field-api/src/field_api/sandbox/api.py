"""Sandbox routes (M3 contract section 3). Every one is refused on a production site: 403 FIELD-SBX-403-PRODUCTION.

POST /v1/sandbox/receipts {site_id, case?}              -> 201 {task_id, ref_doc_no}   (case: M5 C1/C2 starter)
POST /v1/sandbox/counts {site_id, bin, simulated?}      -> 201 {task_id, ref_doc_no}   (an empty count of one bin)
POST /v1/sandbox/tasks/{task_id}/items {code, description, qty?}  (Idempotency-Key)
                                                        -> 201 {line_id, material, created_material}
POST /v1/sandbox/cases {site_id, case: grocery|pharmacy, units?, pieces_per_unit?, window_days?}   (M5 §1)
                        -> 201 {task_id, ref_doc_no, line_id, case, object, material, expected_units,
                                expected_pieces_per_unit, expiry_window_days}   (field_api.vision.cases)

Permission field.task.execute (operators and technicians; field.admin by its wildcard).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

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
from field_api.vision.cases import CaseResult, create_case

router = APIRouter(prefix="/v1/sandbox", tags=["Sandbox (M3)"])


class ReceiptIn(BaseModel):
    site_id: str
    case: Literal["grocery", "pharmacy"] | None = Field(
        default=None, description="M5: a test-case receipt (C1 grocery / C2 pharmacy) with its default line; the same"
                                  " as POST /v1/sandbox/cases with the defaults")


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
    if body.case is not None:  # M5 Today starter (the app): the case receipt, answered in the M3 shape
        made = create_case(principal, body.site_id, body.case)
        return {"task_id": made["task_id"], "ref_doc_no": made["ref_doc_no"]}
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


class CaseIn(BaseModel):
    site_id: str
    case: Literal["grocery", "pharmacy"]
    units: int | None = Field(default=None, ge=1, le=999, description="expected units (20 packs / 10 boxes)")
    pieces_per_unit: int | None = Field(default=None, ge=1, le=10_000, description="grocery: pieces in each pack")
    window_days: int | None = Field(default=None, ge=0, le=3650, description="pharmacy: the expiring-soon window")


@router.post("/cases", status_code=201)
def post_case(
    body: CaseIn,
    principal: Principal = Depends(require_permission("field.task.execute")),
) -> CaseResult:
    """M5 test case C1 (grocery delivery) or C2 (pharmacy receipt) on a sandbox site (contract §1)."""
    return create_case(principal, body.site_id, body.case, body.units, body.pieces_per_unit, body.window_days)
