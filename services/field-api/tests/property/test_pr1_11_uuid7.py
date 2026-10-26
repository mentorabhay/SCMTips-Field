"""Property Test PR1.11: UUIDv7 Invariants (RFC 9562).

Verifies:
1. Version nibble is 7
2. Variant bits are 10
3. Monotonic ordering: strictly increasing 128-bit values
4. Timestamp matches system clock
"""

import time

import hypothesis.strategies as st
import pytest
from field_common.uuid7 import uuid7
from hypothesis import given, settings


@pytest.mark.property
@settings(max_examples=100)
@given(st.integers(min_value=5, max_value=50))
def test_pr1_11_uuid7_monotonic_and_format(count: int) -> None:
    now_ms = int(time.time() * 1000)
    generated = [uuid7() for _ in range(count)]

    # 1. Version must be 7
    for u in generated:
        assert u.version == 7, f"Expected UUID version 7, got {u.version}"

    # 2. Variant must be RFC 4122 / 9562 (10)
    for u in generated:
        assert u.variant == "specified in RFC 4122", f"Invalid variant: {u.variant}"

    # 3. Monotonic strictly increasing 128-bit integer values
    ints = [u.int for u in generated]
    for i in range(len(ints) - 1):
        assert ints[i] < ints[i + 1], f"UUIDv7 sequence must be strictly monotonic: {ints[i]} >= {ints[i+1]}"

    # 4. Timestamp within 10 seconds of system clock
    first_ts = ints[0] >> 80
    assert abs(first_ts - now_ms) < 10000, f"Timestamp drift too large: {first_ts} vs {now_ms}"
