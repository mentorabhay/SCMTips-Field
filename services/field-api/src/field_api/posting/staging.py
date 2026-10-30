"""Stage an ERP document and its ordered posting jobs inside the caller's transaction (C4).

Replaces the pattern where the erp_document row and each posting job were written in separate
autocommit connections (a crash between them left orphans). Job payloads use the exact shape the
worker builds ``ErpPostingRequest`` from: idempotency_key, doc_family, site_id, plant,
header_data, items, seq, ref_doc_no.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg
from field_common.uuid7 import uuid7_str


@dataclass(frozen=True)
class JobSpec:
    doc_family: str
    header_data: dict[str, Any]
    items: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class StagedDocument:
    erp_document_id: str
    queue_key: str
    job_ids: tuple[str, ...]


def stage_document(
    cur: psycopg.Cursor[Any],
    *,
    tenant_id: str,
    site_id: str,
    doc_type: str,
    movement_type: str,
    queue_key: str,
    ref_doc_no: str | None,
    plant: str,
    payload: dict[str, Any],
    jobs: list[JobSpec],
    idempotency_key: str,
    reversal_of_id: str | None = None,
) -> StagedDocument:
    if not jobs:
        raise ValueError("a staged document needs at least one posting job")
    erp_doc_id = uuid7_str()
    cur.execute(
        """
        INSERT INTO field.erp_document
            (id, tenant_id, site_id, doc_type, movement_type, reversal_of_id, payload, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        """,
        (erp_doc_id, tenant_id, site_id, doc_type, movement_type, reversal_of_id, json.dumps(payload)),
    )
    # Serialise seq allocation per queue: no two confirms may interleave within a queue_key.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant_id}:{queue_key}",))
    cur.execute("SELECT COALESCE(MAX(seq), 0) FROM field.posting_job WHERE queue_key = %s", (queue_key,))
    row = cur.fetchone()
    seq = int(row[0]) if row else 0
    job_ids: list[str] = []
    for i, job in enumerate(jobs, start=1):
        seq += 1
        job_id = uuid7_str()
        job_payload = {
            # Deterministic per (request, step): a retried confirm re-uses the same ERP keys.
            "idempotency_key": f"{idempotency_key}:{i}",
            "doc_family": job.doc_family,
            "site_id": site_id,
            "plant": plant,
            "header_data": job.header_data,
            "items": list(job.items),
            "seq": seq,
            "ref_doc_no": ref_doc_no,
        }
        cur.execute(
            """
            INSERT INTO field.posting_job
                (id, tenant_id, erp_doc_id, queue_key, seq, ref_doc_no, payload, status, next_attempt_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
            """,
            (job_id, tenant_id, erp_doc_id, queue_key, seq, ref_doc_no, json.dumps(job_payload)),
        )
        job_ids.append(job_id)
    return StagedDocument(erp_doc_id, queue_key, tuple(job_ids))
