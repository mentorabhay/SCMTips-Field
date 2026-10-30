"""Physical Inventory Differences Posting (Task T3.042 / FR3.033 / FR3.034 / TC3.127 / PR3.05).

Posts SAP movement types:
- Movement 701: Inventory Gain (counted > book)
- Movement 702: Inventory Loss (counted < book)
Enforces variance approval check (PR3.05) prior to submission.
"""

from typing import Any

from field_api.warehouse.inventory.approvals import (
    evaluate_variance_approval_requirement,
    validate_approval_state_for_posting,
)


def post_physical_inventory_difference(
    pi_line: dict[str, Any],
    counted_qty: float,
    book_qty: float,
    unit_price: float = 100.0,
    approval_record: dict[str, Any] | None = None,
    counter_id: str = "counter-01",
) -> dict[str, Any]:
    """Calculates gain/loss and posts difference document 701/702."""
    diff_qty = counted_qty - book_qty
    needs_approval, variance_val = evaluate_variance_approval_requirement(diff_qty, unit_price)

    # Enforce PR3.05
    validate_approval_state_for_posting(
        variance_val=variance_val,
        approval_record=approval_record,
        counter_id=counter_id,
    )

    if diff_qty > 0:
        movement_type = "701"  # Physical inventory gain
        quantity = diff_qty
    elif diff_qty < 0:
        movement_type = "702"  # Physical inventory loss
        quantity = abs(diff_qty)
    else:
        movement_type = "NONE"
        quantity = 0.0


    return {
        "line_id": pi_line.get("line_id") or pi_line.get("id"),
        "pi_doc_id": pi_line.get("pi_doc_id"),
        "counted_qty": counted_qty,
        "book_qty": book_qty,
        "difference_qty": diff_qty,
        "movement_type": movement_type,
        "quantity_posted": quantity,
        "difference_doc_no": None,  # assigned by the ERP (PostDifferences via field-worker), never invented
        "variance_value": variance_val,
        "status": "difference_staged" if diff_qty != 0 else "no_difference",
    }
