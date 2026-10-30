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
from field_api.equipment.history import append_serial_event
from field_common.uuid7 import uuid7_str
from field_sap.equipment import SAPEquipmentAdapter

from field_worker.posting.conflicts import check_and_handle_replay_conflict
from field_worker.posting.events import notify_device
from field_worker.posting.queue import mark_erp_document_failed

logger = structlog.get_logger(__name__)

# The worker role (NOBYPASSRLS), as posting/queue.py: RLS really applies. (Was the superuser.)
DATABASE_URL = (
    os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
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


def check_preconditions(port: Any, tenant_id: str, payload: dict[str, Any], db_url: str) -> str | None:
    """None when the ERP state allows the job, else the conflict reason (queue now held).

    dismantle: the unit must still be installed at ``expected_fl`` (the position the technician saw);
    install: the unit must not be installed somewhere else. Jobs without a precondition pass.
    """
    op = payload.get("operation")
    expected_fl = payload.get("expected_fl") if op == "dismantle" else payload.get("target_fl")
    if op not in ("dismantle", "install") or not expected_fl or not hasattr(port, "get_equipment"):
        return None
    if op == "dismantle":
        if not payload.get("equipment_no"):
            return None
        state = port.get_equipment(str(payload["equipment_no"]))
    else:
        if not payload.get("serial_no"):
            return None
        state = port.find_equipment_by_serial(str(payload["serial_no"]))
    if state is None:
        return None  # unknown unit: the post itself reports the ERP error
    erp_state = {"status": "installed" if state.get("current_fl") else "dismantled", "current_fl": state.get("current_fl")}
    res = check_and_handle_replay_conflict(
        tenant_id=tenant_id, site_id=str(payload.get("site_id")), tower_fl=str(payload.get("tower_fl")),
        equipment_no=str(state.get("equipment_no") or payload.get("equipment_no") or ""),
        serial_no=str(payload.get("serial_no") or ""), operation=str(op), expected_precondition_fl=str(expected_fl),
        current_erp_state=erp_state, db_url=db_url,
    )
    return str(res["reason"]) if res.get("conflict") else None


def finalize_tower_document(cur: psycopg.Cursor[Any], tenant_id: str, erp_doc_id: str, change_doc: str,
                            year: int) -> None:
    """Last job of a swap posted: document number, installed base, line and task, and the phone hears it."""
    cur.execute(
        "UPDATE field.erp_document SET status = 'posted', doc_number = %s, fiscal_year = %s, updated_at = NOW()"
        " WHERE id = %s RETURNING payload",
        (change_doc, str(year), erp_doc_id),
    )
    row = cur.fetchone()
    if not row:
        return
    p = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    loc = p.get("location_id")
    cur.execute("SELECT payload FROM field.posting_job WHERE erp_doc_id = %s ORDER BY seq", (erp_doc_id,))
    jobs = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in cur.fetchall()]
    for j in jobs:
        serial = j.get("serial_no")
        if not serial:
            continue
        if j.get("operation") == "dismantle":
            cur.execute("UPDATE field.equipment SET status = 'dismantled', current_location_id = NULL,"
                        " updated_at = NOW() WHERE serial_no = %s RETURNING id", (serial,))
            eq = cur.fetchone()
            append_serial_event(tenant_id=tenant_id, serial_no=serial, event_type="dismantle", location_id=loc,
                                equipment_id=str(eq[0]) if eq else None, idempotency_key=j.get("idempotency_key"),
                                cur=cur)
        elif j.get("operation") == "install":
            cur.execute(
                """
                INSERT INTO field.equipment (tenant_id, erp_equipment_no, serial_no, material, current_location_id, status)
                VALUES (%s, %s, %s, %s, %s, 'installed')
                ON CONFLICT (tenant_id, material, serial_no) DO UPDATE SET current_location_id = EXCLUDED.current_location_id,
                       status = 'installed', erp_equipment_no = EXCLUDED.erp_equipment_no, updated_at = NOW()
                RETURNING id
                """,
                (tenant_id, j.get("equipment_no"), serial, j.get("material") or "UNKNOWN", loc),
            )
            eq = cur.fetchone()
            append_serial_event(tenant_id=tenant_id, serial_no=serial, event_type="install", location_id=loc,
                                equipment_id=str(eq[0]) if eq else None, idempotency_key=j.get("idempotency_key"),
                                cur=cur)
    line_ids = p.get("line_ids") or []
    if line_ids:
        cur.execute("UPDATE field.task_line SET status = 'done', version = version + 1, updated_at = NOW()"
                    " WHERE id = ANY(%s::uuid[])", (line_ids,))
    if p.get("task_id"):
        cur.execute("UPDATE field.task SET status = 'completed', version = version + 1, updated_at = NOW()"
                    " WHERE id = %s", (p["task_id"],))
    notify_device(cur, tenant_id, erp_doc_id, "erp.posted",
                  {"doc_number": change_doc, "doc_year": str(year), "doc_type": "EQ_SWAP"})


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

            # 1. One poster per queue at a time. Two workers on the same tower would otherwise both
            #    claim jobs (FOR UPDATE SKIP LOCKED let a second worker post seq N+1 while seq N was
            #    still in flight), breaking per-tower order (PR4.12).
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (f"{tenant_id}|{queue_key}",))
            lock_row = cur.fetchone()
            if not lock_row or not lock_row[0]:
                return {"status": "busy", "queue_key": queue_key}

            # 2. Head of line: the lowest seq not yet completed. A later job never overtakes it, whether
            #    the head is waiting out a retry backoff or has failed for good (it then blocks the
            #    tower until it is resolved). Previously the query took the lowest *due* pending job,
            #    so a job in backoff or failed was silently skipped.
            cur.execute(
                """
                SELECT id, seq, payload, attempts, status, (%s OR next_attempt_at <= NOW()) AS due, erp_doc_id
                FROM field.posting_job
                WHERE tenant_id = %s AND queue_key = %s AND status NOT IN ('completed', 'cancelled')
                ORDER BY seq ASC
                LIMIT 1
                FOR UPDATE;
                """,
                (ignore_backoff, tenant_id, queue_key),
            )
            head = cur.fetchone()
            if not head:
                return None
            if head[4] == "failed":
                return {"status": "blocked", "queue_key": queue_key, "seq": head[1]}
            if head[4] != "pending" or not head[5]:
                return {"status": "waiting", "queue_key": queue_key, "seq": head[1]}
            job_row = head[:4]
            erp_doc_id = str(head[6]) if head[6] else None

            job_id, seq, raw_payload, attempts = job_row
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            op = payload.get("operation")
            eq_no = payload.get("equipment_no")
            target_fl = payload.get("target_fl")
            idem_key = payload.get("idempotency_key")
            site_id = payload.get("site_id")
            port = adapter if adapter is not None else SAPEquipmentAdapter()

            # 2a. Replay-conflict check (T4.064 / FR4.060): the job's precondition against the ERP state
            #     read through the SAP adapter. On conflict the tower queue is held and a case opened;
            #     the job stays pending until a supervisor releases the hold.
            conflict = check_preconditions(port, tenant_id, payload, db_url)
            if conflict:
                cur.execute("UPDATE field.posting_job SET last_error = %s WHERE id = %s", (f"held: {conflict}", job_id))
                conn.commit()
                return {"status": "held", "queue_key": queue_key, "seq": seq, "reason": conflict}

            try:
                # 2. Post through the SAP equipment adapter (erp-sim or S/4 per config). C4: when no
                # adapter was passed the job used to be marked completed with a fabricated change
                # document and an erp.posted event, without any ERP call.
                if (not isinstance(eq_no, str) or not eq_no) and op == "install" and payload.get("serial_no"):
                    # A swap's new unit: SAP knows it by serial; its equipment number is read now.
                    found = port.find_equipment_by_serial(str(payload["serial_no"]))
                    if not found or not found.get("equipment_no"):
                        raise ValueError(f"no ERP equipment carries serial {payload['serial_no']}")
                    eq_no = str(found["equipment_no"])
                    payload = {**payload, "equipment_no": eq_no, "material": found.get("material")
                               or payload.get("material")}
                    cur.execute("UPDATE field.posting_job SET payload = %s WHERE id = %s",
                                (json.dumps(payload), job_id))
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
                        last_error = NULL,
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
                if erp_doc_id and payload.get("final"):
                    finalize_tower_document(cur, tenant_id, erp_doc_id, str(change_doc), now.year)
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
                            last_error = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (new_attempts, str(e), job_id),
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
                    if erp_doc_id:
                        notify_device(cur, tenant_id, erp_doc_id, "erp.failed", {"message": str(e)})
                        mark_erp_document_failed(cur, erp_doc_id, str(e))

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
                            last_error = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (new_attempts, next_run, str(e), job_id),
                    )
                    conn.commit()

                    return {
                        "job_id": str(job_id),
                        "status": "pending",
                        "attempts": new_attempts,
                        "retry_delay_s": delay_s,
                        "seq": seq,
                    }
