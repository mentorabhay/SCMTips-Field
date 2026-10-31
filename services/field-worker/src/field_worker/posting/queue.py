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
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import psycopg
import structlog
from field_common.bin_stock import change_stock
from field_common.uuid7 import uuid7_str
from field_sap.ports.erp_port import ErpPort, ErpPostingRequest

from field_worker.posting.events import emit_erp_failed, emit_erp_posted, notify_device
from field_worker.posting.idempotency import generate_idempotency_key
from field_worker.posting.retry import (
    MAX_ATTEMPTS,
    classify_error,
    compute_backoff_jitter,
)
from field_worker.warehouse.putaway_tasks import create_putaway_task

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_WORKER_DATABASE_URL",
        "postgresql://field_worker:devpassword@127.0.0.1:5450/field",
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
FINAL_DOC_FAMILIES = frozenset({"GoodsReceipt", "GoodsIssue", "Cancellation", "PhysicalInventory", "Transfer",
                                "InitialStockEntry"})
MOVEMENT_TYPES = MappingProxyType(
    {"GoodsReceipt": "101", "GoodsIssue": "601", "PhysicalInventory": "701/702", "Transfer": "311",
     "InitialStockEntry": "561"}
)


def finalize_erp_document(cur: psycopg.Cursor[Any], job: ClaimedJob, doc_no: str, doc_year: str | int) -> None:
    """Write the ERP document number back and close the task lines it posted (C4).

    erp_document.payload carries ``task_id``, ``line_ids`` and, for reversals, ``reverses``
    (the original erp_document id) and ``line_status_after``. After a goods receipt the put-away
    task is created; after a goods issue or a PI difference the field bin stock follows
    (M2 jobs contract §4).
    """
    if not job.erp_doc_id:
        return
    cur.execute(
        """
        UPDATE field.erp_document
           SET status = 'posted', doc_number = %s, fiscal_year = %s, version = version + 1, updated_at = NOW()
         WHERE id = %s
     RETURNING payload, doc_type, site_id, tenant_id
        """,
        (str(doc_no) or None, str(doc_year), job.erp_doc_id),
    )
    row = cur.fetchone()
    if not row:
        return
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    doc_type, site_id, tenant_id = row[1], str(row[2]), str(row[3])
    line_ids = payload.get("line_ids") or []
    reverses = payload.get("reverses")
    if reverses:
        cur.execute(
            "UPDATE field.erp_document SET status = 'reversed', updated_at = NOW() WHERE id = %s",
            (reverses,),
        )
    notify_device(cur, job.tenant_id, job.erp_doc_id, "erp.posted",
                  {"doc_number": str(doc_no), "doc_year": str(doc_year), "fiscal_year": str(doc_year),
                   "doc_type": doc_type, "reversal": bool(reverses)})
    if doc_type == "GI":
        apply_goods_issue_to_bins(cur, tenant_id, site_id, line_ids)
    elif doc_type == "INIT_STOCK":  # M3 sandbox count: opening stock (561) for items with no book stock
        apply_count_to_bins(cur, tenant_id, site_id, line_ids)
        if payload.get("pi_document_id") and payload.get("closes_pi"):
            cur.execute("UPDATE field.pi_document SET status = 'posted', difference_doc_no = %s, closed_at = NOW()"
                        " WHERE id = %s", (str(doc_no), payload["pi_document_id"]))
    elif doc_type == "PI_DIFF":
        apply_count_to_bins(cur, tenant_id, site_id, line_ids)
        if payload.get("pi_document_id"):
            cur.execute(
                "UPDATE field.pi_document SET status = 'posted', difference_doc_no = %s, closed_at = NOW()"
                " WHERE id = %s",
                (str(doc_no), payload["pi_document_id"]),
            )
    line_status = payload.get("line_status_after", "posted")
    task_id = payload.get("task_id") if payload.get("updates_task", True) else None
    if line_ids:
        cur.execute(
            "UPDATE field.task_line SET status = %s, version = version + 1, updated_at = NOW() WHERE id = ANY(%s::uuid[])",
            (line_status, line_ids),
        )
    if task_id:
        cur.execute(
            """
            UPDATE field.task t SET status = CASE
                     WHEN NOT EXISTS (SELECT 1 FROM field.task_line l
                                       WHERE l.task_id = t.id AND l.status NOT IN ('posted', 'cancelled', 'done'))
                     THEN 'completed' ELSE 'in_progress' END,
                   version = version + 1, updated_at = NOW()
             WHERE t.id = %s
            """,
            (task_id,),
        )
    if doc_type == "GR" and not reverses:
        created = create_putaway_task(cur, tenant_id, payload, str(doc_no))
        if created:
            notify_device(cur, job.tenant_id, job.erp_doc_id, "task.assigned",
                          {"task_id": created[0], "type": "putaway", "title": created[1]})


