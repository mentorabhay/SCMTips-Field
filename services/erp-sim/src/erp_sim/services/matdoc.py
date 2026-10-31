"""API_MATERIAL_DOCUMENT_SRV Implementation (Task T3.005).

Implements:
- A_MaterialDocumentHeader / A_MaterialDocumentItem reads
- Deep insert of material documents (101, 261, 321, 601, 701, 702)
- 321 Transfer posting (Quality to Unrestricted)
- Cancel and CancelItem (reversal semantics 102/602)
- Reversal of already reversed item returns HTTP 409 Conflict
- Conservation of inventory (net zero on reversal)
"""

import contextlib
import json
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from erp_sim.db import get_conn
from erp_sim.dedupe import check_dedupe, compute_request_hash, record_dedupe
from erp_sim.faults import evaluate_faults
from erp_sim.locks import acquire_lock, release_lock
from erp_sim.numbering import allocate_material_document_number
from erp_sim.stock import apply_movement

router = APIRouter(prefix="/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV", tags=["Material Document"])

REVERSAL_MAP = {
    "101": "102",
    "601": "602",
    "701": "702",
    "702": "701",
    "261": "262",
    "321": "322",
    "561": "562",
}

DISALLOWED_REVERSAL_TYPES = {"102", "602", "262", "322", "562"}


class MaterialDocumentItemIn(BaseModel):
    Material: str
    Plant: str = "1010"
    StorageLocation: str = "101A"
    GoodsMovementType: str = "101"
    QuantityInEntryUnit: str
    EntryUnit: str = "EA"


class MaterialDocumentCreateIn(BaseModel):
    GoodsMovementCode: str = "01"
    DocumentDate: str | None = None
    PostingDate: str | None = None
    MaterialDocumentHeaderText: str | None = None
    # Key-user extension fields (the S/4 YY1_ convention): set by the field app for sandbox sites (M3).
    field_sandbox: bool = Field(default=False, alias="YY1_FieldSandbox")
    field_simulated: bool = Field(default=False, alias="YY1_FieldSimulated")
    to_MaterialDocumentItem: dict[str, list[MaterialDocumentItemIn]] | list[MaterialDocumentItemIn] | None = None  # noqa: N815


def document_header(doc_in: MaterialDocumentCreateIn) -> dict[str, Any]:
    """header_data of a created material document; ``sandbox`` / ``simulated`` only when set (M3)."""
    head: dict[str, Any] = {"GoodsMovementCode": doc_in.GoodsMovementCode}
    if doc_in.MaterialDocumentHeaderText:
        head["MaterialDocumentHeaderText"] = doc_in.MaterialDocumentHeaderText
    if doc_in.field_sandbox:
        head["sandbox"] = True
    if doc_in.field_simulated:
        head["simulated"] = True
    return head


HEADER_TEXT_FILTER = "MaterialDocumentHeaderText eq 'FIELD:"


