"""Field Worker Posting Queue Package (Workstream WS3.2 / Tasks T3.010 - T3.015)."""

from field_worker.posting.events import (
    emit_erp_failed,
    emit_erp_posted,
    emit_erp_reversed,
    emit_posting_requested,
)
from field_worker.posting.idempotency import (
    generate_idempotency_key,
    probe_sap_document,
)
from field_worker.posting.queue import (
    DATABASE_URL,
    ClaimedJob,
    PostingQueueWorker,
    claim_next_job,
    enqueue_posting_job,
)
from field_worker.posting.retry import (
    BACKOFF_SCHEDULE,
    MAX_ATTEMPTS,
    classify_error,
    compute_backoff_jitter,
)

__all__ = [
    "BACKOFF_SCHEDULE",
    "DATABASE_URL",
    "MAX_ATTEMPTS",
    "ClaimedJob",
    "PostingQueueWorker",
    "claim_next_job",
    "classify_error",
    "compute_backoff_jitter",
    "emit_erp_failed",
    "emit_erp_posted",
    "emit_erp_reversed",
    "emit_posting_requested",
    "enqueue_posting_job",
    "generate_idempotency_key",
    "probe_sap_document",
]
