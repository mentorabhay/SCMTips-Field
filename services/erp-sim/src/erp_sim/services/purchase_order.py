"""API_PURCHASEORDER_PROCESS_SRV subset: A_PurchaseOrderItem read (M4 Q10, the open-PO snapshot to the core).

The field reads the ERP's purchase-order lines through the ErpPort (ErpReadPort.list_purchase_order_items) and sends
the core what is still open, so the core's open supply is the system of record's. erpsim.purchase_order_item is
seeded from the core's export (``stack seed-core-export``, migration erpsim_0005).

S/4 fields served as S/4 names them: PurchaseOrder, PurchaseOrderItem, Material, Plant, StorageLocation,
OrderQuantity, PurchaseOrderQuantityUnit, IsCompletelyDelivered. Flattened for one read (S/4 keeps them elsewhere):
Supplier (A_PurchaseOrder) and ScheduleLineDeliveryDate (A_PurchaseOrderScheduleLine). Simulator only (YY1_, no S/4
equivalent verified, rule 2.4): YY1_ReceivedQuantity (sum of the goods receipts 101 that reference the line, less
reversed documents and cancelled items; S/4 keeps this in the PO history), YY1_LastGoodsReceiptDate (the posting date
of the newest of them), YY1_SupplyStatus (the core's status of the line) and YY1_LaneCode (the core's lane).

Supported: ``$filter=Plant eq '<p>'`` (required), ``$top`` (1..1000, default 1000) and ``$skip``; ordered by
PurchaseOrder, PurchaseOrderItem.
"""

import re
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from erp_sim.db import get_conn

router = APIRouter(prefix="/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV", tags=["Purchase order"])

_FILTER = re.compile(r"^Plant eq '([^']{1,40})'$")
MAX_TOP = 1000



def _num(q: Decimal) -> str:
    return format(q.normalize(), "f") if q == q.to_integral_value() else str(q)


@router.get("/A_PurchaseOrderItem")
async def list_purchase_order_items(
    filter_: str | None = Query(None, alias="$filter"),
    top: int = Query(MAX_TOP, alias="$top", ge=1, le=MAX_TOP),
    skip: int = Query(0, alias="$skip", ge=0),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    m = _FILTER.match((filter_ or "").strip())
    if not m:
        raise HTTPException(status_code=400, detail="only $filter=Plant eq '<p>' is supported")
    sql = """
        WITH gr AS (  -- goods receipts per PO line: 101 items referencing it, not cancelled, document not reversed
            SELECT di.item_data->>'PurchaseOrder' AS po, di.item_data->>'PurchaseOrderItem' AS po_item,
                   SUM(di.quantity) AS received, MAX(d.created_at)::date AS last_gr
              FROM erpsim.document_item di
              JOIN erpsim.document d USING (client, doc_number, fiscal_year)
             WHERE di.client = %s AND di.movement_type = '101' AND di.item_data ? 'PurchaseOrder'
               AND d.status <> 'reversed' AND COALESCE((di.item_data->>'cancelled')::boolean, false) = false
             GROUP BY 1, 2
        )
        SELECT i.purchase_order, i.item_no, i.material_no, i.plant, i.storage_location, i.order_qty, i.uom,
               i.delivery_date, i.status, i.ext->>'lane_code', h.supplier,
               COALESCE(gr.received, 0), gr.last_gr
          FROM erpsim.purchase_order_item i
          JOIN erpsim.purchase_order h USING (client, purchase_order)
          LEFT JOIN gr ON gr.po = i.purchase_order AND gr.po_item = i.item_no
         WHERE i.client = %s AND i.plant = %s
         ORDER BY i.purchase_order, i.item_no
         LIMIT %s OFFSET %s
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (sap_client, sap_client, m.group(1), top, skip))
        rows = cur.fetchall()
    results = []
    for po, item, mat, plant, sloc, qty, uom, due, status, lane, supplier, received, last_gr in rows:
        order_qty, got = Decimal(str(qty)), Decimal(str(received))
        results.append({
            "PurchaseOrder": po, "PurchaseOrderItem": item, "Material": mat, "Plant": plant,
            "StorageLocation": sloc, "OrderQuantity": _num(order_qty), "PurchaseOrderQuantityUnit": uom,
            "IsCompletelyDelivered": got >= order_qty, "Supplier": supplier or "",
            "ScheduleLineDeliveryDate": due.isoformat() if due else None,
            "YY1_ReceivedQuantity": _num(got), "YY1_LastGoodsReceiptDate": last_gr.isoformat() if last_gr else None,
            "YY1_SupplyStatus": status, "YY1_LaneCode": lane or "",
        })
    return {"d": {"results": results}}
