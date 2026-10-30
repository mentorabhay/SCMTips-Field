"""Goods Receipt Undo and Reversal Orchestrator (Task T3.023 / FR3.011 / PR3.01 / TC3.110).

Maps 'undo' after posting to a reversal erp_document (movement type 102).
Supports:
- Line-level reversal via CancelItem (reverses single item while other items remain posted).
- Document-level reversal via Cancel (reverses all items).
- Invariant PR3.01: Net stock delta across GR 101 and reversal 102 evaluates to zero.
"""

import json
import os
from typing import Any

import psycopg
from field_common.uuid7 import uuid7_str
from field_worker.posting import enqueue_posting_job

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def stage_goods_receipt_reversal(
    tenant_id: str,
    site_id: str,
    original_matdoc_no: str,
    fiscal_year: str = "2026",
    item_no: str | None = None,  # None = cancel whole document, str = cancel single item
    reason: str = "Undo receipt",
    plant: str = "1010",
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Create a reversal 102 erp_document and enqueue Cancel/CancelItem job."""
    queue_key = f"REV:{original_matdoc_no}"
    reversal_doc_id = uuid7_str()

    doc_family = "CancelItem" if item_no is not None else "Cancel"
    payload = {
        "original_material_document": original_matdoc_no,
        "fiscal_year": fiscal_year,
        "item_no": item_no,
        "movement_type": "102",
        "reason": reason,
    }

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

        cur.execute(
            """
            INSERT INTO field.erp_document (
                id, tenant_id, site_id, doc_type, status, doc_number, fiscal_year, movement_type, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'GoodsReceiptReversal', 'pending', %s, %s, '102', %s, NOW(), NOW());
            """,
            (
                reversal_doc_id,
                tenant_id,
                site_id,
                original_matdoc_no,
                fiscal_year,
                json.dumps(payload),
            ),
        )

    # Enqueue posting job for reversal
    job_id = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family=doc_family,
        site_id=site_id,
        plant=plant,
        header_data={
            "MaterialDocument": original_matdoc_no,
            "MaterialDocumentYear": fiscal_year,
            "PostingDate": "2026-10-27",
        },
        items=[{"MaterialDocumentItem": item_no}] if item_no is not None else [],
        seq=1,
        ref_doc_no=original_matdoc_no,
        db_url=db_url,
    )

    return {
        "status": "staged",
        "reversal_document_id": reversal_doc_id,
        "original_matdoc_no": original_matdoc_no,
        "is_partial": item_no is not None,
        "item_no": item_no,
        "queue_key": queue_key,
        "job_id": job_id,
    }
