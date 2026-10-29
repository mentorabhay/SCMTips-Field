"""Outbound Packing and SSCC Handling Unit Generator (Task T3.033 / FR3.022 / TC3.119 / PR3.12).

Enforces:
1. Valid 18-digit GS1 Mod-10 check digit on generated or scanned SSCCs.
2. Packed quantity per line <= picked quantity.
3. Attachment of picked lines to outbound handling unit.
"""

import uuid
from typing import Any


def calculate_gs1_mod10_check_digit(digits17: str) -> int:
    """Standard GS1 Mod-10 check digit calculation."""
    require_len = 17
    if len(digits17) != require_len or not digits17.isdigit():
        raise ValueError("Input must be exactly 17 numeric digits")

    total = 0
    for i, char in enumerate(digits17):
        digit = int(char)
        # Weights: 3, 1, 3, 1... on 0-based index
        weight = 3 if (i % 2 == 0) else 1
        total += digit * weight

    rem = total % 10
    return 0 if rem == 0 else 10 - rem


def generate_sscc(
    company_prefix: str = "0890123",
    extension_digit: str = "0",
    serial_ref: int = 1,
) -> str:
    """Generates an 18-digit GS1 SSCC with compliant Mod-10 check digit (PR3.12)."""
    # SSCC format: extension (1) + company prefix (7) + serial ref (9) = 17 digits + check (1)
    prefix_len = len(company_prefix)
    serial_len = 16 - prefix_len
    serial_str = str(serial_ref).zfill(serial_len)

    digits17 = f"{extension_digit}{company_prefix}{serial_str}"
    check = calculate_gs1_mod10_check_digit(digits17)
    return f"{digits17}{check}"


def validate_sscc(sscc: str) -> bool:
    """Validates 18-digit length, digits only, and Mod-10 check digit."""
    if len(sscc) != 18 or not sscc.isdigit():
        return False
    expected_check = calculate_gs1_mod10_check_digit(sscc[:17])
    return int(sscc[17]) == expected_check


class OutboundPackManager:
    """Packs picked items into outbound handling units."""

    @staticmethod
    def pack_line(
        line: dict[str, Any],
        pack_quantity: float,
        existing_sscc: str | None = None,
        serial_counter: int = 1,
    ) -> dict[str, Any]:
        picked_qty = float(line.get("picked_qty", 0.0))
        if pack_quantity > picked_qty:
            raise ValueError(
                f"Cannot pack {pack_quantity}: exceeds picked quantity {picked_qty} (FR3.022)"
            )
        if pack_quantity <= 0:
            raise ValueError("Pack quantity must be greater than zero")

        if existing_sscc:
            if not validate_sscc(existing_sscc):
                raise ValueError(f"Scanned SSCC '{existing_sscc}' has invalid Mod-10 check digit")
            sscc = existing_sscc
        else:
            sscc = generate_sscc(serial_ref=serial_counter)

        hu_id = str(uuid.uuid4())
        return {
            "handling_unit_id": hu_id,
            "sscc": sscc,
            "task_line_id": line.get("id", ""),
            "material_id": line.get("material_id", ""),
            "packed_quantity": pack_quantity,
            "status": "packed",
            "delivery_ref": line.get("delivery_no", ""),
        }
