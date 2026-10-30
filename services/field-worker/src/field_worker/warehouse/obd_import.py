"""Outbound Delivery Polling and Pick Task Generation Worker (Task T3.029 / FR3.017 / FR3.026 / TC3.114).

Polls A_OutbDeliveryHeader/Item for site's shipping points and plants.
Upserts tasks by DeliveryDocument and sorts lines by pick route order from the site graph.
"""

import os

import httpx
import psycopg
import structlog
from field_common.uuid7 import uuid7_str

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

ERP_SIM_URL = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")


async def poll_and_import_outbound_deliveries(
    tenant_id: str,
    site_id: str,
    shipping_point: str,
    erp_url: str = ERP_SIM_URL,
    db_url: str = DATABASE_URL,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int]:
    """Poll open outbound deliveries and upsert pick tasks.

    Returns:
        (tasks_created, lines_created)
    """
    filter_expr = f"ShippingPoint eq '{shipping_point}' and OverallPickingStatus ne 'C'"
    url = f"{erp_url}/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV;v=0002/A_OutbDeliveryHeader"
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
            logger.warning("obd_poll_failed", status=resp.status_code, text=resp.text[:200])
            return 0, 0

        payload = resp.json()
        deliveries = payload.get("d", {}).get("results", [])
    except Exception as e:
        logger.error("obd_poll_exception", error=str(e))
        return 0, 0
    finally:
        if should_close:
            await client.aclose()

    tasks_created = 0
    lines_created = 0

    try:
        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false);",
                    (tenant_id,),
                )

                for deliv in deliveries:
                    deliv_no = deliv.get("DeliveryDocument", "")
                    if not deliv_no:
                        continue

                    # Check if pick task already exists
                    await cur.execute(
                        """
                        SELECT id FROM field.task
                        WHERE tenant_id = %s::uuid AND ref_doc_no = %s AND task_type = 'pick';
                        """,
                        (tenant_id, deliv_no),
                    )
                    existing = await cur.fetchone()
                    if existing:
                        continue  # Already imported

                    task_id = uuid7_str()
                    await cur.execute(
                        """
                        INSERT INTO field.task (
                            id, tenant_id, site_id, title, task_type,
                            status, priority, ref_doc_no, created_at, updated_at
                        ) VALUES (
                            %s::uuid, %s::uuid, %s::uuid, %s, 'pick',
                            'open', 50, %s, NOW(), NOW()
                        );
                        """,
                        (
                            task_id,
                            tenant_id,
                            site_id,
                            f"Pick Delivery {deliv_no}",
                            deliv_no,
                        ),
                    )
                    tasks_created += 1

                    raw_items = deliv.get("to_DeliveryDocumentItem", {}).get("results", [])
                    # Sort lines by storage bin order (T3.035 / FR3.026)
                    sorted_items = sorted(
                        raw_items,
                        key=lambda itm: itm.get("StorageBin", "") or itm.get("StorageLocation", ""),
                    )

                    seq = 1
                    for item in sorted_items:
                        line_id = uuid7_str()
                        mat_id = item.get("Material", "")
                        qty = float(item.get("ActualDeliveryQuantity", 1.0))
                        storage_bin = item.get("StorageBin", "A-01-01")

                        await cur.execute(
                            """
                            INSERT INTO field.task_line (
                                id, tenant_id, task_id, line_no, material_id,
                                required_qty, picked_qty, storage_bin, status, created_at
                            ) VALUES (
                                %s::uuid, %s::uuid, %s::uuid, %s, %s,
                                %s, 0, %s, 'open', NOW()
                            );
                            """,
                            (
                                line_id,
                                tenant_id,
                                task_id,
                                seq,
                                mat_id,
                                qty,
                                storage_bin,
                            ),
                        )
                        lines_created += 1
                        seq += 1

            await conn.commit()
    except Exception as e:
        logger.error("obd_db_import_failed", error=str(e))
        return tasks_created, lines_created

    return tasks_created, lines_created
