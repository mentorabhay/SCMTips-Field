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
@settings(max_examples=12, deadline=None)
@given(st.permutations(list(range(1, 7))), st.integers(min_value=1, max_value=6))
def test_pr1_15_queue_sequence_execution_order(enqueue_order: list[int], failing_seq: int) -> None:
    """PR1.15: the real PostingQueueWorker posts one queue strictly in seq order, whatever order the
    jobs were inserted in, and a job that keeps failing blocks every later seq of its queue."""
    import asyncio
    import uuid
    from datetime import UTC, datetime

    from field_sap.ports.erp_port import ErpError, ErpErrorKind, ErpPostingRequest, ErpResult
    from field_worker.posting.queue import DATABASE_URL, PostingQueueWorker, enqueue_posting_job

    class RecordingPort:  # test double for the ERP: records the order of PATCH calls
        def __init__(self) -> None:
            self.seen: list[int] = []

        async def update_inbound_delivery_item(self, req: ErpPostingRequest) -> ErpResult:
            n = int(req.header_data["Seq"])
            if n == failing_seq:
                raise ErpError(kind=ErpErrorKind.BUSINESS, message="rejected", retryable=False)
            self.seen.append(n)
            return ErpResult(req.idempotency_key, "", "", "InboundDeliveryItem", datetime.now(UTC))

    tenant = str(uuid.uuid4())
    queue = f"IBD:PR115-{uuid.uuid4().hex[:8]}"
    for n in enqueue_order:
        enqueue_posting_job(tenant_id=tenant, queue_key=queue, doc_family="InboundDeliveryItem", site_id="S",
                            plant="1010", header_data={"Seq": n}, items=[], seq=n,
                            idempotency_key=f"{queue}:{n}", db_url=DATABASE_URL)
    port = RecordingPort()
    worker = PostingQueueWorker(erp_port=port, db_url=DATABASE_URL)

    async def drain() -> None:
        for _ in range(20):
            if not await worker.process_one_job(tenant):
                return

    asyncio.run(drain())
    assert port.seen == list(range(1, failing_seq)), "posted out of order or past a failed seq"
