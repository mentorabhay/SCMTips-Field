"""API_MATERIAL_STOCK_SRV subset: A_MatlStkInAcctMod read (M4 F4, the on-hand after a goods receipt).

The field reads the ERP's own on-hand through the ErpPort (ErpReadPort.read_stock) instead of computing it, so
the stock row it sends to the core is the system of record's number. S/4 serves stock per material, plant,
storage location, batch, special stock and stock type; erpsim.stock holds one unrestricted quantity per
(material, plant, storage location), so every result has InventoryStockType '01' (unrestricted) and no batch.

Supported filter (the one the adapter sends): ``Material eq '<m>' and Plant eq '<p>'`` optionally followed by
``and StorageLocation eq '<s>'``.
"""

import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from erp_sim.db import get_conn

router = APIRouter(prefix="/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV", tags=["Stock"])

_FILTER = re.compile(
    r"^Material eq '([^']{1,40})' and Plant eq '([^']{1,40})'(?: and StorageLocation eq '([^']{1,40})')?$"
)


def parse_stock_filter(f: str | None) -> tuple[str, str, str | None]:
    m = _FILTER.match((f or "").strip())
    if not m:
        raise HTTPException(
            status_code=400,
            detail="only $filter=Material eq '<m>' and Plant eq '<p>' [and StorageLocation eq '<s>'] is supported",
        )
    return m.group(1), m.group(2), m.group(3)


@router.get("/A_MatlStkInAcctMod")
async def list_material_stock(
    filter_: str | None = Query(None, alias="$filter"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    material, plant, sloc = parse_stock_filter(filter_)
    sql = ("SELECT storage_location, quantity, uom FROM erpsim.stock WHERE client = %s AND material_no = %s"
           " AND plant = %s")
    args: list[str] = [sap_client, material, plant]
    if sloc:
        sql += " AND storage_location = %s"
        args.append(sloc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql + " ORDER BY storage_location", args)
        rows = cur.fetchall()
    results = [
        {"Material": material, "Plant": plant, "StorageLocation": r[0], "Batch": "", "Supplier": "", "Customer": "",
         "InventorySpecialStockType": "", "InventoryStockType": "01", "MatlWrhsStkQtyInMatlBaseUnit": str(r[1]),
         "MaterialBaseUnit": r[2]}
        for r in rows
    ]
    return {"d": {"results": results}}
