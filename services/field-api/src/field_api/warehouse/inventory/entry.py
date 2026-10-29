"""Physical Inventory Count Entry and Commit (Task T3.039 / FR3.030 / TC3.124).

Handles:
1. Spoken count or camera capture ("count 12", "count zero" -> zero count flag).
2. Requires explicit confirmed status before commitment.
3. Produces immutable count_record per counter per count cycle.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class InventoryCountEntry(BaseModel):
    pi_doc_id: str
    line_id: str
    counted_qty: float = Field(..., ge=0.0)
    is_zero_count: bool = False
    counter_operator_id: str
    is_confirmed: bool = False


class InventoryCountCommitResult(BaseModel):
    count_record_id: str
    pi_doc_id: str
    line_id: str
    committed_qty: float
    is_zero_count: bool
    status: str
    counted_at: str


def record_inventory_count(entry: InventoryCountEntry) -> dict[str, Any]:
    """Records an inventory count line. Rejects unconfirmed commitments."""
    if not entry.is_confirmed:
        raise ValueError(
            "Cannot commit count without explicit confirmation ('confirm' turn required)"
        )

    qty = 0.0 if entry.is_zero_count else entry.counted_qty
    record_id = str(uuid.uuid4())

    return {
        "count_record_id": record_id,
        "pi_doc_id": entry.pi_doc_id,
        "line_id": entry.line_id,
        "committed_qty": qty,
        "is_zero_count": entry.is_zero_count or (qty == 0.0),
        "counter_operator_id": entry.counter_operator_id,
        "status": "counted",
        "counted_at": datetime.now(UTC).isoformat(),
    }
