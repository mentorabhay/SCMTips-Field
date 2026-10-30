"""Comprehensive WS3.2 Posting Queue Tests (Tasks T3.010 - T3.015 / PR3.06 / PR3.07 / PR3.13).

Covers:
- T3.010 / TC3.131 / PR3.07: Ordered claim, predecessor blocking, and single-worker queue locking
- T3.011 / TC3.132 / PR3.13: Retry classification, fail-fast validation, and jittered backoff
- T3.012 / TC3.133 / PR3.06: Compact 23-char key, pre-post probe and adoption
- T3.014 / EV3.01 - EV3.04: Atomic outbox events emission
"""

import json
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from field_common.uuid7 import uuid7_str
from field_sap.ports.erp_port import ErpError, ErpErrorKind, ErpPostingRequest, ErpResult
from field_worker.posting import (
    DATABASE_URL,
    PostingQueueWorker,
    claim_next_job,
    classify_error,
    compute_backoff_jitter,
    emit_erp_failed,
    emit_erp_posted,
    emit_erp_reversed,
    emit_posting_requested,
    enqueue_posting_job,
    generate_idempotency_key,
)


class MockErpPortWS32:
    def __init__(self, fail_kind: ErpErrorKind | None = None) -> None:
        self.fail_kind = fail_kind
        self.call_count = 0

    async def list_materials(self, *args, **kwargs):
        raise NotImplementedError

    async def find_by_idempotency_key(self, *args, **kwargs):
        return None

    async def post_inbound_goods_receipt(self, req: ErpPostingRequest) -> ErpResult:
        self.call_count += 1
        if self.fail_kind:
            raise ErpError(
                kind=self.fail_kind,
                message="Simulated error",
                retryable=(self.fail_kind != ErpErrorKind.BUSINESS),
            )
        return ErpResult(
            idempotency_key=req.idempotency_key,
            document_number="4900123456",
            fiscal_year="2026",
            document_family="GoodsReceipt",
            posted_at=datetime.now(UTC),
            raw_response={"MaterialDocument": "4900123456"},
        )

    async def cancel_material_document(self, *args, **kwargs):
        raise NotImplementedError

    async def pick_outbound_delivery(self, *args, **kwargs):
        raise NotImplementedError

    async def post_outbound_goods_issue(self, *args, **kwargs):
        raise NotImplementedError

    async def create_physical_inventory_doc(self, *args, **kwargs):
        raise NotImplementedError

    async def enter_physical_inventory_count(self, *args, **kwargs):
        raise NotImplementedError

    async def post_physical_inventory_differences(self, *args, **kwargs):
        raise NotImplementedError

    async def post_transfer_posting(self, *args, **kwargs):
        raise NotImplementedError


@pytest.mark.unit
def test_t3_012_compact_idempotency_key_format():
    """T3.012 / PR3.06: Compact 23-char idempotency key format: 'F' + base64url(uuid)."""
    key = generate_idempotency_key()
    assert len(key) == 23, f"Expected 23 chars, got {len(key)}: {key}"
    assert key.startswith("F"), f"Key must start with 'F': {key}"
    # Verify randomness across 100 keys
    keys = {generate_idempotency_key() for _ in range(100)}
    assert len(keys) == 100


@pytest.mark.unit
def test_t3_011_retry_classification_and_backoff_jitter():
    """T3.011 / PR3.13 / TC3.132: Classification into network/server/lock/validation and jittered backoff."""
    # 1. Classification
    lock_err = Exception("ZSIM/LOCKED: resource locked by session sess_1")
    err_class, retryable, _ = classify_error(lock_err)
    assert err_class == "lock"
    assert retryable is True

    vl046_err = Exception("SAP error VL/046: document currently being processed")
    err_class, retryable, _ = classify_error(vl046_err)
    assert err_class == "lock"
    assert retryable is True

    timeout_err = TimeoutError("Connection to ERP timed out after 30s")
    err_class, retryable, _ = classify_error(timeout_err)
    assert err_class == "network"
    assert retryable is True

    class Dummy400Error(Exception):
        status_code = 400

    val_err = Dummy400Error("Field actual_qty exceeds delivery_qty")
    err_class, retryable, _ = classify_error(val_err)
    assert err_class == "validation"
    assert retryable is False  # Must fail fast!

    # 2. Backoff + Jitter schedule
    expected_bases = [2.0, 4.0, 8.0, 16.0, 32.0, 32.0, 32.0, 32.0]
    for attempt, expected_base in enumerate(expected_bases, start=1):
        delays = [compute_backoff_jitter(attempt) for _ in range(20)]
        for d in delays:
            # Jitter is ±10%
            assert expected_base * 0.89 <= d <= expected_base * 1.11, (
                f"Attempt {attempt} delay {d} out of range"
            )


@pytest.mark.unit
def test_t3_010_ordered_queue_claim_and_predecessor_blocking():
    """T3.010 / FR3.038 / PR3.07: Lowest seq claimed first; uncompleted predecessor blocks later jobs."""
    tenant_id = str(uuid.uuid4())
    queue_key = f"IBD:TEST_QUEUE_{uuid.uuid4().hex[:6]}"

    # Enqueue seq 2 then seq 1
    j2 = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000002"},
        items=[],
        seq=2,
    )
    j1 = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000001"},
        items=[],
        seq=1,
    )

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        # 1. First claim must get j1 (seq 1), despite j2 being enqueued first
        claimed1 = claim_next_job(cur, tenant_id)
        assert claimed1 is not None
        assert claimed1.job_id == j1
        assert claimed1.seq == 1
        conn.commit()

    # 2. While j1 is 'running', j2 cannot be claimed (at most one worker per queue_key)
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        claimed_while_running = claim_next_job(cur, tenant_id)
        assert claimed_while_running is None
        conn.rollback()

    # 3. Complete j1
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute("UPDATE field.posting_job SET status = 'completed' WHERE id = %s;", (j1,))

    # 4. Now j2 (seq 2) can be claimed
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        claimed2 = claim_next_job(cur, tenant_id)
        assert claimed2 is not None
        assert claimed2.job_id == j2
        assert claimed2.seq == 2
        conn.commit()


