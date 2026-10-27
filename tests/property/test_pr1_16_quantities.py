"""Property Test PR1.16: Decimal Quantities (3 decimals) and Item Number Steps (000010)."""

from decimal import Decimal

import pytest
from field_sap.mapping.quantities import format_erp_item_no, format_erp_quantity, parse_erp_item_no
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.property
@given(
    qty=st.decimals(
        min_value=Decimal("0.000"),
        max_value=Decimal("99999999.999"),
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_pr1_16_decimal_quantity_formatting(qty: Decimal):
    """PR1.16 Invariant 1: Quantities always produce string with exactly 3 decimals."""
    formatted = format_erp_quantity(qty)
    assert "." in formatted
    parts = formatted.split(".")
    assert len(parts[1]) == 3, f"Expected 3 decimals, got {parts[1]} for {qty}"


@pytest.mark.property
@given(idx=st.integers(min_value=1, max_value=9999))
def test_pr1_16_item_number_steps_roundtrip(idx: int):
    """PR1.16 Invariant 2: Item numbers step in increments of 10 and have 6 digits."""
    item_str = format_erp_item_no(idx)
    assert len(item_str) == 6
    assert item_str.isdigit()
    assert int(item_str) % 10 == 0

    # Roundtrip check
    parsed = parse_erp_item_no(item_str)
    assert parsed == idx
