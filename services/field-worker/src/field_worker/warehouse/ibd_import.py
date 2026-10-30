"""Inbound Delivery Polling and Task Generation Worker (Task T3.016 / FR3.001 / FR3.003 / TC3.101 / TC3.103).

Polls A_InbDeliveryHeader/Item for site's plants and storage locations.
Upserts tasks by DeliveryDocument and LastChangeDateTime:
- Creates one 'receive' task per delivery with one task_line per item.
- Re-import creates no duplicates if LastChangeDateTime has not changed.
- If delivery changed in SAP: uncaptured lines update expected_qty; lines with captures
  remain unchanged and open a conflict case per TC3.103.
"""

import json
import os
from contextlib import suppress as contextlib_suppress
from datetime import datetime
from typing import Any

import httpx
import psycopg
import structlog
from field_common.uuid7 import uuid7_str

logger = structlog.get_logger(__name__)

# The worker role (NOBYPASSRLS), as posting/queue.py: RLS really applies. (Was the superuser.)
DATABASE_URL = (
    os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

ERP_SIM_URL = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")


async def poll_and_import_inbound_deliveries(
    tenant_id: str,
    site_id: str,
    plant: str,
    storage_locations: list[str] | None = None,
    erp_url: str = ERP_SIM_URL,
    db_url: str = DATABASE_URL,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Poll inbound deliveries for a plant/sloc and upsert receive tasks.

    Returns:
        (tasks_created, lines_created, conflicts)
    """
    filter_expr = f"ReceivingPlant eq '{plant}'"
    url = f"{erp_url}/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader"
    params = {
        "$filter": filter_expr,
        "$expand": "to_DeliveryDocumentItem",
    }
    headers = {"Accept": "application/json", "sap-client": "100"}

    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        should_close = True

    try:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            logger.warning("ibd_poll_failed", status=resp.status_code, text=resp.text)
            return 0, 0, []
        data = resp.json()
    finally:
        if should_close:
            await client.aclose()

    deliveries = data.get("d", {}).get("results", [])
    tasks_created = 0
    lines_created = 0
    conflicts: list[dict[str, Any]] = []

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (str(tenant_id),))

        for d in deliveries:
            deliv_doc = d.get("DeliveryDocument")
            if not deliv_doc:
                continue

            # Filter by storage location if provided
            sloc = d.get("StorageLocation")
            if storage_locations and sloc and sloc not in storage_locations:
                continue

            last_change_raw = d.get("LastChangeDateTime")
            last_change_dt: datetime | None = None
            if last_change_raw:
                with contextlib_suppress(Exception):
                    last_change_dt = datetime.fromisoformat(last_change_raw.replace("Z", "+00:00"))

            # Check if task already exists
            cur.execute(
                """
                SELECT id, last_change_at, status
                FROM field.task
                WHERE tenant_id = %s AND ref_doc_no = %s AND type = 'receive';
                """,
                (tenant_id, deliv_doc),
            )
            existing_task = cur.fetchone()

            items = d.get("to_DeliveryDocumentItem", {}).get("results", [])

            if not existing_task and d.get("OverallGoodsReceiptStatus") == "C":
                continue  # already fully received in the ERP: nothing to do in the field

            if not existing_task:
                # 1. Create new receive task
                task_id = uuid7_str()
                title = f"Receive {deliv_doc}"
                cur.execute(
                    """
                    INSERT INTO field.task (
                        id, tenant_id, site_id, type, status, priority, title,
                        ref_doc_no, last_change_at, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, 'receive', 'pending', 'normal', %s, %s, %s, NOW(), NOW());
                    """,
                    (task_id, tenant_id, site_id, title, deliv_doc, last_change_dt),
                )
                tasks_created += 1

                for item in items:
                    item_no = int(item.get("DeliveryDocumentItem", 10))
                    mat_no = item.get("Material", "")
                    expected_qty = float(item.get("ActualDeliveryQuantity", 0.0))
                    uom = item.get("DeliveryQuantityUnit", "EA")

                    # Resolve material_id from field.material or fallback to dummy/null
                    cur.execute(
                        "SELECT id FROM field.material WHERE tenant_id = %s AND erp_material_no = %s;",
                        (tenant_id, mat_no),
                    )
                    mat_row = cur.fetchone()
                    mat_id = mat_row[0] if mat_row else None

                    line_id = uuid7_str()
                    cur.execute(
                        """
                        INSERT INTO field.task_line (
                            id, tenant_id, site_id, task_id, line_no, material_id,
                            expected_qty, uom, captured_qty, counted_qty, status,
                            created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 'pending', NOW(), NOW());
                        """,
                        (line_id, tenant_id, site_id, task_id, item_no, mat_id, expected_qty, uom),
                    )
                    lines_created += 1

            else:
                task_id = existing_task[0]
                prev_last_change = existing_task[1]

                # If last_change_at has not changed, skip (idempotent, no duplicates)
                if last_change_dt and prev_last_change and last_change_dt <= prev_last_change:
                    continue

                # Delivery changed in SAP! Process items per TC3.103
                for item in items:
                    item_no = int(item.get("DeliveryDocumentItem", 10))
                    new_expected_qty = float(item.get("ActualDeliveryQuantity", 0.0))

                    cur.execute(
                        """
                        SELECT id, expected_qty, captured_qty, counted_qty, status
                        FROM field.task_line
                        WHERE tenant_id = %s AND task_id = %s AND line_no = %s;
                        """,
                        (tenant_id, task_id, item_no),
                    )
                    line_row = cur.fetchone()
                    if not line_row:
                        continue

                    line_id = line_row[0]
                    old_expected_qty = float(line_row[1])
                    captured_qty = float(line_row[2])
                    counted_qty = float(line_row[3])

                    # Check if line already has captures / progress
                    cur.execute(
                        "SELECT count(*) FROM field.capture WHERE tenant_id = %s AND task_line_id = %s;",
                        (tenant_id, line_id),
                    )
                    cnt_row = cur.fetchone()
                    capture_count = int(cnt_row[0]) if cnt_row else 0

                    if capture_count > 0 or captured_qty > 0 or counted_qty > 0:
                        # Conflict! Line already has captures; do NOT overwrite!
                        conflict_info = {
                            "task_id": str(task_id),
                            "task_line_id": str(line_id),
                            "line_no": item_no,
                            "captured_qty": captured_qty,
                            "old_expected_qty": old_expected_qty,
                            "new_expected_qty": new_expected_qty,
                            "status": "conflict_opened",
                        }
                        conflicts.append(conflict_info)
                        # Open exception case in field.outbox or audit
                        cur.execute(
                            """
                            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                            VALUES (%s, %s, %s, 'task_line.conflict', %s);
                            """,
                            (
                                uuid7_str(),
                                tenant_id,
                                str(line_id),
                                json.dumps(conflict_info),
                            ),
                        )
                    else:
                        # Uncaptured line: safely update expected_qty per TC3.103
                        cur.execute(
                            """
                            UPDATE field.task_line
                            SET expected_qty = %s, updated_at = NOW()
                            WHERE tenant_id = %s AND id = %s;
                            """,
                            (new_expected_qty, tenant_id, line_id),
                        )

                # Update task last_change_at
                cur.execute(
                    "UPDATE field.task SET last_change_at = %s, updated_at = NOW() WHERE id = %s;",
                    (last_change_dt, task_id),
                )

    return tasks_created, lines_created, conflicts
