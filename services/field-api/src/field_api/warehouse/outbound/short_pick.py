"""Short-Pick Exception Handling and Cycle-Count Trigger (Task T3.031 / FR3.020 / FR3.028 / TC3.117).

Enforces:
1. Valid short-pick reason code: bin_empty, damaged, not_found.
2. Short confirmed quantity < required quantity.
3. Automated cycle-count request created for the source bin.
"""

from typing import Any

from pydantic import BaseModel, Field


class ShortPickRequest(BaseModel):
    task_line_id: str
    short_qty: float
    reason_code: str = Field(..., description="One of: bin_empty, damaged, not_found")
    note: str | None = None


class ShortPickResult(BaseModel):
    task_line_id: str
    status: str
    confirmed_picked_qty: float
    shortage_qty: float
    reason_code: str
    cycle_count_requested: bool
    source_bin: str
    material_id: str


VALID_SHORT_PICK_REASONS = frozenset({"bin_empty", "damaged", "not_found"})


def handle_short_pick(
    line: dict[str, Any],
    short_qty: float,
    reason_code: str,
    note: str | None = None,
) -> dict[str, Any]:
    reason_clean = reason_code.strip().lower()
    if reason_clean not in VALID_SHORT_PICK_REASONS:
        raise ValueError(
            f"Invalid short pick reason '{reason_code}'. Must be one of: {sorted(VALID_SHORT_PICK_REASONS)}"
        )

    required_qty = float(line.get("required_qty", 1.0))
    if short_qty >= required_qty:
        raise ValueError(
            f"Short pick quantity ({short_qty}) must be strictly less than required quantity ({required_qty})"
        )
    if short_qty < 0:
        raise ValueError(f"Short pick quantity ({short_qty}) cannot be negative")

    shortage = required_qty - short_qty
    storage_bin = line.get("storage_bin") or "UNKNOWN_BIN"
    material_id = line.get("material_id") or "UNKNOWN_MAT"

    # Trigger cycle count for source bin per FR3.028
    cycle_count_event = {
        "event_type": "cycle_count_trigger",
        "trigger_source": "short_pick",
        "bin_id": storage_bin,
        "material_id": material_id,
        "reason_code": reason_clean,
        "shortage_qty": shortage,
    }

    return {
        "task_line_id": line.get("id", ""),
        "status": "short_confirmed",
        "confirmed_picked_qty": short_qty,
        "shortage_qty": shortage,
        "reason_code": reason_clean,
        "cycle_count_requested": True,
        "source_bin": storage_bin,
        "material_id": material_id,
        "cycle_count_event": cycle_count_event,
    }
