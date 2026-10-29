"""Goods Issue and Reversal Orchestrator (Task T3.034 / FR3.023 - FR3.025 / PR3.08 / PR3.01 / TC3.120).

Invariants:
1. PR3.08: Goods issue quantity strictly equals picked quantity, never exceeds.
2. PR3.01: Post goods issue (601) and reverse goods issue (602) evaluate to net zero stock delta.
3. 601 is permitted only when all lines in delivery are picked or short-confirmed.
"""

import uuid
from typing import Any


class GoodsIssueException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def post_goods_issue(
    delivery_no: str,
    lines: list[dict[str, Any]],
    tenant_id: str = "tenant-default",
) -> dict[str, Any]:
    """Posts SAP movement 601 goods issue against picked delivery lines."""
    if not lines:
        raise GoodsIssueException("FIELD-GI-422-EMPTY", "Delivery has no lines to issue")

    total_picked = 0.0
    items_to_issue: list[dict[str, Any]] = []

    for line in lines:
        required_qty = float(line.get("required_qty", 1.0))
        picked_qty = float(line.get("picked_qty", 0.0))
        status = line.get("status", "open")

        # Must be picked or short_confirmed (FR3.023)
        if status not in ("picked", "short_confirmed", "packed") and picked_qty < required_qty:
            raise GoodsIssueException(
                "FIELD-GI-422-INCOMPLETE",
                f"Line '{line.get('id')}' is not fully picked or short-confirmed (picked {picked_qty}/{required_qty})",
            )

        # Invariant PR3.08: GI quantity == picked quantity
        if picked_qty > required_qty:
            raise GoodsIssueException(
                "FIELD-GI-422-OVERPICK",
                f"Line '{line.get('id')}' picked {picked_qty} exceeds required {required_qty} (PR3.08)",
            )

        if picked_qty > 0:
            total_picked += picked_qty
            items_to_issue.append(
                {
                    "line_id": line.get("id"),
                    "material_id": line.get("material_id"),
                    "quantity": picked_qty,
                    "movement_type": "601",
                }
            )

    matdoc_no = f"490{uuid.uuid4().int % 10000000:07d}"

    return {
        "delivery_no": delivery_no,
        "material_document_no": matdoc_no,
        "movement_type": "601",
        "total_issued_qty": total_picked,
        "items": items_to_issue,
        "status": "goods_issue_posted",
        "tenant_id": tenant_id,
    }


def reverse_goods_issue(
    original_gi: dict[str, Any],
    reason: str = "supervisor_reversal",
) -> dict[str, Any]:
    """Posts SAP movement 602 goods issue reversal (PR3.01: net delta nets to zero)."""
    orig_doc = original_gi.get("material_document_no")
    if not orig_doc:
        raise GoodsIssueException(
            "FIELD-REV-422-NO-ORIGINAL", "Original material document number required"
        )

    reversal_items = []
    total_reversed = 0.0

    for itm in original_gi.get("items", []):
        qty = float(itm.get("quantity", 0.0))
        total_reversed += qty
        reversal_items.append(
            {
                "line_id": itm.get("line_id"),
                "material_id": itm.get("material_id"),
                "quantity": qty,
                "movement_type": "602",
                "referenced_doc_item": orig_doc,
            }
        )

    reversal_doc_no = f"490{uuid.uuid4().int % 10000000:07d}"

    return {
        "delivery_no": original_gi.get("delivery_no"),
        "original_material_document_no": orig_doc,
        "reversal_material_document_no": reversal_doc_no,
        "movement_type": "602",
        "total_reversed_qty": total_reversed,
        "net_stock_delta": 0.0,  # Invariant PR3.01
        "items": reversal_items,
        "status": "reversal_posted",
        "reason": reason,
    }
