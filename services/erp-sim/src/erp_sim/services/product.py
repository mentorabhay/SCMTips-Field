"""API_PRODUCT_SRV subset: A_ProductPlant listing (T1.058 material sync source).

Sim simplification (documented, S/4 differs): erpsim.material is client-wide, so every material is
listed for every plant that exists in erpsim.plant. Description and base unit are flattened onto the
entity instead of S/4's to_Description / to_Product navigation. Paging is $top/$skip with
$inlinecount=allpages, as in OData v2.
"""

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from erp_sim.db import get_conn

router = APIRouter(prefix="/sap/opu/odata/sap/API_PRODUCT_SRV", tags=["Product"])

MAX_TOP = 500


def _plant_from_filter(f: str | None) -> str:
    prefix = "Plant eq '"
    if not f or not f.startswith(prefix) or not f.endswith("'"):
        raise HTTPException(status_code=400, detail="only $filter=Plant eq '<plant>' is supported")
    plant = f[len(prefix) : -1]
    if not plant or "'" in plant:
        raise HTTPException(status_code=400, detail="invalid plant")
    return plant


@router.get("/A_ProductPlant")
async def list_product_plant(
    filter_: str | None = Query(None, alias="$filter"),
    top: int = Query(100, alias="$top", ge=1, le=MAX_TOP),
    skip: int = Query(0, alias="$skip", ge=0),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    plant = _plant_from_filter(filter_)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM erpsim.plant WHERE client = %s AND plant = %s", (sap_client, plant))
        if cur.fetchone() is None:
            return {"d": {"__count": "0", "results": []}}
        cur.execute("SELECT count(*) FROM erpsim.material WHERE client = %s", (sap_client,))
        row = cur.fetchone()
        total = int(row[0]) if row else 0
        cur.execute(
            "SELECT material_no, description, base_uom FROM erpsim.material WHERE client = %s"
            " ORDER BY material_no LIMIT %s OFFSET %s",
            (sap_client, top, skip),
        )
        results = [
            {"Product": r[0], "Plant": plant, "ProductDescription": r[1], "BaseUnit": r[2]} for r in cur.fetchall()
        ]
    return {"d": {"__count": str(total), "results": results}}
