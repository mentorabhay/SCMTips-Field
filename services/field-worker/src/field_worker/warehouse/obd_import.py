"""Outbound delivery import into pick tasks (Task T3.029 / FR3.017 / FR3.026 / TC3.114).

Polls A_OutbDeliveryHeader (+ items) for the site's shipping point (the plant, as in the SAMPLE
system) with OverallPickingStatus ne 'C', and creates one pick task per delivery:

- ``line_no`` = the delivery item number (10, 20, ...), because the goods-issue posting addresses
  A_OutbDeliveryItem by it;
- ``storage_bin`` = the bin that holds the material in field.bin_stock (SAP IM has no bins);
- ``expected_qty`` = the delivery quantity. Stops are shown in walking order (bin code order; the
  task list sorts pick lines by bin). FR3.026's graph-distance order needs a site graph (T3.035).

Idempotent: a delivery that already has a pick task is skipped. Runs as the worker role
(NOBYPASSRLS) with the tenant set, so RLS applies. (C4: the previous version wrote to columns that do
not exist, task_type / required_qty, and never ran.)
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import structlog
from field_common.bin_stock import bin_of_material

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)
ERP_SIM_URL = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")
OBD_PATH = "/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/A_OutbDeliveryHeader"


async def fetch_open_outbound_deliveries(
    shipping_point: str, erp_url: str = ERP_SIM_URL, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    params = {"$filter": f"ShippingPoint eq '{shipping_point}' and OverallPickingStatus ne 'C'",
              "$expand": "to_DeliveryDocumentItem"}
    headers = {"Accept": "application/json", "sap-client": "100"}
    own = client is None
    cl = client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await cl.get(f"{erp_url}{OBD_PATH}", params=params, headers=headers)
    finally:
        if own:
            await cl.aclose()
    if resp.status_code != 200:
        logger.warning("obd_poll_failed", status=resp.status_code, text=resp.text[:200])
        return []
    return list(resp.json().get("d", {}).get("results", []))


def import_outbound_deliveries(
    cur: psycopg.Cursor[Any], tenant_id: str, site_id: str, deliveries: list[dict[str, Any]]
) -> tuple[int, int]:
    """Create pick tasks for deliveries not imported yet; returns (tasks_created, lines_created)."""
    tasks = lines = 0
    for d in deliveries:
        deliv = d.get("DeliveryDocument")
        if not deliv or d.get("OverallGoodsMovementStatus") == "C":
            continue
        cur.execute("SELECT 1 FROM field.task WHERE tenant_id = %s AND type = 'pick' AND ref_doc_no = %s AND site_id = %s",
                    (tenant_id, deliv, site_id))
        if cur.fetchone():
            continue
        items = (d.get("to_DeliveryDocumentItem") or {}).get("results", [])
        if not items:
            continue
        ship_to = d.get("ShipToParty")
        cur.execute(
            """
            INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle)
            VALUES (%s, %s, 'pick', 'pending', 'normal', %s, %s, %s) RETURNING id
            """,
            (tenant_id, site_id, f"Pick delivery {deliv}", deliv, f"For {ship_to}" if ship_to else None),
        )
        row = cur.fetchone()
        if not row:
            continue
        task_id = str(row[0])
        tasks += 1
        for it in items:
            mat = it.get("Material", "")
            cur.execute("SELECT id FROM field.material WHERE tenant_id = %s AND erp_material_no = %s"
                        " ORDER BY updated_at DESC LIMIT 1", (tenant_id, mat))
            mrow = cur.fetchone()
            cur.execute(
                """
                INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,
                       storage_bin, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (tenant_id, site_id, task_id, int(it.get("DeliveryDocumentItem") or 10), mrow[0] if mrow else None,
                 Decimal(str(it.get("ActualDeliveryQuantity") or 0)), it.get("DeliveryQuantityUnit") or "EA",
                 bin_of_material(cur, site_id, mat)),
            )
            lines += 1
    return tasks, lines


async def poll_and_import_outbound_deliveries(
    tenant_id: str,
    site_id: str,
    shipping_point: str,
    erp_url: str = ERP_SIM_URL,
    db_url: str = DATABASE_URL,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int]:
    """Poll open outbound deliveries and create pick tasks. Returns (tasks_created, lines_created)."""
    deliveries = await fetch_open_outbound_deliveries(shipping_point, erp_url, client)
    if not deliveries:
        return 0, 0
    with psycopg.connect(db_url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (tenant_id,))
        out = import_outbound_deliveries(cur, tenant_id, site_id, deliveries)
        conn.commit()
    return out
