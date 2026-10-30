"""Ordered Posting Queue Claim and Worker (Task T3.010 / FR3.038 / FR3.039 / PR3.07).

Key Invariants:
1. Ordered claim: Within each queue_key, jobs execute strictly in `seq` order (PR3.07).
2. Concurrency control: At most one worker processes a queue_key at a time via
   FOR UPDATE SKIP LOCKED and pg_try_advisory_xact_lock(hashtext(tenant_id || queue_key)) (TC3.131).
3. Blocking: A failed or uncompleted predecessor blocks later jobs until retried or cancelled (BR3.14).
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import psycopg
import structlog
from field_common.uuid7 import uuid7_str
from field_sap.ports.erp_port import ErpPort, ErpPostingRequest

from field_worker.posting.events import emit_erp_failed, emit_erp_posted
from field_worker.posting.idempotency import generate_idempotency_key, probe_sap_document
from field_worker.posting.retry import (
    MAX_ATTEMPTS,
    classify_error,
    compute_backoff_jitter,
)

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


@dataclass
class ClaimedJob:
    job_id: str
    tenant_id: str
    queue_key: str
    seq: int
    ref_doc_no: str | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    erp_doc_id: str | None = None


# Doc families whose success means the ERP document is posted (item PATCHes are intermediate).
FINAL_DOC_FAMILIES = frozenset({"GoodsReceipt", "GoodsIssue", "Cancellation", "PhysicalInventory", "Transfer"})
MOVEMENT_TYPES = MappingProxyType(
    {"GoodsReceipt": "101", "GoodsIssue": "601", "PhysicalInventory": "701/702", "Transfer": "311"}
)


def finalize_erp_document(cur: psycopg.Cursor[Any], job: ClaimedJob, doc_no: str, doc_year: str | int) -> None:
    """Write the ERP document number back and close the task lines it posted (C4).

    erp_document.payload carries ``task_id``, ``line_ids`` and, for reversals, ``reverses``
    (the original erp_document id) and ``line_status_after``.
    """
    if not job.erp_doc_id:
        return
    cur.execute(
        """
        UPDATE field.erp_document
           SET status = 'posted', doc_number = %s, fiscal_year = %s, version = version + 1, updated_at = NOW()
         WHERE id = %s
     RETURNING payload
        """,
        (str(doc_no) or None, str(doc_year), job.erp_doc_id),
    )
    row = cur.fetchone()
    if not row:
        return
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    line_ids = payload.get("line_ids") or []
    reverses = payload.get("reverses")
    if reverses:
        cur.execute(
            "UPDATE field.erp_document SET status = 'reversed', updated_at = NOW() WHERE id = %s",
            (reverses,),
        )
    line_status = payload.get("line_status_after", "posted")
    if line_ids:
        cur.execute(
            "UPDATE field.task_line SET status = %s, version = version + 1, updated_at = NOW() WHERE id = ANY(%s::uuid[])",
            (line_status, line_ids),
        )
    task_id = payload.get("task_id")
    if task_id:
        cur.execute(
            """
            UPDATE field.task t SET status = CASE
                     WHEN NOT EXISTS (SELECT 1 FROM field.task_line l
                                       WHERE l.task_id = t.id AND l.status NOT IN ('posted', 'cancelled'))
                     THEN 'completed' ELSE 'in_progress' END,
                   version = version + 1, updated_at = NOW()
             WHERE t.id = %s
            """,
            (task_id,),
        )


def enqueue_posting_job(
    tenant_id: str,
    queue_key: str,
    doc_family: str,
    site_id: str,
    plant: str,
    header_data: dict[str, Any],
    items: list[dict[str, Any]],
    idempotency_key: str | None = None,
    seq: int = 1,
    ref_doc_no: str | None = None,
    db_url: str = DATABASE_URL,
) -> str:
    """Enqueue an ordered posting job in field.posting_job."""
    job_id = uuid7_str()
    idem_key = idempotency_key or generate_idempotency_key()

    payload = {
        "idempotency_key": idem_key,
        "doc_family": doc_family,
        "site_id": site_id,
        "plant": plant,
        "header_data": header_data,
        "items": items,
        "seq": seq,
        "ref_doc_no": ref_doc_no,
    }

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
        cur.execute(
            """
            INSERT INTO field.posting_job (
                id, tenant_id, queue_key, seq, ref_doc_no, payload, status,
                attempts, max_attempts, next_attempt_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', 0, 8, NOW());
        """,
            (job_id, tenant_id, queue_key, seq, ref_doc_no, json.dumps(payload)),
        )

    return job_id


def claim_next_job(
    cur: psycopg.Cursor[Any],
    tenant_id: str,
    worker_id: str | None = None,
) -> ClaimedJob | None:
    """Claim lowest-seq pending job per queue_key with transactional advisory locking.

    Ensures:
    1. Predecessors in same queue_key with seq < current.seq must be completed or cancelled.
    2. No currently running or failed jobs in same queue_key.
    3. pg_try_advisory_xact_lock(hashtext(tenant_id || queue_key)) prevents two workers
       from concurrently claiming from the same queue_key.
    """
    wid = worker_id or f"worker_{uuid.uuid4().hex[:8]}"

    # Find candidate lowest-seq pending job across unlocked queues
    cur.execute(
        """
        SELECT j.id, j.queue_key, j.seq, j.ref_doc_no, j.payload, j.attempts, j.max_attempts, j.erp_doc_id
        FROM field.posting_job j
        WHERE j.tenant_id = %s
          AND j.status = 'pending'
          AND j.next_attempt_at <= NOW()
          AND NOT EXISTS (
              -- Predecessors must be completed or cancelled
              SELECT 1 FROM field.posting_job p
              WHERE p.tenant_id = j.tenant_id
                AND p.queue_key = j.queue_key
                AND p.seq < j.seq
                AND p.status NOT IN ('completed', 'cancelled')
          )
          AND NOT EXISTS (
              -- No currently active running job in the same queue
              SELECT 1 FROM field.posting_job r
              WHERE r.tenant_id = j.tenant_id
                AND r.queue_key = j.queue_key
                AND r.status = 'running'
                AND (r.locked_until IS NULL OR r.locked_until > NOW())
          )
          AND NOT EXISTS (
              -- No failed job in the same queue (failed job blocks later jobs per BR3.14)
              SELECT 1 FROM field.posting_job f
              WHERE f.tenant_id = j.tenant_id
                AND f.queue_key = j.queue_key
                AND f.status = 'failed'
          )
        ORDER BY j.seq ASC, j.created_at ASC
        FOR UPDATE OF j SKIP LOCKED
        LIMIT 10;
    """,
        (tenant_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return None

    for row in rows:
        j_id, q_key, seq, ref_doc, payload_raw, attempts, max_att = (
            str(row[0]),
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6] or MAX_ATTEMPTS,
        )
        erp_doc_id = str(row[7]) if len(row) > 7 and row[7] is not None else None

        # Attempt transactional advisory lock on queue_key
        lock_key_text = f"{tenant_id}:{q_key}"
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s));", (lock_key_text,))
        lock_row = cur.fetchone()
        got_lock = bool(lock_row[0]) if lock_row else False
        if not got_lock:
            continue

        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw

        # Lock and claim the job
        cur.execute(
            """
            UPDATE field.posting_job
            SET status = 'running',
                locked_by = %s,
                locked_until = NOW() + INTERVAL '30 seconds',
                attempts = attempts + 1,
                updated_at = NOW()
            WHERE id = %s;
        """,
            (wid, j_id),
        )

        return ClaimedJob(
            job_id=j_id,
            tenant_id=tenant_id,
            queue_key=q_key,
            seq=seq,
            ref_doc_no=ref_doc,
            payload=payload,
            attempts=attempts + 1,
            max_attempts=max_att,
            erp_doc_id=erp_doc_id,
        )

    return None


class PostingQueueWorker:
    """Worker service that claims and executes ordered posting jobs."""

    def __init__(self, erp_port: ErpPort, db_url: str = DATABASE_URL) -> None:
        self.erp_port = erp_port
        self.db_url = db_url
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"

    async def process_one_job(self, tenant_id: str) -> bool:
        """Claim and process one pending job. Returns True if a job was processed."""
        now = datetime.now(UTC)

        # 1. Claim job within transactional lock
        with psycopg.connect(self.db_url, autocommit=False) as conn, conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
            claimed = claim_next_job(cur, tenant_id, worker_id=self.worker_id)
            if not claimed:
                conn.rollback()
                return False
            conn.commit()

        payload = claimed.payload
        idem_key = payload.get("idempotency_key") or generate_idempotency_key()
        doc_family = payload["doc_family"]
        ref_doc_no = claimed.ref_doc_no or payload.get("ref_doc_no")

        # 2. Pre-post probe if retrying (attempts > 1)
        if claimed.attempts > 1:
            adopted = probe_sap_document(
                sap_client="100",
                doc_family=doc_family,
                ref_doc_no=str(ref_doc_no or ""),
                idempotency_key=idem_key,
            )
            if adopted:
                # Adopt document and mark completed
                with (
                    psycopg.connect(self.db_url, autocommit=False) as adopt_conn,
                    adopt_conn.cursor() as adopt_cur,
                ):
                    adopt_cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
                    adopt_cur.execute(
                        """
                            UPDATE field.posting_job
                            SET status = 'completed', locked_by = NULL, locked_until = NULL, updated_at = NOW()
                            WHERE id = %s;
                        """,
                        (claimed.job_id,),
                    )
                    emit_erp_posted(
                        adopt_cur,
                        tenant_id=tenant_id,
                        job_id=claimed.job_id,
                        doc_type=doc_family,
                        doc_no=adopted["document_number"],
                        doc_year=adopted["fiscal_year"],
                        movement_types=["101"],
                        queue_key=claimed.queue_key,
                        adopted_by_probe=True,
                    )
                    adopt_conn.commit()
                return True

        # 3. Dispatch to ERP
        post_req = ErpPostingRequest(
            idempotency_key=idem_key,
            doc_family=doc_family,
            site_id=payload.get("site_id", "WH1"),
            plant=payload.get("plant", "1010"),
            posting_date=now.strftime("%Y-%m-%d"),
            header_data=payload.get("header_data", {}),
            items=tuple(payload.get("items", [])),
        )

        try:
            if doc_family == "InboundDeliveryItem":
                erp_res = await self.erp_port.update_inbound_delivery_item(post_req)
            elif doc_family == "GoodsReceipt":
                erp_res = await self.erp_port.post_inbound_goods_receipt(post_req)
            elif doc_family == "OutboundDeliveryPick":
                erp_res = await self.erp_port.pick_outbound_delivery(post_req)
            elif doc_family == "GoodsIssue":
                erp_res = await self.erp_port.post_outbound_goods_issue(post_req)
            elif doc_family == "Cancellation":
                erp_res = await self.erp_port.cancel_material_document(post_req)
            elif doc_family == "PhysicalInventory":
                erp_res = await self.erp_port.post_physical_inventory_differences(post_req)
            elif doc_family == "Transfer":
                erp_res = await self.erp_port.post_transfer_posting(post_req)
            else:
                raise NotImplementedError(f"Unsupported doc family: {doc_family}")

            # Mark completed and emit erp.posted
            with (
                psycopg.connect(self.db_url, autocommit=False) as conn_done,
                conn_done.cursor() as cur_done,
            ):
                cur_done.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
                cur_done.execute(
                    """
                    UPDATE field.posting_job
                    SET status = 'completed', locked_by = NULL, locked_until = NULL, updated_at = NOW()
                    WHERE id = %s;
                """,
                    (claimed.job_id,),
                )
                if doc_family in FINAL_DOC_FAMILIES:
                    finalize_erp_document(cur_done, claimed, erp_res.document_number, erp_res.fiscal_year)
                    emit_erp_posted(
                        cur_done,
                        tenant_id=tenant_id,
                        job_id=claimed.job_id,
                        doc_type=doc_family,
                        doc_no=erp_res.document_number,
                        doc_year=erp_res.fiscal_year,
                        movement_types=[MOVEMENT_TYPES.get(doc_family, "")],
                        queue_key=claimed.queue_key,
                        adopted_by_probe=False,
                    )
                conn_done.commit()
            return True

        except Exception as exc:
            error_class, is_retryable, sap_msg = classify_error(exc)

            with (
                psycopg.connect(self.db_url, autocommit=False) as conn_err,
                conn_err.cursor() as cur_err,
            ):
                cur_err.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

                if not is_retryable or claimed.attempts >= claimed.max_attempts:
                    # Final failure -> status = 'failed'
                    cur_err.execute(
                        """
                        UPDATE field.posting_job
                        SET status = 'failed', locked_by = NULL, locked_until = NULL, updated_at = NOW()
                        WHERE id = %s;
                    """,
                        (claimed.job_id,),
                    )
                    emit_erp_failed(
                        cur_err,
                        tenant_id=tenant_id,
                        job_id=claimed.job_id,
                        queue_key=claimed.queue_key,
                        seq=claimed.seq,
                        attempts=claimed.attempts,
                        error_class=error_class,
                        sap_message=sap_msg,
                    )
                else:
                    # Retry with backoff + jitter
                    delay_s = compute_backoff_jitter(claimed.attempts)
                    next_at = datetime.now(UTC) + timedelta(seconds=delay_s)
                    cur_err.execute(
                        """
                        UPDATE field.posting_job
                        SET status = 'pending', locked_by = NULL, locked_until = NULL, next_attempt_at = %s, updated_at = NOW()
                        WHERE id = %s;
                    """,
                        (next_at, claimed.job_id),
                    )
                conn_err.commit()
            return True
