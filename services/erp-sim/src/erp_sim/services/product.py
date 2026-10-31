"""API_PRODUCT_SRV subset: A_ProductPlant listing (T1.058 material sync source) and barcodes (M3).

Sim simplifications (documented, S/4 differs): erpsim.material is client-wide, so every material is
listed for every plant that exists in erpsim.plant, except a sandbox material (HOME-nnnn), which belongs
to the plant of the sandbox site that created it. Description and base unit are flattened onto the
entity instead of S/4's to_Description / to_Product navigation. Paging is $top/$skip with
$inlinecount=allpages, as in OData v2.

Barcodes (SAP table MEAN) are read the S/4 way as A_ProductUnitsOfMeasureEAN entities (Product,
AlternativeUnit, ConsecutiveNumber, ProductStandardID, InternationalArticleNumberCat,
IsMainGlobalTradeItemNumber): on their own entity set, filtered by Product or by ProductStandardID, and
as ``$expand=to_ProductUnitsOfMeasureEAN`` on A_ProductPlant (in S/4 the navigation runs
A_Product -> to_ProductUnitsOfMeasure -> to_InternationalArticleNumber; the sim flattens it).
"""

import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from erp_sim.db import get_conn

router = APIRouter(prefix="/sap/opu/odata/sap/API_PRODUCT_SRV", tags=["Product"])

MAX_TOP = 500
EAN_EXPAND = "to_ProductUnitsOfMeasureEAN"
_EAN_FILTER = re.compile(r"^(Product|ProductStandardID) eq '([^']{1,128})'$")


def _plant_from_filter(f: str | None) -> str:
    prefix = "Plant eq '"
    if not f or not f.startswith(prefix) or not f.endswith("'"):
        raise HTTPException(status_code=400, detail="only $filter=Plant eq '<plant>' is supported")
    plant = f[len(prefix) : -1]
    if not plant or "'" in plant:
        raise HTTPException(status_code=400, detail="invalid plant")
    return plant


def ean_entity(material_no: str, barcode: str, uom: str, is_main: bool, n: int) -> dict[str, Any]:
    """One A_ProductUnitsOfMeasureEAN entity. Category 'HE' (manufacturer EAN) for digit-only codes,
    'IC' (in-house) for anything else (a material number used as its own barcode)."""
    return {
        "Product": material_no,
        "AlternativeUnit": uom,
        "ConsecutiveNumber": f"{n:05d}",
        "ProductStandardID": barcode,
        "InternationalArticleNumberCat": "HE" if barcode.isdigit() else "IC",
        "IsMainGlobalTradeItemNumber": is_main,
    }


def _barcodes(cur: Any, client: str, materials: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {m: [] for m in materials}
    if not materials:
        return out
    cur.execute(
        "SELECT material_no, barcode, uom, is_main FROM erpsim.material_barcode WHERE client = %s"
        " AND material_no = ANY(%s) ORDER BY material_no, is_main DESC, created_at, barcode",
        (client, materials),
    )
    for mat, code, uom, main in cur.fetchall():
        out[mat].append(ean_entity(mat, code, uom, bool(main), len(out[mat]) + 1))
    return out


@router.get("/A_ProductPlant")
async def list_product_plant(
    filter_: str | None = Query(None, alias="$filter"),
    top: int = Query(100, alias="$top", ge=1, le=MAX_TOP),
    skip: int = Query(0, alias="$skip", ge=0),
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    plant = _plant_from_filter(filter_)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM erpsim.plant WHERE client = %s AND plant = %s", (sap_client, plant))
        if cur.fetchone() is None:
            return {"d": {"__count": "0", "results": []}}
        cur.execute("SELECT count(*) FROM erpsim.material WHERE client = %s"
                    " AND (sandbox_plant IS NULL OR sandbox_plant = %s)", (sap_client, plant))
        row = cur.fetchone()
        total = int(row[0]) if row else 0
        cur.execute(
            "SELECT material_no, description, base_uom FROM erpsim.material WHERE client = %s"
            " AND (sandbox_plant IS NULL OR sandbox_plant = %s) ORDER BY material_no LIMIT %s OFFSET %s",
            (sap_client, plant, top, skip),
        )
        results: list[dict[str, Any]] = [
            {"Product": r[0], "Plant": plant, "ProductDescription": r[1], "BaseUnit": r[2]} for r in cur.fetchall()
        ]
        if expand and EAN_EXPAND in expand:
            eans = _barcodes(cur, sap_client, [str(r["Product"]) for r in results])
            for r in results:
                r[EAN_EXPAND] = {"results": eans[str(r["Product"])]}
    return {"d": {"__count": str(total), "results": results}}


@router.get("/A_ProductUnitsOfMeasureEAN")
async def list_product_eans(
    filter_: str = Query(..., alias="$filter", description="Product eq '<material>' or ProductStandardID eq '<code>'"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    m = _EAN_FILTER.match(filter_ or "")
    if not m:
        raise HTTPException(status_code=400, detail="only $filter=Product eq '<x>' or ProductStandardID eq '<x>'")
    by_product = m.group(1) == "Product"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT material_no FROM erpsim.material_barcode WHERE client = %s"
            " AND ((%s AND material_no = %s) OR (NOT %s AND barcode = %s))",
            (sap_client, by_product, m.group(2), by_product, m.group(2)),
        )
        materials = sorted({str(r[0]) for r in cur.fetchall()})
        eans = _barcodes(cur, sap_client, materials)
    results = [e for mat in materials for e in eans[mat]
               if by_product or e["ProductStandardID"] == m.group(2)]
    return {"d": {"results": results}}
