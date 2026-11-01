"""The two real-world test cases of M5 (docs/design/M5_CONTRACT.md §1), as sandbox receipts.

``create_case`` makes, on a sandbox site, an open inbound delivery in the ERP with one item and its receive task
(``sandbox.service.create_receipt`` + ``add_item``: the item becomes a sandbox material on first use), and records
what the look checks beyond the quantity (field.vision_case_line):

- C1 ``grocery``: ``units`` packs (default 20), ``pieces_per_unit`` pieces in each (default 12), counted as "pack";
- C2 ``pharmacy``: ``units`` boxes (default 10), expiry window ``window_days`` (default VISION_EXPIRY_WINDOW_DAYS,
  90), counted as "box".

The material is named by a generic description ("biscuit pack", "tablet box"), never a brand (contract §6). The
delivery is in storage location FIELD_CASE_SLOC (default 101A) when the site lists it; flagged units post to
FIELD_QUALITY_SLOC (default 101Q). A production site refuses (403 FIELD-SBX-403-PRODUCTION).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypedDict

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.errors import FieldError
from field_api.sandbox.service import add_item, create_receipt
from field_api.vision import settings

CaseName = Literal["grocery", "pharmacy"]


@dataclass(frozen=True)
class CaseSpec:
    object_noun: str
    description: str
    code: str
    units: int
    pieces_per_unit: int | None


CASES: dict[str, CaseSpec] = {
    "grocery": CaseSpec("pack", "biscuit pack", "M5-C1-PACK", 20, 12),
    "pharmacy": CaseSpec("box", "tablet box", "M5-C2-BOX", 10, None),
}


class CaseResult(TypedDict):
    task_id: str
    ref_doc_no: str
    line_id: str
    case: str
    object: str
    material: str
    expected_units: int
    expected_pieces_per_unit: int | None
    expiry_window_days: int | None


def case_sloc() -> str:
    return os.getenv("FIELD_CASE_SLOC", "").strip() or "101A"


def create_case(principal: Principal, site_id: str, case: str, units: int | None = None,
                pieces_per_unit: int | None = None, window_days: int | None = None) -> CaseResult:
    spec = CASES.get(case)
    if spec is None:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="The case is grocery or pharmacy")
    n = spec.units if units is None else units
    if not 1 <= n <= 999:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Units must be between 1 and 999")
    ppu = (spec.pieces_per_unit if pieces_per_unit is None else pieces_per_unit) if case == "grocery" else None
    if ppu is not None and not 1 <= ppu <= 10_000:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Pieces per unit must be 1 to 10000")
    window = (settings.expiry_window_days() if window_days is None else window_days) if case == "pharmacy" else None
    if window is not None and not 0 <= window <= 3650:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="The window must be 0 to 3650 days")
    receipt = create_receipt(principal, site_id, sloc=case_sloc())
    item = add_item(principal, receipt["task_id"], spec.code, spec.description, Decimal(n),
                    f"m5-case:{receipt['task_id']}")
    with principal_tx(principal) as cur:
        cur.execute(
            """
            INSERT INTO field.vision_case_line (tenant_id, site_id, task_id, task_line_id, "case", object,
                   expected_pieces_per_unit, expiry_window_days)
            VALUES (%s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, task_line_id) DO NOTHING
            """,
            (principal.tenant_id, site_id, receipt["task_id"], item["line_id"], case, spec.object_noun, ppu, window),
        )
        cur.execute("UPDATE field.task SET title = %s, updated_at = NOW() WHERE id = %s::uuid",
                    (f"{'Grocery' if case == 'grocery' else 'Pharmacy'} delivery {receipt['ref_doc_no']}",
                     receipt["task_id"]))
    return {"task_id": receipt["task_id"], "ref_doc_no": receipt["ref_doc_no"], "line_id": item["line_id"],
            "case": case, "object": spec.object_noun, "material": item["material"], "expected_units": n,
            "expected_pieces_per_unit": ppu, "expiry_window_days": window}
