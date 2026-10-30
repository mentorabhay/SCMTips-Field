"""Posting Queue Management Endpoints (Task T3.013 / FR3.045 / BR3.14).

Exposes:
- GET /v1/posting-queues: List queues with counts, blocked indicators, and min/max seq.
- GET /v1/posting-queues/{queue_key}/jobs: List all ordered jobs within a queue.
- POST /v1/posting-jobs/{id}/retry: Retry a failed or blocked job.
- POST /v1/posting-jobs/{id}/cancel: Cancel a job and its dependent successors per BR3.14.
"""

import json
import os
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel

from field_api.auth.jwt import Principal
from field_api.config import settings
from field_api.deps import require_permission

router = APIRouter(tags=["Posting Queues"])

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        settings.FIELD_DATABASE_URL,
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def get_db_conn() -> psycopg.Connection[Any]:
    return psycopg.connect(DATABASE_URL, autocommit=False)


class QueueSummary(BaseModel):
    queue_key: str
    pending_count: int
    running_count: int
    failed_count: int
    completed_count: int
    cancelled_count: int
    is_blocked: bool
    min_seq: int | None
    max_seq: int | None
    oldest_pending_at: str | None


class PostingJobRecord(BaseModel):
    id: str
    queue_key: str
    seq: int
    ref_doc_no: str | None
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: str | None
    payload: dict[str, Any]
    created_at: str
    updated_at: str


@router.get("/v1/posting-queues", response_model=list[QueueSummary])
async def list_posting_queues(
    principal: Principal = Depends(require_permission("field.queue.read")),
) -> list[QueueSummary]:
    """List posting queues with health status, failure counts, and blocking status."""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(principal.tenant_id),))
        cur.execute(
            """
            SELECT
                queue_key,
                count(*) FILTER (WHERE status = 'pending') AS pending_count,
                count(*) FILTER (WHERE status = 'running') AS running_count,
                count(*) FILTER (WHERE status = 'failed') AS failed_count,
                count(*) FILTER (WHERE status = 'completed') AS completed_count,
                count(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                bool_or(status = 'failed') AS is_blocked,
                min(seq) AS min_seq,
                max(seq) AS max_seq,
                min(created_at) FILTER (WHERE status = 'pending') AS oldest_pending_at
            FROM field.posting_job
            WHERE tenant_id = %s
            GROUP BY queue_key
            ORDER BY queue_key ASC;
        """,
            (principal.tenant_id,),
        )
        results = []
        for row in cur.fetchall():
            results.append(
                QueueSummary(
                    queue_key=row[0],
                    pending_count=row[1],
                    running_count=row[2],
                    failed_count=row[3],
                    completed_count=row[4],
                    cancelled_count=row[5],
                    is_blocked=bool(row[6]),
                    min_seq=row[7],
                    max_seq=row[8],
                    oldest_pending_at=row[9].isoformat() if row[9] else None,
                )
            )
        return results


@router.get("/v1/posting-queues/{queue_key}/jobs", response_model=list[PostingJobRecord])
async def list_queue_jobs(
    queue_key: str,
    principal: Principal = Depends(require_permission("field.queue.read")),
) -> list[PostingJobRecord]:
    """List jobs within a specific posting queue in sequence order."""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(principal.tenant_id),))
        cur.execute(
            """
            SELECT id, queue_key, seq, ref_doc_no, status, attempts, max_attempts, next_attempt_at, payload, created_at, updated_at
            FROM field.posting_job
            WHERE tenant_id = %s AND queue_key = %s
            ORDER BY seq ASC, created_at ASC;
        """,
            (principal.tenant_id, queue_key),
        )
        jobs = []
        for r in cur.fetchall():
            payload_data = r[8] if isinstance(r[8], dict) else json.loads(r[8] or "{}")
            jobs.append(
                PostingJobRecord(
                    id=str(r[0]),
                    queue_key=r[1],
                    seq=r[2],
                    ref_doc_no=r[3],
                    status=r[4],
                    attempts=r[5],
                    max_attempts=r[6],
                    next_attempt_at=r[7].isoformat() if r[7] else None,
                    payload=payload_data,
                    created_at=r[9].isoformat() if r[9] else "",
                    updated_at=r[10].isoformat() if r[10] else "",
                )
            )
        return jobs


@router.post("/v1/posting-jobs/{job_id}/retry")
async def retry_posting_job(
    job_id: str,
    principal: Principal = Depends(require_permission("field.queue.manage")),
) -> dict[str, Any]:
    """Retry a failed or blocked job immediately."""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(principal.tenant_id),))
        cur.execute(
            """
            SELECT id, status, queue_key, seq FROM field.posting_job
            WHERE tenant_id = %s AND id = %s;
        """,
            (principal.tenant_id, job_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Posting job not found")

        cur.execute(
            """
            UPDATE field.posting_job
            SET status = 'pending',
                next_attempt_at = NOW(),
                locked_by = NULL,
                locked_until = NULL,
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s;
        """,
            (principal.tenant_id, job_id),
        )

        # Audit retry
        outbox_id = uuid7_str()
        audit_payload = {
            "action": "posting_job.retry",
            "job_id": job_id,
            "operator_id": principal.id,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        cur.execute(
            """
            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, 'posting_job.retry', %s);
        """,
            (outbox_id, principal.tenant_id, job_id, json.dumps(audit_payload)),
        )
        conn.commit()

        return {"id": job_id, "status": "pending", "retried": True}


@router.post("/v1/posting-jobs/{job_id}/cancel")
async def cancel_posting_job(
    job_id: str,
    principal: Principal = Depends(require_permission("field.queue.manage")),
) -> dict[str, Any]:
    """Cancel a posting job and cascade cancel dependent subsequent jobs per BR3.14."""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(principal.tenant_id),))
        cur.execute(
            """
            SELECT id, status, queue_key, seq, ref_doc_no FROM field.posting_job
            WHERE tenant_id = %s AND id = %s;
        """,
            (principal.tenant_id, job_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Posting job not found")

        q_key, seq, ref_doc = row[2], row[3], row[4]

        # 1. Cancel target job
        cur.execute(
            """
            UPDATE field.posting_job
            SET status = 'cancelled',
                locked_by = NULL,
                locked_until = NULL,
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s;
        """,
            (principal.tenant_id, job_id),
        )

        # 2. BR3.14: Cancel dependent subsequent jobs on same ref_doc_no
        dependent_cancelled = []
        if ref_doc:
            cur.execute(
                """
                UPDATE field.posting_job
                SET status = 'cancelled',
                    locked_by = NULL,
                    locked_until = NULL,
                    updated_at = NOW()
                WHERE tenant_id = %s
                  AND queue_key = %s
                  AND ref_doc_no = %s
                  AND seq > %s
                  AND status IN ('pending', 'running')
                RETURNING id;
            """,
                (principal.tenant_id, q_key, ref_doc, seq),
            )
            dependent_cancelled = [str(r[0]) for r in cur.fetchall()]

        # Audit cancellation
        outbox_id = uuid7_str()
        audit_payload = {
            "action": "posting_job.cancel",
            "job_id": job_id,
            "dependent_cancelled": dependent_cancelled,
            "operator_id": principal.id,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        cur.execute(
            """
            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, 'posting_job.cancelled', %s);
        """,
            (outbox_id, principal.tenant_id, job_id, json.dumps(audit_payload)),
        )
        conn.commit()

        return {
            "id": job_id,
            "status": "cancelled",
            "cancelled": True,
            "dependent_cancelled_count": len(dependent_cancelled),
            "dependent_cancelled_ids": dependent_cancelled,
        }
