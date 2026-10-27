"""Outbox event emission for posting lifecycle (Task T3.014 / EV3.01 - EV3.04 / FR3.038 / FR3.064).

Emits:
- EV3.01: posting.requested
- EV3.02: erp.posted
- EV3.03: erp.reversed
- EV3.04: erp.failed
All written to field.outbox in the same transaction as state changes.
"""

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
from field_common.uuid7 import uuid7_str


def emit_posting_requested(
    cur: psycopg.Cursor[Any],
    tenant_id: str,
    job_id: str,
    queue_key: str,
    doc_type: str,
    jobs: list[dict[str, Any]],
    trace_id: str | None = None,
    subject: str | None = None,
) -> str:
    """EV3.01: Emit posting.requested event."""
    outbox_id = uuid7_str()
    payload = {
        "id": outbox_id,
        "type": "posting.requested",
        "tenant_id": tenant_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        "subject": subject or f"erp_document/{job_id}",
        "data": {
            "queue_key": queue_key,
            "doc_type": doc_type,
            "jobs": jobs,
        },
        "trace_id": trace_id or uuid7_str(),
    }
    cur.execute(
        """
        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
        VALUES (%s, %s, %s, 'posting.requested', %s);
    """,
        (outbox_id, tenant_id, job_id, json.dumps(payload)),
    )
    return outbox_id


def emit_erp_posted(
    cur: psycopg.Cursor[Any],
    tenant_id: str,
    job_id: str,
    doc_type: str,
    doc_no: str,
    doc_year: str | int,
    movement_types: list[str],
    queue_key: str,
    adopted_by_probe: bool = False,
    subject: str | None = None,
) -> str:
    """EV3.02: Emit erp.posted event."""
    outbox_id = uuid7_str()
    payload = {
        "id": outbox_id,
        "type": "erp.posted",
        "occurred_at": datetime.now(UTC).isoformat(),
        "subject": subject or f"erp_document/{job_id}",
        "data": {
            "doc_type": doc_type,
            "doc_no": str(doc_no),
            "doc_year": int(doc_year),
            "movement_types": movement_types,
            "queue_key": queue_key,
            "adopted_by_probe": adopted_by_probe,
        },
    }
    cur.execute(
        """
        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
        VALUES (%s, %s, %s, 'erp.posted', %s);
    """,
        (outbox_id, tenant_id, job_id, json.dumps(payload)),
    )
    return outbox_id


def emit_erp_reversed(
    cur: psycopg.Cursor[Any],
    tenant_id: str,
    job_id: str,
    doc_no: str,
    reverses: str,
    movement_types: list[str],
    items: list[str] | None = None,
) -> str:
    """EV3.03: Emit erp.reversed event."""
    outbox_id = uuid7_str()
    payload = {
        "id": outbox_id,
        "type": "erp.reversed",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "doc_no": str(doc_no),
            "reverses": str(reverses),
            "movement_types": movement_types,
            "items": items or ["0001"],
        },
    }
    cur.execute(
        """
        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
        VALUES (%s, %s, %s, 'erp.reversed', %s);
    """,
        (outbox_id, tenant_id, job_id, json.dumps(payload)),
    )
    return outbox_id


def emit_erp_failed(
    cur: psycopg.Cursor[Any],
    tenant_id: str,
    job_id: str,
    queue_key: str,
    seq: int,
    attempts: int,
    error_class: str,
    sap_message: str,
) -> str:
    """EV3.04: Emit erp.failed event."""
    outbox_id = uuid7_str()
    payload = {
        "id": outbox_id,
        "type": "erp.failed",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "queue_key": queue_key,
            "seq": seq,
            "attempts": attempts,
            "error_class": error_class,
            "sap_message": sap_message,
        },
    }
    cur.execute(
        """
        INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
        VALUES (%s, %s, %s, 'erp.failed', %s);
    """,
        (outbox_id, tenant_id, job_id, json.dumps(payload)),
    )
    return outbox_id
