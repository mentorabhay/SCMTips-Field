"""Pure Quantity and Line Number Formatting Rules (Task T1.059 / PR1.16).

Enforces:
1. Exact 3-decimal string formatting for ERP quantities (e.g. 24.000, 1.500).
2. Standard SAP line item numbering in steps of 10 with 6-digit zero padding:
   000010, 000020, 000030, etc.
"""

from decimal import ROUND_HALF_UP, Decimal


def format_erp_quantity(val: Decimal | float | int | str) -> str:
    """Format quantity to exactly 3 decimal places with ROUND_HALF_UP."""
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    quantized = val.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return f"{quantized:.3f}"


def format_erp_item_no(index: int, step: int = 10) -> str:
    """Format 1-based index to standard 6-digit SAP item number (step 10)."""
    if index < 1:
        raise ValueError(f"Line index must be >= 1, got {index}")
    num = index * step
    return f"{num:06d}"


def parse_erp_item_no(item_no: str, step: int = 10) -> int:
    """Parse 6-digit SAP item number back to 1-based line index."""
    num = int(item_no)
    return num // step
