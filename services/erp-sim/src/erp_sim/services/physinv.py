"""API_PHYSICAL_INVENTORY_DOC_SRV Implementation (Task T3.004).

Implements:
- A_PhysInventoryDocHeader / A_PhysInventoryDocItem create & read
- Count entry by PATCH
- InitiateRecount
- PostDifferences (701 gain, 702 loss)
- Freeze snapshot and posting block flags
- Document numbering 100000000+
"""

import contextlib
import json
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel

from erp_sim.db import get_conn
from erp_sim.dedupe import check_dedupe, compute_request_hash, record_dedupe
from erp_sim.faults import evaluate_faults
from erp_sim.locks import acquire_lock, release_lock
from erp_sim.numbering import allocate_material_document_number, allocate_number
from erp_sim.stock import apply_movement, get_current_stock

router = APIRouter(prefix="/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV", tags=["Physical Inventory"])


class PiItemCreate(BaseModel):
    Material: str
    Plant: str = "1010"
    StorageLocation: str = "101A"


class PiDocCreate(BaseModel):
    Plant: str = "1010"
    StorageLocation: str = "101A"
    PhysicalInventoryDocumentFiscalYear: str = "2026"
    PostingBlocked: bool = True
    FreezeBookInventory: bool = True
    YY1_FieldSandbox: bool = False  # noqa: N815 - key-user extension field: created for a sandbox site (M3)
    YY1_FieldSimulated: bool = False  # noqa: N815 - set up by `stack home --simulate-differences` (M3)
    to_PhysicalInventoryDocItem: dict[str, list[PiItemCreate]] | list[PiItemCreate] | None = None  # noqa: N815


class PiItemCountPatch(BaseModel):
    QuantityInEntryUnit: str
    EntryUnit: str = "EA"


def allocate_pi_doc_number(cur: Any, client: str) -> str:
    base_num = allocate_number(cur, client, "PI_DOCUMENT")
    if base_num < 100000000:
        base_num = 100000000 + base_num
    return str(base_num)