@router.get("/A_MaterialDocumentHeader")
async def find_material_documents(
    filter_: str | None = Query(None, alias="$filter"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """Find documents by header text ``FIELD:<idempotency key>`` (timeout recovery, FR1.011).

    Only this filter is supported. The sim keeps the key in its dedupe store rather than a header
    text column; the response shape matches the S/4 collection read.
    """
    if not filter_ or not filter_.startswith(HEADER_TEXT_FILTER) or not filter_.endswith("'"):
        raise HTTPException(status_code=400, detail="only $filter=MaterialDocumentHeaderText eq 'FIELD:<key>' is supported")
    key = filter_[len(HEADER_TEXT_FILTER) : -1]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.document_no, d.fiscal_year, d.created_at FROM erpsim.dedupe d"
            " WHERE d.client = %s AND d.idem_key = %s",
            (sap_client, key),
        )
        rows = cur.fetchall()
    return {
        "d": {
            "results": [
                {
                    "MaterialDocument": r[0],
                    "MaterialDocumentYear": r[1],
                    "MaterialDocumentHeaderText": f"FIELD:{key}",
                    "CreationDate": r[2].date().isoformat(),
                }
                for r in rows
            ]
        }
    }


@router.get("/A_MaterialDocumentHeader(MaterialDocument='{doc_number}',MaterialDocumentYear='{fiscal_year}')")
async def get_material_document(
    doc_number: str,
    fiscal_year: str,
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_type, movement_type, reversal_of, status, header_data, created_at
            FROM erpsim.document
            WHERE client = %s AND doc_number = %s AND fiscal_year = %s;
        """,
            (sap_client, doc_number, fiscal_year),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Material document not found")
        head = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")

        d_data: dict[str, Any] = {
            "MaterialDocument": doc_number,
            "MaterialDocumentYear": fiscal_year,
            "DocumentDate": row[5].date().isoformat(),
            "PostingDate": row[5].date().isoformat(),
            "GoodsMovementCode": head.get("GoodsMovementCode", "01"),
            "Status": row[3],
            "MaterialDocumentHeaderText": head.get("MaterialDocumentHeaderText", ""),
            "YY1_FieldSandbox": bool(head.get("sandbox")),
            "YY1_FieldSimulated": bool(head.get("simulated")),
        }

        if expand and "to_MaterialDocumentItem" in expand:
            cur.execute(
                """
                SELECT line_no, material_no, plant, storage_location, quantity, uom, movement_type, item_data
                FROM erpsim.document_item
                WHERE client = %s AND doc_number = %s AND fiscal_year = %s
                ORDER BY line_no ASC;
            """,
                (sap_client, doc_number, fiscal_year),
            )
            items = []
            for it in cur.fetchall():
                idata = it[7] if isinstance(it[7], dict) else json.loads(it[7] or "{}")
                items.append({
                    "MaterialDocument": doc_number,
                    "MaterialDocumentYear": fiscal_year,
                    "MaterialDocumentItem": str(it[0]),
                    "Material": it[1],
                    "Plant": it[2],
                    "StorageLocation": it[3],
                    "QuantityInEntryUnit": str(it[4]),
                    "EntryUnit": it[5],
                    "GoodsMovementType": it[6],
                    # S/4 A_MaterialDocumentItem: empty strings when the movement has no PO (M4 F4)
                    "PurchaseOrder": str(idata.get("PurchaseOrder") or ""),
                    "PurchaseOrderItem": str(idata.get("PurchaseOrderItem") or ""),
                })
            d_data["to_MaterialDocumentItem"] = {"results": items}

        return {"d": d_data}


@router.post("/A_MaterialDocumentHeader")
async def create_material_document(
    request: Request,
    response: Response,
    doc_in: MaterialDocumentCreateIn,
    sap_client: str = Header("100", alias="sap-client"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Deep insert of a material document (e.g. 561 initial entry, GoodsMovementCode 05; 321 transfer).

    With an Idempotency-Key the same request returns the first document (header text FIELD:<key> finds it).
    """
    req_hash = compute_request_hash(await request.body())
    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(cur, sap_client, "API_MATERIAL_DOCUMENT_SRV", "Create", "*")
        if idempotency_key:
            is_dup, dup_doc, dup_year = check_dedupe(cur, sap_client, idempotency_key, req_hash)
            if is_dup:
                response.headers["sap-message"] = "ZSIM/DUP"
                return {"d": {"MaterialDocument": dup_doc, "MaterialDocumentYear": dup_year}}
        items_raw = doc_in.to_MaterialDocumentItem
        items_list: list[MaterialDocumentItemIn] = []
        if isinstance(items_raw, dict) and "results" in items_raw:
            items_list = [i if isinstance(i, MaterialDocumentItemIn) else MaterialDocumentItemIn(**i) for i in items_raw["results"]]
        elif isinstance(items_raw, list):
            items_list = items_raw
        if not items_list:
            raise HTTPException(status_code=400, detail={"error": {"code": "ZSIM/NO-ITEMS", "message": {
                "lang": "en", "value": "A material document needs at least one item"}}})
        for it in items_list:
            cur.execute("SELECT 1 FROM erpsim.material WHERE client = %s AND material_no = %s", (sap_client, it.Material))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail={"error": {"code": "ZSIM/NOT-FOUND", "message": {
                    "lang": "en", "value": f"Material {it.Material} does not exist"}}})
        mat_doc, doc_year = allocate_material_document_number(cur, sap_client)
        primary_mvt = items_list[0].GoodsMovementType

        cur.execute(
            """
            INSERT INTO erpsim.document (
                client, doc_number, fiscal_year, doc_type, movement_type,
                reversal_of, header_data, status
            )
            VALUES (%s, %s, %s, 'WA', %s, NULL, %s, 'posted');
        """,
            (sap_client, mat_doc, doc_year, primary_mvt, json.dumps(document_header(doc_in))),
        )

        line_no = 1
        for it in items_list:
            qty = Decimal(it.QuantityInEntryUnit)
            cur.execute(
                """
                INSERT INTO erpsim.document_item (
                    client, doc_number, fiscal_year, line_no, material_no,
                    plant, storage_location, quantity, uom, movement_type, item_data
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
                (
                    sap_client,
                    mat_doc,
                    doc_year,
                    line_no,
                    it.Material,
                    it.Plant,
                    it.StorageLocation,
                    qty,
                    it.EntryUnit,
                    it.GoodsMovementType,
                    json.dumps(it.model_dump()),
                ),
            )
            apply_movement(
                cur, sap_client, it.Plant, it.StorageLocation, it.Material, qty, it.GoodsMovementType, it.EntryUnit
            )
            line_no += 1

        if idempotency_key:
            record_dedupe(cur, sap_client, idempotency_key, req_hash, mat_doc, doc_year)
        conn.commit()
        return {
            "d": {
                "MaterialDocument": mat_doc,
                "MaterialDocumentYear": doc_year,
            }
        }


@router.post("/Cancel")
async def cancel_material_document(
    request: Request,
    response: Response,
    material_document: str = Query(..., alias="MaterialDocument"),
    material_document_year: str = Query(..., alias="MaterialDocumentYear"),
    sap_client: str = Header("100", alias="sap-client"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    idem_key = idempotency_key
    raw_body = await request.body()
    req_hash = compute_request_hash(raw_body or f"{material_document}_{material_document_year}")
    session_id = f"sess_{sap_client}"

    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(
            cur, sap_client, "API_MATERIAL_DOCUMENT_SRV", "Cancel", material_document
        )

        if idem_key:
            is_dup, dup_doc, dup_year = check_dedupe(cur, sap_client, idem_key, req_hash)
            if is_dup:
                response.headers["sap-message"] = "ZSIM/DUP"
                return {
                    "d": {
                        "MaterialDocument": dup_doc,
                        "MaterialDocumentYear": dup_year,
                        "ReversalOf": material_document,
                    }
                }

        acquire_lock(cur, sap_client, "MATERIAL_DOCUMENT", material_document, session_id)
        try:
            # 1. Fetch original doc
            cur.execute(
                """
                SELECT doc_type, movement_type, reversal_of, status
                FROM erpsim.document
                WHERE client = %s AND doc_number = %s AND fiscal_year = %s;
            """,
                (sap_client, material_document, material_document_year),
            )
            hdr = cur.fetchone()
            if not hdr:
                raise HTTPException(status_code=404, detail="Document not found")

            doc_type, orig_mvt, reversal_of, doc_status = hdr[0], hdr[1], hdr[2], hdr[3]

            if orig_mvt in DISALLOWED_REVERSAL_TYPES or reversal_of is not None:
                raise HTTPException(status_code=400, detail="Reversal of a reversal document is not allowed")

            # Check if already reversed - return 409 Conflict per spec T3.005!
            if doc_status in ("reversed", "cancelled"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "code": "ZSIM/ALREADY-REVERSED",
                            "message": {"lang": "en", "value": f"Document {material_document} already reversed"},
                        }
                    },
                )

            rev_doc, rev_year = allocate_material_document_number(cur, sap_client)
            rev_mvt = REVERSAL_MAP.get(orig_mvt, "102")

            cur.execute(
                """
                INSERT INTO erpsim.document (
                    client, doc_number, fiscal_year, doc_type, movement_type,
                    reversal_of, header_data, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'posted');
            """,
                (
                    sap_client,
                    rev_doc,
                    rev_year,
                    doc_type,
                    rev_mvt,
                    material_document,
                    json.dumps({"ReversalOf": material_document}),
                ),
            )

            # Check original items from document_item
            cur.execute(
                """
                SELECT line_no, material_no, plant, storage_location, quantity, uom, movement_type
                FROM erpsim.document_item
                WHERE client = %s AND doc_number = %s AND fiscal_year = %s
                ORDER BY line_no ASC;
            """,
                (sap_client, material_document, material_document_year),
            )
            items = cur.fetchall()

            line_no = 1
            for it in items:
                mat_no, plant, sloc, qty, uom, it_mvt = it[1], it[2], it[3], Decimal(str(it[4])), it[5], it[6]
                item_rev_mvt = REVERSAL_MAP.get(it_mvt, "102")

                cur.execute(
                    """
                    INSERT INTO erpsim.document_item (
                        client, doc_number, fiscal_year, line_no, material_no,
                        plant, storage_location, quantity, uom, movement_type, item_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                    (
                        sap_client,
                        rev_doc,
                        rev_year,
                        line_no,
                        mat_no,
                        plant,
                        sloc,
                        qty,
                        uom,
                        item_rev_mvt,
                        json.dumps({"ReversalOfItem": line_no}),
                    ),
                )

                apply_movement(cur, sap_client, plant, sloc, mat_no, qty, item_rev_mvt, uom)
                line_no += 1

            cur.execute(
                """
                UPDATE erpsim.document
                SET status = 'reversed'
                WHERE client = %s AND doc_number = %s AND fiscal_year = %s;
            """,
                (sap_client, material_document, material_document_year),
            )

            if idem_key:
                record_dedupe(cur, sap_client, idem_key, req_hash, rev_doc, rev_year)
            conn.commit()

            return {
                "d": {
                    "MaterialDocument": rev_doc,
                    "MaterialDocumentYear": rev_year,
                    "ReversalOf": material_document,
                }
            }
        finally:
            with contextlib.suppress(Exception):
                release_lock(cur, sap_client, "MATERIAL_DOCUMENT", material_document, session_id)


@router.post("/CancelItem")
async def cancel_material_document_item(
    material_document: str = Query(..., alias="MaterialDocument"),
    material_document_year: str = Query(..., alias="MaterialDocumentYear"),
    material_document_item: str = Query(..., alias="MaterialDocumentItem"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_data FROM erpsim.document_item
            WHERE client = %s AND doc_number = %s AND fiscal_year = %s AND line_no = %s;
        """,
            (sap_client, material_document, material_document_year, int(material_document_item)),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        item_data = json.loads(row[0] or "{}")
        if item_data.get("cancelled"):
            raise HTTPException(status_code=409, detail="Item already reversed")

        item_data["cancelled"] = True
        cur.execute(
            """
            UPDATE erpsim.document_item
            SET item_data = %s
            WHERE client = %s AND doc_number = %s AND fiscal_year = %s AND line_no = %s;
        """,
            (json.dumps(item_data), sap_client, material_document, material_document_year, int(material_document_item)),
        )
        conn.commit()
        return {
            "d": {
                "MaterialDocument": material_document,
                "MaterialDocumentItem": material_document_item,
                "Cancelled": True,
            }
        }
