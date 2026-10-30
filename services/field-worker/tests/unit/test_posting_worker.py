"""Unit tests for PostingQueueWorker (Task T1.061 / FR1.008)."""

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from field_sap.ports.erp_port import ErpError, ErpErrorKind, ErpPostingRequest, ErpResult
from field_worker.posting import DATABASE_URL, PostingQueueWorker, enqueue_posting_job


class MockWorkerErpPort:
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
                message="Simulated failure",
                retryable=(self.fail_kind != ErpErrorKind.BUSINESS),
            )
        return ErpResult(
            idempotency_key=req.idempotency_key,
            document_number="4900999999",
            fiscal_year="2026",
            document_family="GoodsReceipt",
            posted_at=datetime.now(UTC),
            raw_response={"MaterialDocument": "4900999999"},
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
@pytest.mark.asyncio
async def test_posting_worker_successful_claim_and_outbox():
    tenant_id = str(uuid.uuid4())
    queue_key = f"ibd_queue_{uuid.uuid4().hex[:6]}"

    # Enqueue two jobs in sequence
    j1 = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000001"},
        items=[],
    )
    _j2 = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000002"},
        items=[],
    )

    port = MockWorkerErpPort()
    worker = PostingQueueWorker(erp_port=port)

    # Process first job (must be j1 due to lowest seq)
    did_process = await worker.process_one_job(tenant_id)
    assert did_process is True
    assert port.call_count == 1

    # Check j1 status in database
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
            cur.execute("SELECT status FROM field.posting_job WHERE id = %s;", (j1,))
            status = cur.fetchone()[0]
            assert status == "completed"

            # Verify outbox event emitted
            cur.execute("SELECT event_type FROM field.outbox WHERE tenant_id = %s;", (tenant_id,))
            events = [r[0] for r in cur.fetchall()]
            assert "erp.posted" in events


@pytest.mark.unit
@pytest.mark.asyncio
async def test_posting_worker_business_failure_marked_failed():
    tenant_id = str(uuid.uuid4())
    queue_key = f"ibd_queue_{uuid.uuid4().hex[:6]}"

    job_id = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={"DeliveryDocument": "180000003"},
        items=[],
    )

    # Port returns non-retryable BUSINESS error
    port = MockWorkerErpPort(fail_kind=ErpErrorKind.BUSINESS)
    worker = PostingQueueWorker(erp_port=port)

    did_process = await worker.process_one_job(tenant_id)
    assert did_process is True

    # Check status is failed
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
            cur.execute("SELECT status FROM field.posting_job WHERE id = %s;", (job_id,))
            status = cur.fetchone()[0]
            assert status == "failed"

            cur.execute("SELECT event_type FROM field.outbox WHERE tenant_id = %s;", (tenant_id,))
            events = [r[0] for r in cur.fetchall()]
            assert "erp.failed" in events
