"""API_MATERIAL_STOCK_SRV subset: A_MatlStkInAcctMod read (M4 F4, the on-hand after a goods receipt).

The field reads the ERP's own on-hand through the ErpPort (ErpReadPort.read_stock) instead of computing it, so
the stock row it sends to the core is the system of record's number. S/4 serves stock per material, plant,
storage location, batch, special stock and stock type; erpsim.stock holds one unrestricted quantity per
(material, plant, storage location), so every result has InventoryStockType '01' (unrestricted) and no batch.

Supported filters (the ones the adapter sends): ``Material eq '<m>' and Plant eq '<p>'`` optionally followed by
``and StorageLocation eq '<s>'`` (one material, M4 F4), or ``Plant eq '<p>' and InventoryStockType eq '01'``: the
unrestricted stock of every material of the plant, for the stock snapshot to the core (M4 Q10), ordered by Material
and StorageLocation and paged with ``$top`` (1..1000, default 1000) and ``$skip``. Any other filter is a 400.
"""

import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from erp_sim.db import get_conn

router = APIRouter(prefix="/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV", tags=["Stock"])

_FILTER = re.compile(
    r"^Material eq '([^']{1,40})' and Plant eq '([^']{1,40})'(?: and StorageLocation eq '([^']{1,40})')?$"
)
_PLANT = re.compile(r"^Plant eq '([^']{1,40})' and InventoryStockType eq '01'$")
MAX_TOP = 1000


def parse_stock_filter(f: str | None) -> tuple[str, str, str | None]:
    m = _FILTER.match((f or "").strip())
    if not m:
        raise HTTPException(
            status_code=400,
            detail="only $filter=Material eq '<m>' and Plant eq '<p>' [and StorageLocation eq '<s>'] is supported",
        )
    return m.group(1), m.group(2), m.group(3)


def _result(material: str, plant: str, sloc: str, qty: Any, uom: str) -> dict[str, Any]:
    return {"Material": material, "Plant": plant, "StorageLocation": sloc, "Batch": "", "Supplier": "", "Customer": "",
            "InventorySpecialStockType": "", "InventoryStockType": "01", "MatlWrhsStkQtyInMatlBaseUnit": str(qty),
            "MaterialBaseUnit": uom}


@router.get("/A_MatlStkInAcctMod")
async def list_material_stock(
    filter_: str | None = Query(None, alias="$filter"),
    top: int = Query(MAX_TOP, alias="$top", ge=1, le=MAX_TOP),
    skip: int = Query(0, alias="$skip", ge=0),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    whole = _PLANT.match((filter_ or "").strip())
    if whole:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT material_no, storage_location, quantity, uom FROM erpsim.stock WHERE client = %s"
                        " AND plant = %s ORDER BY material_no, storage_location LIMIT %s OFFSET %s",
                        (sap_client, whole.group(1), top, skip))
            rows = cur.fetchall()
        return {"d": {"results": [_result(r[0], whole.group(1), r[1], r[2], r[3]) for r in rows]}}
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
    return {"d": {"results": [_result(material, plant, r[0], r[1], r[2]) for r in rows]}}