@pytest.mark.unit
def test_t3_010_failed_job_blocks_later_jobs_until_retried():
    """T3.010 / BR3.14: A failed job blocks later jobs in the same queue until unblocked."""
    tenant_id = str(uuid.uuid4())
    queue_key = f"OBD:TEST_BLOCK_{uuid.uuid4().hex[:6]}"

    j1 = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=1,
    )
    enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=2,
    )

    # Set j1 to failed
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute("UPDATE field.posting_job SET status = 'failed' WHERE id = %s;", (j1,))

    # Attempt to claim next job: j2 must NOT be claimed because queue is blocked by j1
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        claimed = claim_next_job(cur, tenant_id)
        assert claimed is None, "Queue must be blocked by failed predecessor"
        conn.rollback()

    # Retry j1 (set status back to pending)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute("UPDATE field.posting_job SET status = 'pending' WHERE id = %s;", (j1,))

    # Now j1 can be claimed
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        claimed_j1 = claim_next_job(cur, tenant_id)
        assert claimed_j1 is not None
        assert claimed_j1.job_id == j1
        conn.commit()


@pytest.mark.unit
def test_t3_014_outbox_events_emission():
    """T3.014 / EV3.01 - EV3.04: All 4 posting events validate and persist to field.outbox."""
    tenant_id = str(uuid.uuid4())
    job_id = uuid7_str()

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

        # 1. EV3.01 posting.requested
        ev1 = emit_posting_requested(
            cur,
            tenant_id=tenant_id,
            job_id=job_id,
            queue_key="IBD:180000123",
            doc_type="GR",
            jobs=[{"seq": 41, "kind": "patch_item"}, {"seq": 42, "kind": "post_gr"}],
        )
        assert ev1 is not None

        # 2. EV3.02 erp.posted
        ev2 = emit_erp_posted(
            cur,
            tenant_id=tenant_id,
            job_id=job_id,
            doc_type="GR",
            doc_no="4900000101",
            doc_year=2026,
            movement_types=["101"],
            queue_key="IBD:180000123",
            adopted_by_probe=False,
        )
        assert ev2 is not None

        # 3. EV3.03 erp.reversed
        ev3 = emit_erp_reversed(
            cur,
            tenant_id=tenant_id,
            job_id=job_id,
            doc_no="4900000102",
            reverses="4900000101",
            movement_types=["102"],
            items=["0001"],
        )
        assert ev3 is not None

        # 4. EV3.04 erp.failed
        ev4 = emit_erp_failed(
            cur,
            tenant_id=tenant_id,
            job_id=job_id,
            queue_key="OBD:800000045",
            seq=7,
            attempts=8,
            error_class="lock",
            sap_message="VL/046",
        )
        assert ev4 is not None

        conn.commit()

    # Verify rows in outbox
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute(
            "SELECT event_type FROM field.outbox WHERE tenant_id = %s ORDER BY created_at ASC;",
            (tenant_id,),
        )
        types = [r[0] for r in cur.fetchall()]
        assert types == ["posting.requested", "erp.posted", "erp.reversed", "erp.failed"]


@pytest.mark.asyncio
async def test_t3_012_pre_post_probe_adoption():
    """T3.012 / TC3.133: a retry after a timed-out-but-committed post adopts the ERP document.

    The probe goes through the real SimAdapter to the real erp-sim app (header text FIELD:<key>);
    the posting call itself must not be repeated.
    """
    from erp_sim.app import app as erp_app
    from field_sap.sim.adapter import SimAdapter

    class CountingSim(SimAdapter):
        posts = 0

        async def post_inbound_goods_receipt(self, req: ErpPostingRequest) -> ErpResult:
            CountingSim.posts += 1
            raise AssertionError("must not post again: the probe should have adopted the document")

    tenant_id = str(uuid.uuid4())
    queue_key = f"IBD:PROBE_{uuid.uuid4().hex[:6]}"
    idem_key = generate_idempotency_key()
    doc_no = f"49{uuid.uuid4().int % 10**8:08d}"

    # The ERP committed the document under this key, but the worker never saw the answer.
    erpsim_url = "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim"
    with psycopg.connect(erpsim_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO erpsim.dedupe (client, idem_key, request_hash, document_no, fiscal_year)"
            " VALUES ('100', %s, 'hash_abc', %s, '2026') ON CONFLICT DO NOTHING",
            (idem_key, doc_no),
        )

    job_id = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000999"},
        items=[],
        idempotency_key=idem_key,
    )
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute("UPDATE field.posting_job SET attempts = 1 WHERE id = %s;", (job_id,))

    worker = PostingQueueWorker(erp_port=CountingSim(app=erp_app), db_url=DATABASE_URL)
    assert await worker.process_one_job(tenant_id) is True
    assert CountingSim.posts == 0

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute("SELECT status FROM field.posting_job WHERE id = %s;", (job_id,))
        assert cur.fetchone()[0] == "completed"
        cur.execute(
            "SELECT payload FROM field.outbox WHERE tenant_id = %s AND event_type = 'erp.posted';",
            (tenant_id,),
        )
        raw = cur.fetchone()[0]
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        assert payload["data"]["adopted_by_probe"] is True
        assert payload["data"]["doc_no"] == doc_no
