"""Warehouse Quantity Derivation and Counting Engine (Task T3.019 / FR3.005 / FR3.006 / PR3.02 / TC3.105).

Rules:
1. HU Quantity derivation hierarchy:
   - GS1 AI 37 or AI 30 if present in scanned barcode data.
   - Else material pack quantity (units_per_carton).
   - Else requests a voice count (needs_voice_count = True).
2. Line counted quantity calculation (PR3.02):
   - Latest non-undone voice count if any.
   - Else sum of quantities of non-discarded captures on the line.
"""

import re
from typing import Any


def extract_gs1_ai_quantity(barcode_data: str) -> float | None:
    """Extract quantity from GS1 AI 37 (count) or AI 30 (count variable)."""
    if not barcode_data:
        return None

    # Handle parenthesis format: (37)12 or (30)24
    m_paren = re.search(r"\((?:37|30)\)(\d+)", barcode_data)
    if m_paren:
        return float(m_paren.group(1))

    # Handle FNC1 / plain GS1-128 format: 37... or 30...
    m_plain = re.search(r"(?:^|[\x1d\s])(?:37|30)(\d{1,8})(?:[\x1d\s]|$)", barcode_data)
    if m_plain:
        return float(m_plain.group(1))

    return None


def derive_hu_quantity(
    barcode_data: str | None = None,
    material_units_per_carton: float | None = None,
) -> tuple[float | None, bool]:
    """Derive handling unit quantity from available signals.

    Returns:
        (quantity, needs_voice_count)
    """
    # 1. GS1 AI 37 / AI 30
    if barcode_data:
        ai_qty = extract_gs1_ai_quantity(barcode_data)
        if ai_qty is not None and ai_qty > 0:
            return ai_qty, False

    # 2. Material pack quantity
    if material_units_per_carton is not None and material_units_per_carton > 0:
        return float(material_units_per_carton), False

    # 3. Needs voice count
    return None, True


def compute_line_counted_quantity(
    captures: list[dict[str, Any]],
    voice_counts: list[dict[str, Any]] | None = None,
) -> float:
    """Compute task_line counted_qty per Property PR3.02.

    Invariant PR3.02:
    counted_qty = latest non-undone voice count if any,
    else sum of quantities of non-discarded captures.
    """
    # 1. Check for valid voice count overrides
    if voice_counts:
        # Sort or filter for latest non-undone voice count
        active_voice = [v for v in voice_counts if not v.get("is_undone", False)]
        if active_voice:
            # Most recent non-undone voice count
            latest = active_voice[-1]
            return float(latest.get("quantity", 0.0))

    # 2. Sum non-discarded captures
    valid_captures = [c for c in captures if not c.get("is_discarded", False)]
    total = sum(float(c.get("quantity", 1.0)) for c in valid_captures)
    return total
