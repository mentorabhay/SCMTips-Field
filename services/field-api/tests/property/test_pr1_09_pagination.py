"""Property Test PR1.09: Keyset Cursor Pagination Invariants (Hypothesis)."""

import hypothesis.strategies as st
import pytest
from field_api.http.pagination import decode_cursor, encode_cursor
from hypothesis import given, settings


@pytest.mark.property
@settings(max_examples=50)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=100000),
            st.text(min_size=1, max_size=10, alphabet="abcdef0123456789"),
        ),
        min_size=1,
        max_size=100,
        unique_by=lambda x: x[0],
    ),
    st.integers(min_value=1, max_value=25),
)
def test_pr1_09_pagination_completeness(items: list[tuple[int, str]], page_limit: int) -> None:
    """PR1.09: Keyset cursor pagination completeness, monotonicity, and cursor signature validity."""
    # Sort items strictly by primary key (id)
    sorted_items = sorted(items, key=lambda x: x[0])
    all_keys = [x[0] for x in sorted_items]

    # Simulate keyset pagination loop
    collected_keys: list[int] = []
    cursor: str | None = None
    pages_count = 0

    while True:
        pages_count += 1
        last_id = decode_cursor(cursor)

        # Filter items where id > last_id
        if last_id is not None:
            remaining = [item for item in sorted_items if item[0] > int(last_id)]
        else:
            remaining = sorted_items

        # Fetch up to page_limit + 1 for lookahead
        batch = remaining[: page_limit + 1]
        has_more = len(batch) > page_limit
        page_items = batch[:page_limit]

        for item in page_items:
            collected_keys.append(item[0])

        if has_more and page_items:
            cursor = encode_cursor(str(page_items[-1][0]))
        else:
            cursor = None
            break

    # Verification 1: All items collected exactly once in original sorted order
    assert collected_keys == all_keys

    # Verification 2: No duplicates across pages
    assert len(collected_keys) == len(set(collected_keys))

    # Verification 3: Each cursor was valid and tamper-evident
    tampered = encode_cursor("12345") + "tampered"
    assert decode_cursor(tampered) is None