def mark_erp_document_failed(cur: psycopg.Cursor[Any], erp_doc_id: str | None, message: str) -> None:
    """A posting that will not be retried: the document and its task show ``failed`` (contract §2)."""
    if not erp_doc_id:
        return
    cur.execute(
        "UPDATE field.erp_document SET status = 'failed', updated_at = NOW() WHERE id = %s AND status = 'pending'"
        " RETURNING payload->>'task_id'",
        (erp_doc_id,),
    )
    row = cur.fetchone()
    if row and row[0]:
        cur.execute("UPDATE field.task SET status = 'failed', version = version + 1, updated_at = NOW()"
                    " WHERE id = %s", (row[0],))


def apply_goods_issue_to_bins(cur: psycopg.Cursor[Any], tenant_id: str, site_id: str, line_ids: list[str]) -> None:
    """A posted goods issue takes the picked quantity out of each pick line's bin."""
    if not line_ids:
        return
    cur.execute(
        "SELECT l.storage_bin, m.erp_material_no, l.picked_qty, l.uom FROM field.task_line l"
        " LEFT JOIN field.material m ON m.id = l.material_id WHERE l.id = ANY(%s::uuid[]) AND l.storage_bin IS NOT NULL",
        (line_ids,),
    )
    for bin_, mat, qty, uom in cur.fetchall():
        if mat:
            change_stock(cur, tenant_id=tenant_id, site_id=site_id, storage_bin=bin_, material_no=mat,
                         delta=-Decimal(qty), uom=uom)