@router.post("/A_PhysInventoryDocHeader")
async def create_pi_doc(
    doc_in: PiDocCreate,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        pi_num = allocate_pi_doc_number(cur, sap_client)
        doc_year = doc_in.PhysicalInventoryDocumentFiscalYear or "2026"

        cur.execute(
            """
            INSERT INTO erpsim.physical_inventory_doc (
                client, pi_document, fiscal_year, plant, storage_location, status, header_data
            )
            VALUES (%s, %s, %s, %s, %s, 'created', %s);
        """,
            (sap_client, pi_num, doc_year, doc_in.Plant, doc_in.StorageLocation,
             json.dumps({k: True for k, on in (("sandbox", doc_in.YY1_FieldSandbox),
                                               ("simulated", doc_in.YY1_FieldSimulated)) if on})),
        )

        items_raw = doc_in.to_PhysicalInventoryDocItem
        items_list: list[PiItemCreate] = []
        if isinstance(items_raw, dict) and "results" in items_raw:
            items_list = [i if isinstance(i, PiItemCreate) else PiItemCreate(**i) for i in items_raw["results"]]
        elif isinstance(items_raw, list):
            items_list = items_raw

        line_no = 1
        for it in items_list:
            book_qty = get_current_stock(cur, sap_client, it.Plant, it.StorageLocation, it.Material)
            cur.execute(
                """
                INSERT INTO erpsim.physical_inventory_item (
                    client, pi_document, fiscal_year, line_no, material_no, book_qty, counted_qty, uom, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, NULL, 'EA', 'created');
            """,
                (sap_client, pi_num, doc_year, line_no, it.Material, book_qty),
            )
            line_no += 1

        conn.commit()

        return {
            "d": {
                "PhysicalInventoryDocument": pi_num,
                "FiscalYear": doc_year,
                "Plant": doc_in.Plant,
                "StorageLocation": doc_in.StorageLocation,
                "PostingBlocked": doc_in.PostingBlocked,
                "FreezeBookInventory": doc_in.FreezeBookInventory,
            }
        }


@router.get("/A_PhysInventoryDocHeader(PhysicalInventoryDocument='{pi_doc}',FiscalYear='{fiscal_year}')")
async def get_pi_doc(
    pi_doc: str,
    fiscal_year: str,
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT plant, storage_location, status
            FROM erpsim.physical_inventory_doc
            WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
        """,
            (sap_client, pi_doc, fiscal_year),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="PI Document not found")

        d_data: dict[str, Any] = {
            "PhysicalInventoryDocument": pi_doc,
            "FiscalYear": fiscal_year,
            "Plant": row[0],
            "StorageLocation": row[1],
            "Status": row[2],
            "PostingBlocked": True,
            "FreezeBookInventory": True,
        }

        if expand and "to_PhysicalInventoryDocItem" in expand:
            cur.execute(
                """
                SELECT line_no, material_no, book_qty, counted_qty, uom, status
                FROM erpsim.physical_inventory_item
                WHERE client = %s AND pi_document = %s AND fiscal_year = %s
                ORDER BY line_no ASC;
            """,
                (sap_client, pi_doc, fiscal_year),
            )
            items = []
            for r in cur.fetchall():
                items.append({
                    "PhysicalInventoryDocument": pi_doc,
                    "FiscalYear": fiscal_year,
                    "PhysicalInventoryDocumentItem": str(r[0]),
                    "Material": r[1],
                    "BookQuantity": str(r[2]),
                    "CountedQuantity": str(r[3]) if r[3] is not None else "",
                    "UnitOfEntry": r[4],
                    "Status": r[5],
                })
            d_data["to_PhysicalInventoryDocItem"] = {"results": items}

        return {"d": d_data}


@router.patch("/A_PhysInventoryDocItem(PhysicalInventoryDocument='{pi_doc}',FiscalYear='{fiscal_year}',PhysicalInventoryDocumentItem='{line_no}')")
async def enter_count(
    pi_doc: str,
    fiscal_year: str,
    line_no: int,
    body: PiItemCountPatch,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    counted = Decimal(body.QuantityInEntryUnit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE erpsim.physical_inventory_item
            SET counted_qty = %s, status = 'counted'
            WHERE client = %s AND pi_document = %s AND fiscal_year = %s AND line_no = %s;
        """,
            (counted, sap_client, pi_doc, fiscal_year, line_no),
        )
        conn.commit()

    return {
        "d": {
            "PhysicalInventoryDocument": pi_doc,
            "FiscalYear": fiscal_year,
            "PhysicalInventoryDocumentItem": str(line_no),
            "QuantityInEntryUnit": str(counted),
        }
    }


@router.post("/InitiateRecount")
async def initiate_recount(
    pi_doc: str = Query(..., alias="PhysicalInventoryDocument"),
    fiscal_year: str = Query(..., alias="FiscalYear"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE erpsim.physical_inventory_item
            SET counted_qty = NULL, status = 'recount'
            WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
        """,
            (sap_client, pi_doc, fiscal_year),
        )
        cur.execute(
            """
            UPDATE erpsim.physical_inventory_doc
            SET status = 'recount'
            WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
        """,
            (sap_client, pi_doc, fiscal_year),
        )
        conn.commit()
        return {
            "d": {
                "PhysicalInventoryDocument": pi_doc,
                "FiscalYear": fiscal_year,
                "Status": "recount",
            }
        }


@router.post("/PostDifferences")
async def post_differences(
    request: Request,
    response: Response,
    pi_doc: str = Query(..., alias="PhysicalInventoryDocument"),
    fiscal_year: str = Query(..., alias="FiscalYear"),
    sap_client: str = Header("100", alias="sap-client"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    idem_key = idempotency_key
    raw_body = await request.body()
    req_hash = compute_request_hash(raw_body or f"{pi_doc}_{fiscal_year}")
    session_id = f"sess_{sap_client}"

    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(
            cur, sap_client, "API_PHYSICAL_INVENTORY_DOC_SRV", "PostDifferences", pi_doc
        )

        if idem_key:
            is_dup, dup_doc, dup_year = check_dedupe(cur, sap_client, idem_key, req_hash)
            if is_dup:
                response.headers["sap-message"] = "ZSIM/DUP"
                return {
                    "d": {
                        "MaterialDocument": dup_doc,
                        "MaterialDocumentYear": dup_year,
                        "PhysicalInventoryDocument": pi_doc,
                    }
                }

        acquire_lock(cur, sap_client, "PI_DOCUMENT", pi_doc, session_id)
        try:
            cur.execute(
                """
                SELECT plant, storage_location, status, header_data
                FROM erpsim.physical_inventory_doc
                WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
            """,
                (sap_client, pi_doc, fiscal_year),
            )
            hdr = cur.fetchone()
            if not hdr:
                raise HTTPException(status_code=404, detail=f"PI doc {pi_doc} not found")

            plant, sloc = hdr[0], hdr[1]
            diff_head: dict[str, Any] = {"PhysicalInventoryDocument": pi_doc}
            for flag in ("sandbox", "simulated"):
                if isinstance(hdr[3], dict) and hdr[3].get(flag):
                    diff_head[flag] = True

            cur.execute(
                """
                SELECT line_no, material_no, book_qty, counted_qty, uom
                FROM erpsim.physical_inventory_item
                WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
            """,
                (sap_client, pi_doc, fiscal_year),
            )
            items = cur.fetchall()

            mat_doc, doc_year = allocate_material_document_number(cur, sap_client)

            cur.execute(
                """
                INSERT INTO erpsim.document (
                    client, doc_number, fiscal_year, doc_type, movement_type,
                    reversal_of, header_data, status
                )
                VALUES (%s, %s, %s, 'WI', '701', NULL, %s, 'posted');
            """,
                (sap_client, mat_doc, doc_year, json.dumps(diff_head)),
            )

            doc_line = 1
            for it in items:
                mat_no, book, counted, uom = (
                    it[1],
                    Decimal(str(it[2])),
                    Decimal(str(it[3] if it[3] is not None else it[2])),
                    it[4],
                )
                diff = counted - book
                if diff == Decimal("0"):
                    continue

                mvt = "701" if diff > 0 else "702"
                abs_diff = abs(diff)

                apply_movement(cur, sap_client, plant, sloc, mat_no, abs_diff, mvt, uom)

                cur.execute(
                    """
                    INSERT INTO erpsim.document_item (
                        client, doc_number, fiscal_year, line_no, material_no,
                        plant, storage_location, quantity, uom, movement_type, item_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                    (sap_client, mat_doc, doc_year, doc_line, mat_no, plant, sloc, abs_diff, uom, mvt, json.dumps({"PhysicalInventoryItem": it[0]})),
                )
                doc_line += 1

            cur.execute(
                """
                UPDATE erpsim.physical_inventory_doc
                SET status = 'posted'
                WHERE client = %s AND pi_document = %s AND fiscal_year = %s;
            """,
                (sap_client, pi_doc, fiscal_year),
            )

            if idem_key:
                record_dedupe(cur, sap_client, idem_key, req_hash, mat_doc, doc_year)
            conn.commit()

            return {
                "d": {
                    "MaterialDocument": mat_doc,
                    "MaterialDocumentYear": doc_year,
                    "PhysicalInventoryDocument": pi_doc,
                }
            }
        finally:
            with contextlib.suppress(Exception):
                release_lock(cur, sap_client, "PI_DOCUMENT", pi_doc, session_id)
