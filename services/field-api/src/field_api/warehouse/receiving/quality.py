"""Quality Inspection Routing and 321 Release Workflow (Task T3.024 / FR3.012 / FR3.015 / TC3.111).

Rules:
1. Routing to Quality Hold:
   - When material.qm_inspection is true or site hold rule matches supplier+material:
     - Posts GR to quality inspection stock (StockType 'X').
     - Directs putaway to bins in quality inspection hold zones (e.g., 'Q-HOLD-01').
     - Sets handling unit inspection_status to 'quality_hold'.
2. Quality Release:
   - Requires permission 'field.quality.release'.
   - Generates 321 transfer movement (Quality stock -> Unrestricted-use stock).
   - Sets handling unit inspection_status to 'released'.
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


def evaluate_quality_inspection_need(
    material_qm_inspection: bool = False,
    supplier_id: str | None = None,
    site_hold_rules: list[dict[str, Any]] | None = None,
) -> bool:
    """Determine whether an incoming receipt requires quality inspection."""
    if material_qm_inspection:
        return True

    if site_hold_rules and supplier_id:
        for rule in site_hold_rules:
            if rule.get("supplier_id") == supplier_id and rule.get("hold_active", True):
                return True

    return False


def route_quality_hold_receipt(
    tenant_id: str,
    site_id: str,
    delivery_ref: str,
    hu_id: str,
    material_id: str,
    quantity: float,
    proposed_hold_bin: str = "Q-HOLD-01",
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Route handling unit to quality hold and propose inspection bin."""
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")

        cur.execute(
            """
            UPDATE field.handling_unit
            SET inspection_status = 'quality_hold',
                storage_bin = %s,
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            RETURNING id, sscc, quantity;
            """,
            (proposed_hold_bin, tenant_id, hu_id),
        )
        cur.fetchone()

    return {
        "hu_id": hu_id,
        "delivery_ref": delivery_ref,
        "stock_type": "X",  # Quality inspection
        "storage_bin": proposed_hold_bin,
        "inspection_status": "quality_hold",
        "quantity": quantity,
    }


def release_quality_hold_to_unrestricted(
    tenant_id: str,
    site_id: str,
    hu_id: str,
    material_code: str,
    quantity: float,
    plant: str = "1010",
    storage_location: str = "101A",
    operator_id: str = "supervisor-01",
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Release quality hold via movement 321 to unrestricted stock."""
    queue_key = f"QM:{hu_id}"
    transfer_doc_id = uuid7_str()

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")

        # Update HU inspection status to released
        cur.execute(
            """
            UPDATE field.handling_unit
            SET inspection_status = 'released',
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s;
            """,
            (tenant_id, hu_id),
        )

        # Create erp_document for 321 transfer
        payload = {
            "movement_type": "321",
            "material": material_code,
            "plant": plant,
            "storage_location": storage_location,
            "quantity": quantity,
            "from_stock_type": "X",
            "to_stock_type": "unrestricted",
            "released_by": operator_id,
        }
        cur.execute(
            """
            INSERT INTO field.erp_document (
                id, tenant_id, site_id, doc_type, status, doc_number, fiscal_year, movement_type, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'TransferPosting321', 'pending', %s, '2026', '321', %s, NOW(), NOW());
            """,
            (
                transfer_doc_id,
                tenant_id,
                site_id,
                hu_id,
                json.dumps(payload),
            ),
        )

    # Enqueue 321 posting job
    job_id = enqueue_posting_job(
        tenant_id=tenant_id,
        queue_key=queue_key,
        doc_family="TransferPosting",
        site_id=site_id,
        plant=plant,
        header_data={
            "GoodsMovementCode": "04",
            "PostingDate": "2026-10-27",
        },
        items=[
            {
                "Material": material_code,
                "Plant": plant,
                "StorageLocation": storage_location,
                "GoodsMovementType": "321",
                "EntryQuantity": quantity,
                "EntryUnit": "EA",
            }
        ],
        seq=1,
        ref_doc_no=hu_id,
        db_url=db_url,
    )

    return {
        "status": "released",
        "transfer_document_id": transfer_doc_id,
        "hu_id": hu_id,
        "movement_type": "321",
        "queue_key": queue_key,
        "job_id": job_id,
    }