def apply_count_to_bins(cur: psycopg.Cursor[Any], tenant_id: str, site_id: str, line_ids: list[str]) -> None:
    """A posted PI difference: the bin now holds what was counted."""
    if not line_ids:
        return
    cur.execute(
        "SELECT l.storage_bin, m.erp_material_no, l.counted_qty, l.uom, l.material_id FROM field.task_line l"
        " LEFT JOIN field.material m ON m.id = l.material_id WHERE l.id = ANY(%s::uuid[]) AND l.storage_bin IS NOT NULL",
        (line_ids,),
    )
    for bin_, mat, qty, uom, mat_id in cur.fetchall():
        if mat:
            change_stock(cur, tenant_id=tenant_id, site_id=site_id, storage_bin=bin_, material_no=mat,
                         set_to=Decimal(qty), uom=uom, material_id=str(mat_id) if mat_id else None)


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
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))
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
          AND j.queue_key NOT LIKE 'EQUIP:%%'  -- tower equipment queues have their own processor
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

    async def _post_physical_inventory(self, job: ClaimedJob, req: ErpPostingRequest) -> Any:
        """SAP sequence: create PI doc (once) -> enter every count -> post differences (701/702).

        The ERP PI number is persisted into the job payload right after creation, so a retry never
        creates a second ERP document.
        """
        hdr = dict(req.header_data)
        erp_pi = hdr.get("ErpPhysicalInventoryDocument")
        year = hdr.get("FiscalYear", str(datetime.now(UTC).year))
        if not erp_pi:
            created = await self.erp_port.create_physical_inventory_doc(
                ErpPostingRequest(
                    idempotency_key=f"{req.idempotency_key}:create", doc_family="PhysicalInventoryCreate",
                    site_id=req.site_id, plant=req.plant, posting_date=req.posting_date,
                    header_data={
                        "Plant": req.plant, "StorageLocation": hdr.get("StorageLocation", ""),
                        "PhysicalInventoryDocumentFiscalYear": year, "PostingBlocked": True,
                        "FreezeBookInventory": True,
                        "YY1_FieldSandbox": bool(hdr.get("Sandbox")), "YY1_FieldSimulated": bool(hdr.get("Simulated")),
                        "to_PhysicalInventoryDocItem": [
                            {"Material": it["Material"], "Plant": req.plant,
                             "StorageLocation": hdr.get("StorageLocation", "")}
                            for it in req.items
                        ],
                    },
                    items=(),
                )
            )
            erp_pi = created.document_number
            payload = {**job.payload, "header_data": {**hdr, "ErpPhysicalInventoryDocument": erp_pi}}
            with psycopg.connect(self.db_url, autocommit=True) as c, c.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(job.tenant_id),))
                cur.execute("UPDATE field.posting_job SET payload = %s WHERE id = %s", (json.dumps(payload), job.job_id))
        for n, it in enumerate(req.items, start=1):
            await self.erp_port.enter_physical_inventory_count(
                ErpPostingRequest(
                    idempotency_key=f"{req.idempotency_key}:count:{n}", doc_family="PhysicalInventoryCount",
                    site_id=req.site_id, plant=req.plant, posting_date=req.posting_date,
                    header_data={"PhysicalInventoryDocument": erp_pi, "FiscalYear": year, "LineNo": n,
                                 "QuantityInEntryUnit": it["QuantityInUnitOfEntry"],
                                 "EntryUnit": it.get("UnitOfEntry", "EA")},
                    items=(),
                )
            )
        return await self.erp_port.post_physical_inventory_differences(
            ErpPostingRequest(
                idempotency_key=req.idempotency_key, doc_family="PhysicalInventory", site_id=req.site_id,
                plant=req.plant, posting_date=req.posting_date,
                header_data={"PhysicalInventoryDocument": erp_pi, "FiscalYear": year}, items=(),
            )
        )

    async def process_one_job(self, tenant_id: str) -> bool:
        """Claim and process one pending job. Returns True if a job was processed."""
        now = datetime.now(UTC)

        # 1. Claim job within transactional lock
        with psycopg.connect(self.db_url, autocommit=False) as conn, conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))
            claimed = claim_next_job(cur, tenant_id, worker_id=self.worker_id)
            if not claimed:
                conn.rollback()
                return False
            conn.commit()

        payload = claimed.payload
        idem_key = payload.get("idempotency_key") or generate_idempotency_key()
        doc_family = payload["doc_family"]

        # 2. Pre-post probe if retrying (attempts > 1): a timed-out call may have posted (FR3.041).
        #    Asked through the ErpPort (header text FIELD:<key>), so it works for erp-sim and S/4 alike.
        if claimed.attempts > 1 and doc_family in FINAL_DOC_FAMILIES:
            try:
                adopted = await self.erp_port.find_by_idempotency_key(idem_key)
            except Exception:
                adopted = None  # probe failed: fall through to the (idempotent) post
            if adopted:
                with (
                    psycopg.connect(self.db_url, autocommit=False) as adopt_conn,
                    adopt_conn.cursor() as adopt_cur,
                ):
                    adopt_cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))
                    adopt_cur.execute(
                        """
                            UPDATE field.posting_job
                            SET status = 'completed', locked_by = NULL, locked_until = NULL, last_error = NULL, updated_at = NOW()
                            WHERE id = %s;
                        """,
                        (claimed.job_id,),
                    )
                    finalize_erp_document(adopt_cur, claimed, adopted.document_number, adopted.fiscal_year)
                    emit_erp_posted(
                        adopt_cur,
                        tenant_id=tenant_id,
                        job_id=claimed.job_id,
                        doc_type=doc_family,
                        doc_no=adopted.document_number,
                        doc_year=adopted.fiscal_year,
                        movement_types=[MOVEMENT_TYPES.get(doc_family, "")],
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
                erp_res = await self._post_physical_inventory(claimed, post_req)
            elif doc_family == "Transfer":
                erp_res = await self.erp_port.post_transfer_posting(post_req)
            elif doc_family == "InitialStockEntry":
                erp_res = await self.erp_port.post_initial_stock_entry(post_req)
            else:
                raise NotImplementedError(f"Unsupported doc family: {doc_family}")

            # Mark completed and emit erp.posted
            with (
                psycopg.connect(self.db_url, autocommit=False) as conn_done,
                conn_done.cursor() as cur_done,
            ):
                cur_done.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))
                cur_done.execute(
                    """
                    UPDATE field.posting_job
                    SET status = 'completed', locked_by = NULL, locked_until = NULL, last_error = NULL, updated_at = NOW()
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
                cur_err.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))

                if not is_retryable or claimed.attempts >= claimed.max_attempts:
                    # Final failure -> status = 'failed'
                    cur_err.execute(
                        """
                        UPDATE field.posting_job
                        SET status = 'failed', locked_by = NULL, locked_until = NULL, last_error = %s, updated_at = NOW()
                        WHERE id = %s;
                    """,
                        (sap_msg, claimed.job_id),
                    )
                    notify_device(cur_err, tenant_id, claimed.erp_doc_id, "erp.failed",
                                  {"error_class": error_class, "message": sap_msg})
                    mark_erp_document_failed(cur_err, claimed.erp_doc_id, sap_msg)
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
                        SET status = 'pending', locked_by = NULL, locked_until = NULL, next_attempt_at = %s,
                            last_error = %s, updated_at = NOW()
                        WHERE id = %s;
                    """,
                        (next_at, sap_msg, claimed.job_id),
                    )
                conn_err.commit()
            return True
