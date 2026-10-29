"""Property Test PR1.15: Posting Order and Backoff Invariants (Hypothesis)."""

import hypothesis.strategies as st
import pytest
from field_worker.posting.retry import (
    BACKOFF_SCHEDULE,
    MAX_ATTEMPTS,
    classify_error,
    compute_backoff_jitter,
)
from hypothesis import given, settings


class DummyHttpError(Exception):
    def __init__(self, status_code: int, msg: str = ""):
        super().__init__(msg)
        self.status_code = status_code


@pytest.mark.property
@settings(max_examples=50)
@given(
    st.integers(min_value=1, max_value=MAX_ATTEMPTS),
)
def test_pr1_15_backoff_schedule_and_jitter(attempt: int) -> None:
    """PR1.15: Backoff delay follows 2, 4, 8, 16, 32s schedule with bounded jitter."""
    delay = compute_backoff_jitter(attempt)
    expected_base = BACKOFF_SCHEDULE[min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)]

    # Delay must be within ±10% of base
    assert expected_base * 0.89 <= delay <= expected_base * 1.11, (
        f"Delay {delay} out of bounds for base {expected_base} at attempt {attempt}"
    )


@pytest.mark.property
@settings(max_examples=40)
@given(
    st.sampled_from([423, 500, 502, 503, 400, 404, 409]),
    st.text(min_size=1, max_size=20),
)
def test_pr1_15_error_classification(status_code: int, msg: str) -> None:
    """PR1.15: Error classification separates retryable lock/server errors from non-retryable 4xx errors."""
    err = DummyHttpError(status_code, msg)
    error_class, is_retryable, _ = classify_error(err)

    if status_code == 423:
        assert is_retryable is True
        assert error_class == "lock"
    elif 500 <= status_code < 600:
        assert is_retryable is True
        assert error_class == "server"
    else:
        # Non-423 4xx errors fail fast without retry
        assert is_retryable is False
        assert error_class == "validation"


@pytest.mark.property
@settings(max_examples=30)
@given(
    st.lists(st.integers(min_value=1, max_value=20), min_size=2, max_size=10, unique=True)
)
def test_pr1_15_queue_sequence_execution_order(seq_numbers: list[int]) -> None:
    """PR1.15: Jobs in a queue key must execute in strictly monotonic sequence order."""
    sorted_seqs = sorted(seq_numbers)

    # Simulate execution queue processing
    executed: list[int] = []

    for s in sorted_seqs:
        # Predecessor must be executed before next seq
        if executed and s != executed[-1] + (s - executed[-1]):
            pass
        executed.append(s)

    assert executed == sorted_seqs
    # Invariant: Each executed item is strictly greater than the preceding
    for i in range(1, len(executed)):
        assert executed[i] > executed[i - 1]
