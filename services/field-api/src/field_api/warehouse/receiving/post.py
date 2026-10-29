"""Goods Receipt Staging and Posting Orchestrator (Task T3.022 / FR3.010 / TC3.109).

On confirm:
1. Creates field.erp_document with doc_type 'GR' (mvt 101).
2. Builds ordered posting jobs in queue IBD:<delivery>:
   - Seq 1..N: PATCH ActualDeliveryQuantity per line item.
   - Seq N+1: PostGoodsReceipt for the delivery.
3. Enqueues jobs into field.posting_job using ordered claim semantics.
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


def stage_and_post_goods_receipt(
    tenant_id: str,
    site_id: str,
    delivery_document: str,
    items: list[dict[str, Any]],  # [{item_no, actual_qty, storage_bin, stock_type}]
    plant: str = "1010",
    storage_location: str = "101A",
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Stage goods receipt into field.erp_document and enqueue ordered posting jobs."""
    queue_key = f"IBD:{delivery_document}"
    erp_doc_id = uuid7_str()

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")

        # 1. Create erp_document tracking row
        cur.execute(
            """
            INSERT INTO field.erp_document (
                id, tenant_id, site_id, doc_type, status, doc_number, fiscal_year, movement_type, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'GoodsReceipt', 'pending', %s, '2026', '101', %s, NOW(), NOW());
            """,
            (
                erp_doc_id,
                tenant_id,
                site_id,
                delivery_document,
                json.dumps(
                    {
                        "delivery_document": delivery_document,
                        "plant": plant,
                        "storage_location": storage_location,
                        "items": items,
                    }
                ),
            ),
        )

    # 2. Build ordered posting jobs
    job_ids = []
    current_seq = 1

    # Stage item quantity patches
    for it in items:
        item_no = str(it.get("item_no", "000010")).zfill(6)
        qty = it.get("actual_qty", 0.0)
        bin_code = it.get("storage_bin")

        patch_job_id = enqueue_posting_job(
            tenant_id=tenant_id,
            queue_key=queue_key,
            doc_family="InboundDeliveryItem",
            site_id=site_id,
            plant=plant,
            header_data={
                "delivery_document": delivery_document,
                "item_no": item_no,
            },
            items=[
                {
                    "item_no": item_no,
                    "ActualDeliveryQuantity": qty,
                    "StorageBin": bin_code,
                }
            ],
            seq=current_seq,
            ref_doc_no=delivery_document,
            db_url=db_url,
        )
        job_ids.append(patch_job_id)
        current_seq += 1

    # Stage PostGoodsReceipt job
    pgr_job_id = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="GoodsReceipt",
        site_id=site_id,
        plant=plant,
        header_data={
            "DeliveryDocument": delivery_document,
            "PostingDate": "2026-10-27",
        },
        items=items,
        seq=current_seq,
        ref_doc_no=delivery_document,
        db_url=db_url,
    )
    job_ids.append(pgr_job_id)

    return {
        "status": "staged",
        "erp_document_id": erp_doc_id,
        "delivery_document": delivery_document,
        "queue_key": queue_key,
        "job_ids": job_ids,
        "total_jobs": len(job_ids),
    }
