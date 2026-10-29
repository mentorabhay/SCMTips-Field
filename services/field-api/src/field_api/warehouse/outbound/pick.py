"""Outbound Picking Engine (Task T3.030 / FR3.018 / FR3.019 / PR3.08 / TC3.115 / TC3.116).

Enforces:
1. Source bin confirmation before product capture.
2. GTIN DataMatrix or SSCC match against required line material.
3. Batch (AI 10) and Serial (AI 21) enforcement when material is batch/serial-managed.
4. Pick quantity <= required quantity (PR3.08).
"""

from typing import Any

from pydantic import BaseModel


class PickConfirmationRequest(BaseModel):
    task_line_id: str
    scanned_bin: str
    scanned_code: str
    quantity: float = 1.0
    batch: str | None = None
    serial: str | None = None


class PickConfirmationResult(BaseModel):
    task_line_id: str
    is_confirmed: bool = True
    picked_qty: float
    remaining_qty: float
    storage_bin: str
    material_id: str
    batch: str | None = None
    serial: str | None = None
    message: str | None = None


class PickingException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PickEngine:
    """Evaluates and records outbound picks against line requirements."""

    @staticmethod
    def evaluate_pick(
        line: dict[str, Any],
        scanned_bin: str,
        scanned_code: str,
        quantity: float,
        batch: str | None = None,
        serial: str | None = None,
    ) -> dict[str, Any]:
        expected_bin = (line.get("storage_bin") or "").strip().upper()
        clean_scanned_bin = scanned_bin.strip().upper()

        # 1. Source bin check (FR3.018 / TC3.115)
        if expected_bin and clean_scanned_bin != expected_bin:
            raise PickingException(
                code="FIELD-PICK-422-BIN-MISMATCH",
                message=f"Scanned bin '{scanned_bin}' does not match line storage bin '{expected_bin}'",
                status_code=422,
            )

        # 2. Material / code check (FR3.019 / TC3.116)
        expected_material = (line.get("material_id") or "").strip().upper()
        clean_code = scanned_code.strip().upper()

        # Code can be GTIN, material_id, or SSCC
        if clean_code != expected_material and not clean_code.endswith(expected_material):
            # Check if scanned code contains expected material as prefix or token
            if expected_material not in clean_code:
                raise PickingException(
                    code="FIELD-PICK-422-WRONG-MATERIAL",
                    message=f"Scanned barcode '{scanned_code}' does not match expected material '{expected_material}'",
                    status_code=422,
                )

        # 3. Batch management check
        is_batch_managed = bool(line.get("is_batch_managed", False))
        if is_batch_managed and not batch:
            raise PickingException(
                code="FIELD-PICK-422-BATCH-REQUIRED",
                message="Material is batch-managed. Batch (AI 10) must be scanned or provided.",
                status_code=422,
            )

        # 4. Serial management check
        is_serial_managed = bool(line.get("is_serial_managed", False))
        if is_serial_managed and not serial:
            raise PickingException(
                code="FIELD-PICK-422-SERIAL-REQUIRED",
                message="Material is serial-managed. Serial number (AI 21) must be scanned or provided.",
                status_code=422,
            )

        # 5. Quantity bounds (PR3.08: picked <= required)
        current_picked = float(line.get("picked_qty", 0.0))
        required_qty = float(line.get("required_qty", 1.0))
        new_picked = current_picked + quantity

        if new_picked > required_qty:
            raise PickingException(
                code="FIELD-PICK-422-OVERPICK",
                message=f"Cannot pick {new_picked}: exceeds required line quantity {required_qty} (PR3.08)",
                status_code=422,
            )

        remaining = max(0.0, required_qty - new_picked)

        return {
            "task_line_id": line.get("id", ""),
            "is_confirmed": True,
            "picked_qty": new_picked,
            "remaining_qty": remaining,
            "storage_bin": expected_bin,
            "material_id": expected_material,
            "batch": batch or line.get("batch"),
            "serial": serial,
            "is_line_complete": remaining == 0.0,
        }
