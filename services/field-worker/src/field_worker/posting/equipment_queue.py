"""Per-Tower Equipment Posting Queue (Task T4.022 / FR4.036 / PR4.12).

Features:
- queue_key per tower functional location (e.g. EQUIP:IN01-TWR-0001-T01)
- Strictly monotonic per-tower seq ordering ensuring FIFO within the tower (PR4.12)
- Exponential backoff schedule: 2, 4, 8, 16, 32 s up to 8 attempts
- Attempt exhaustion triggers job status 'failed', outbox event 'erp.failed',
  and opens S2 exception_case in field.exception_case.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import structlog
from field_common.uuid7 import uuid7_str
from field_sap.equipment import SAPEquipmentAdapter

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

TOWER_MAX_ATTEMPTS = 8
TOWER_BACKOFF_SCHEDULE = [2, 4, 8, 16, 32, 32, 32, 32]


def compute_tower_backoff(attempt: int) -> int:
    """Return exponential backoff delay in seconds for given attempt number (1-indexed)."""
    idx = max(0, min(attempt - 1, len(TOWER_BACKOFF_SCHEDULE) - 1))
    return TOWER_BACKOFF_SCHEDULE[idx]


def enqueue_tower_equipment_job(
    tenant_id: str,
    site_id: str,
    tower_fl: str,
    operation: str,  # 'install' or 'dismantle'
    equipment_no: str,
    serial_no: str,
    material: str,
    target_fl: str,
    idempotency_key: str | None = None,
    explicit_seq: int | None = None,
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Enqueue an ordered equipment posting job in field.posting_job (API4.08 / T4.022)."""
    queue_key = f"EQUIP:{tower_fl}"
    job_id = uuid7_str()
    idem_key = idempotency_key or f"idem-eq-{uuid7_str()}"

    payload = {
        "site_id": site_id,
        "operation": operation,
        "equipment_no": equipment_no,
        "serial_no": serial_no,
        "material": material,
        "tower_fl": tower_fl,
        "target_fl": target_fl,
        "idempotency_key": idem_key,
    }

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Monotonic sequence allocation per (tenant_id, queue_key)
            if explicit_seq is not None:
                seq = explicit_seq
            else:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(seq), 0) + 1
                    FROM field.posting_job
                    WHERE tenant_id = %s AND queue_key = %s;
                    """,
                    (tenant_id, queue_key),
                )
                seq_row = cur.fetchone()
                seq = seq_row[0] if seq_row else 1

            cur.execute(
                """
                INSERT INTO field.posting_job (
                    id, tenant_id, queue_key, seq, status, payload, ref_doc_no,
                    attempts, next_attempt_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, 'pending', %s, %s,
                    0, NOW(), NOW(), NOW()
                )
                RETURNING id, seq;
                """,
                (
                    job_id,
                    tenant_id,
                    queue_key,
                    seq,
                    json.dumps(payload),
                    equipment_no,
                ),
            )
            row = cur.fetchone()

        conn.commit()

    return {
        "job_id": str(row[0]) if row else str(job_id),
        "queue_key": queue_key,
        "seq": row[1] if row else seq,
        "idempotency_key": idem_key,
        "status": "pending",
    }


def process_next_tower_job(
    tenant_id: str,
    queue_key: str,
    adapter: Any = None,
    db_url: str = DATABASE_URL,
    ignore_backoff: bool = True,
) -> dict[str, Any] | None:
    """Process the single next pending job in sequence order for the tower queue (PR4.12)."""
    now = datetime.now(UTC)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Check if queue is held due to conflict (TC4.152 / PR4.12)
            cur.execute(
                """
                SELECT conflict_reason FROM field.queue_hold
                WHERE tenant_id = %s AND queue_key = %s AND is_held = true;
                """,
                (tenant_id, queue_key),
            )
            hold_row = cur.fetchone()
            if hold_row:
                return {"status": "held", "queue_key": queue_key, "reason": hold_row[0]}

            # 1. Claim next pending job with earliest seq
            cur.execute(
                """
                SELECT id, seq, payload, attempts
                FROM field.posting_job
                WHERE tenant_id = %s AND queue_key = %s AND status = 'pending'
                  AND (%s OR next_attempt_at <= NOW())
                ORDER BY seq ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
                """,
                (tenant_id, queue_key, ignore_backoff),
            )
            job_row = cur.fetchone()
            if not job_row:
                return None

            job_id, seq, raw_payload, attempts = job_row
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            op = payload.get("operation")
            eq_no = payload.get("equipment_no")
            target_fl = payload.get("target_fl")
            idem_key = payload.get("idempotency_key")
            site_id = payload.get("site_id")

            try:
                # 2. Post through the SAP equipment adapter (erp-sim or S/4 per config). C4: when no
                # adapter was passed the job used to be marked completed with a fabricated change
                # document and an erp.posted event, without any ERP call.
                port = adapter if adapter is not None else SAPEquipmentAdapter()
                if not isinstance(eq_no, str) or not eq_no:
                    raise ValueError("tower job payload lacks equipment_no")
                if op == "install":
                    if not isinstance(target_fl, str) or not target_fl:
                        raise ValueError("install job payload lacks target_fl")
                    res = port.install_equipment(eq_no, target_fl, idempotency_key=idem_key)
                elif op == "dismantle":
                    res = port.dismantle_equipment(eq_no, idempotency_key=idem_key)
                else:
                    raise ValueError(f"unknown tower equipment operation {op!r}")
                change_doc = res.get("change_document")
                if not change_doc:
                    raise RuntimeError("ERP returned no change document; not marking the job posted")

                # Success: update posting_job to completed
                cur.execute(
                    """
                    UPDATE field.posting_job
                    SET status = 'completed',
                        attempts = attempts + 1,
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (job_id,),
                )

                # Emit erp.posted
                event_payload = {
                    "job_id": str(job_id),
                    "queue_key": queue_key,
                    "seq": seq,
                    "operation": op,
                    "equipment_no": eq_no,
                    "change_document": change_doc,
                    "posted_at": now.isoformat(),
                }
                cur.execute(
                    """
                    INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                    VALUES (%s, %s, %s, 'erp.posted', %s);
                    """,
                    (str(uuid.uuid4()), tenant_id, str(job_id), json.dumps(event_payload)),
                )
                conn.commit()

                return {
                    "job_id": str(job_id),
                    "status": "completed",
                    "change_doc": change_doc,
                    "seq": seq,
                }

            except Exception as e:
                new_attempts = attempts + 1
                if new_attempts >= TOWER_MAX_ATTEMPTS:
                    # Attempt exhaustion: fail job, emit erp.failed, open S2 exception case
                    cur.execute(
                        """
                        UPDATE field.posting_job
                        SET status = 'failed',
                            attempts = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (new_attempts, job_id),
                    )

                    # Emit erp.failed event
                    err_event = {
                        "job_id": str(job_id),
                        "queue_key": queue_key,
                        "seq": seq,
                        "error": str(e),
                        "attempts": new_attempts,
                    }
                    cur.execute(
                        """
                        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                        VALUES (%s, %s, %s, 'erp.failed', %s);
                        """,
                        (str(uuid.uuid4()), tenant_id, str(job_id), json.dumps(err_event)),
                    )

                    # Open S2 exception case. In a savepoint: if it cannot be opened (e.g. the site was
                    # deleted), the job must still end as failed instead of retrying forever.
                    if site_id:
                        try:
                            with conn.transaction():
                                dedupe_key = f"{site_id}:{queue_key}:posting_exhausted"
                                case_id = str(uuid.uuid4())
                                subject_data = {"queue_key": queue_key, "job_id": str(job_id), "seq": seq}
                                fact_data = {"error": str(e), "attempts": new_attempts}

                                cur.execute(
                                    """
                                    INSERT INTO field.exception_case (
                                        id, tenant_id, site_id, type, dedupe_key,
                                        status, severity, subject, facts, rule_id, version
                                    ) VALUES (
                                        %s, %s, %s, 'tower_posting_failed', %s,
                                        'open', 'S2', %s, %s, 'RULE-EQUIP-QUEUE-001', 1
                                    )
                                    ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'closed'
                                    DO NOTHING;
                                    """,
                                    (
                                        case_id,
                                        tenant_id,
                                        site_id,
                                        dedupe_key,
                                        json.dumps(subject_data),
                                        json.dumps(fact_data),
                                    ),
                                )
                        except psycopg.Error:
                            logger.exception("tower_exception_case_failed", job_id=str(job_id), site_id=str(site_id))
                    conn.commit()

                    return {
                        "job_id": str(job_id),
                        "status": "failed",
                        "attempts": new_attempts,
                        "error": str(e),
                        "seq": seq,
                    }
                else:
                    # Retry with exponential backoff
                    delay_s = compute_tower_backoff(new_attempts)
                    next_run = now + timedelta(seconds=delay_s)
                    cur.execute(
                        """
                        UPDATE field.posting_job
                        SET attempts = %s,
                            next_attempt_at = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (new_attempts, next_run, job_id),
                    )
                    conn.commit()

                    return {
                        "job_id": str(job_id),
                        "status": "pending",
                        "attempts": new_attempts,
                        "retry_delay_s": delay_s,
                        "seq": seq,
                    }
