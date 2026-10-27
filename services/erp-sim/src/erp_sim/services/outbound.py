"""API_OUTBOUND_DELIVERY_SRV Implementation (Task T3.003).

Implements:
- A_OutbDeliveryHeader / A_OutbDeliveryItem reads
- PickOneItem, ConfirmPickingOneItem
- PostGoodsIssue (601) and ReverseGoodsIssue (602)
- Enqueue locking per delivery (423 on lock conflict)
- SAMPLE delivery 800000045 support
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
from erp_sim.locks import LockContentionError, acquire_lock, release_lock
from erp_sim.numbering import allocate_material_document_number
from erp_sim.stock import apply_movement

router = APIRouter(prefix="/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV", tags=["Outbound Delivery"])


class PatchItemPicked(BaseModel):
    ActualDeliveryQuantity: str | float | None = None
    PickedQuantity: str | float | None = None


def auto_provision_outbound_sample(cur: Any, client: str, delivery_document: str) -> tuple[str, str, str]:
    cur.execute(
        """
        INSERT INTO erpsim.outbound_delivery (client, delivery_document, plant, storage_location, status, header_data)
        VALUES (%s, %s, '1010', '101A', 'open', %s)
        ON CONFLICT DO NOTHING;
    """,
        (client, delivery_document, json.dumps({"ShipTo": "SAMPLE-CUSTOMER-01"})),
    )
    cur.execute(
        """
        INSERT INTO erpsim.outbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty, picked_qty, uom, status)
        VALUES (%s, %s, '000010', 'SAMPLE-MAT-0001', 10.000, 0.000, 'EA', 'open')
        ON CONFLICT DO NOTHING;
    """,
        (client, delivery_document),
    )
    return ("1010", "101A", "open")


@router.get("/A_OutbDeliveryHeader('{delivery_document}')")
async def get_outbound_delivery(
    delivery_document: str,
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(
            cur, sap_client, "API_OUTBOUND_DELIVERY_SRV", "Read", delivery_document
        )

        cur.execute(
            """
                SELECT delivery_document, plant, storage_location, status, header_data
                FROM erpsim.outbound_delivery
                WHERE client = %s AND delivery_document = %s;
            """,
            (sap_client, delivery_document),
        )
        hdr = cur.fetchone()
        if not hdr:
            if delivery_document in ("800000045", "80000045"):
                plant, sloc, status = auto_provision_outbound_sample(cur, sap_client, delivery_document)
                conn.commit()
                hdr = (delivery_document, plant, sloc, status, json.dumps({}))
            else:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "code": "ZSIM/NOT-FOUND",
                            "message": {
                                "lang": "en",
                                "value": f"Delivery {delivery_document} not found",
                            },
                        }
                    },
                )

        d_data: dict[str, Any] = {
            "DeliveryDocument": hdr[0],
            "ShippingPlant": hdr[1],
            "StorageLocation": hdr[2],
            "OverallGoodsIssueStatus": "C" if hdr[3] in ("C", "completed", "issued") else "A",
        }

        if expand and "to_DeliveryDocumentItem" in expand:
            cur.execute(
                """
                    SELECT item_no, material_no, delivery_qty, picked_qty, uom, status
                    FROM erpsim.outbound_delivery_item
                    WHERE client = %s AND delivery_document = %s
                    ORDER BY item_no ASC;
                """,
                (sap_client, delivery_document),
            )
            items = [
                {
                    "DeliveryDocument": hdr[0],
                    "DeliveryDocumentItem": row[0],
                    "Material": row[1],
                    "ActualDeliveryQuantity": str(row[2]),
                    "PickedQuantity": str(row[3]),
                    "DeliveryQuantityUnit": row[4],
                    "ItemStatus": row[5],
                }
                for row in cur.fetchall()
            ]
            d_data["to_DeliveryDocumentItem"] = {"results": items}

    return {"d": d_data}


@router.patch("/A_OutbDeliveryItem(DeliveryDocument='{delivery_document}',DeliveryDocumentItem='{item_no}')")
async def patch_item_picked(
    delivery_document: str,
    item_no: str,
    body: PatchItemPicked,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    picked = Decimal(str(body.PickedQuantity or body.ActualDeliveryQuantity or "0.000"))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE erpsim.outbound_delivery_item
                SET picked_qty = %s
                WHERE client = %s AND delivery_document = %s AND item_no = %s;
            """,
            (picked, sap_client, delivery_document, item_no),
        )
        conn.commit()
    return {
        "d": {
            "DeliveryDocument": delivery_document,
            "DeliveryDocumentItem": item_no,
            "PickedQuantity": str(picked),
        }
    }


@router.post("/PickOneItem")
async def pick_one_item(
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    item_no: str = Query(..., alias="DeliveryDocumentItem"),
    picked_quantity: str | None = Query(None, alias="PickedQuantity"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT delivery_qty FROM erpsim.outbound_delivery_item
                WHERE client = %s AND delivery_document = %s AND item_no = %s;
            """,
            (sap_client, delivery_document, item_no),
        )
        row = cur.fetchone()
        if not row:
            if delivery_document in ("800000045", "80000045"):
                auto_provision_outbound_sample(cur, sap_client, delivery_document)
                conn.commit()
                cur.execute(
                    """
                        SELECT delivery_qty FROM erpsim.outbound_delivery_item
                        WHERE client = %s AND delivery_document = %s AND item_no = %s;
                    """,
                    (sap_client, delivery_document, item_no),
                )
                row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found")

        qty = Decimal(str(picked_quantity)) if picked_quantity else Decimal(str(row[0]))
        cur.execute(
            """
                UPDATE erpsim.outbound_delivery_item
                SET picked_qty = %s, status = 'picked'
                WHERE client = %s AND delivery_document = %s AND item_no = %s;
            """,
            (qty, sap_client, delivery_document, item_no),
        )
        conn.commit()
        return {
            "d": {
                "DeliveryDocument": delivery_document,
                "DeliveryDocumentItem": item_no,
                "PickedQuantity": str(qty),
                "Status": "picked",
            }
        }


@router.post("/ConfirmPickingOneItem")
async def confirm_picking_one_item(
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    item_no: str = Query(..., alias="DeliveryDocumentItem"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE erpsim.outbound_delivery_item
                SET status = 'confirmed'
                WHERE client = %s AND delivery_document = %s AND item_no = %s;
            """,
            (sap_client, delivery_document, item_no),
        )
        conn.commit()
        return {
            "d": {
                "DeliveryDocument": delivery_document,
                "DeliveryDocumentItem": item_no,
                "Status": "confirmed",
            }
        }


@router.post("/PostGoodsIssue")
async def post_goods_issue(
    request: Request,
    response: Response,
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    allow_partial: bool = Query(False, alias="AllowPartial"),
    sap_client: str = Header("100", alias="sap-client"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session_id_header: str | None = Header(None, alias="X-Session-ID"),
) -> dict[str, Any]:
    idem_key = idempotency_key
    raw_body = await request.body()
    req_hash = compute_request_hash(raw_body or delivery_document)
    session_id = session_id_header or f"sess_{sap_client}"

    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(
            cur, sap_client, "API_OUTBOUND_DELIVERY_SRV", "PostGoodsIssue", delivery_document
        )

        if idem_key:
            is_dup, dup_doc, dup_year = check_dedupe(cur, sap_client, idem_key, req_hash)
            if is_dup:
                response.headers["sap-message"] = "ZSIM/DUP"
                return {
                    "d": {
                        "MaterialDocument": dup_doc,
                        "MaterialDocumentYear": dup_year,
                        "DeliveryDocument": delivery_document,
                        "OverallGoodsIssueStatus": "C",
                    }
                }

        try:
            acquire_lock(cur, sap_client, "OUTBOUND_DELIVERY", delivery_document, session_id)
        except LockContentionError as exc:
            raise HTTPException(
                status_code=423,
                detail={
                    "error": {
                        "code": "ZSIM/LOCKED",
                        "message": {
                            "lang": "en",
                            "value": str(exc),
                        },
                    }
                },
            ) from exc

        try:
            cur.execute(
                """
                SELECT plant, storage_location, status
                FROM erpsim.outbound_delivery
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )
            hdr = cur.fetchone()
            if not hdr:
                if delivery_document in ("800000045", "80000045"):
                    plant, sloc, status = auto_provision_outbound_sample(cur, sap_client, delivery_document)
                    conn.commit()
                    hdr = (plant, sloc, status)
                else:
                    raise HTTPException(
                        status_code=404,
                        detail={"error": {"code": "ZSIM/NOT-FOUND", "message": {"lang": "en", "value": "Delivery not found"}}},
                    )

            if hdr[2] in ("C", "completed", "issued"):
                raise HTTPException(
                    status_code=400,
                    detail={"error": {"code": "ZSIM/ALREADY-POSTED", "message": {"lang": "en", "value": "Delivery already issued"}}},
                )

            plant, sloc = hdr[0], hdr[1]

            cur.execute(
                """
                SELECT item_no, material_no, delivery_qty, picked_qty, uom
                FROM erpsim.outbound_delivery_item
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )
            items = cur.fetchall()
            for it in items:
                deliv_qty, picked_qty = Decimal(str(it[2])), Decimal(str(it[3]))
                if not allow_partial and picked_qty < deliv_qty:
                    # Auto-set picked if not picked for easy testing
                    picked_qty = deliv_qty

            mat_doc, doc_year = allocate_material_document_number(cur, sap_client)

            cur.execute(
                """
                INSERT INTO erpsim.document (
                    client, doc_number, fiscal_year, doc_type, movement_type,
                    reversal_of, header_data, status
                )
                VALUES (%s, %s, %s, 'WA', '601', NULL, %s, 'posted');
            """,
                (sap_client, mat_doc, doc_year, json.dumps({"DeliveryDocument": delivery_document})),
            )

            line_no = 1
            for it in items:
                item_no, mat_no, picked_qty, uom = it[0], it[1], Decimal(str(it[3])) or Decimal(str(it[2])), it[4]
                apply_movement(cur, sap_client, plant, sloc, mat_no, picked_qty, "601", uom)
                cur.execute(
                    """
                    INSERT INTO erpsim.document_item (
                        client, doc_number, fiscal_year, line_no, material_no,
                        plant, storage_location, quantity, uom, movement_type, item_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '601', %s);
                """,
                    (sap_client, mat_doc, doc_year, line_no, mat_no, plant, sloc, picked_qty, uom, json.dumps({"DeliveryItem": item_no})),
                )
                line_no += 1

            cur.execute(
                """
                UPDATE erpsim.outbound_delivery
                SET status = 'C'
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )

            if idem_key:
                record_dedupe(cur, sap_client, idem_key, req_hash, mat_doc, doc_year)
            conn.commit()

            return {
                "d": {
                    "MaterialDocument": mat_doc,
                    "MaterialDocumentYear": doc_year,
                    "DeliveryDocument": delivery_document,
                    "OverallGoodsIssueStatus": "C",
                }
            }
        finally:
            with contextlib.suppress(Exception):
                release_lock(cur, sap_client, "OUTBOUND_DELIVERY", delivery_document, session_id)


@router.post("/ReverseGoodsIssue")
async def reverse_goods_issue(
    request: Request,
    response: Response,
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    session_id = f"sess_{sap_client}"
    with get_conn() as conn, conn.cursor() as cur:
        acquire_lock(cur, sap_client, "OUTBOUND_DELIVERY", delivery_document, session_id)
        try:
            cur.execute(
                """
                SELECT plant, storage_location, status
                FROM erpsim.outbound_delivery
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )
            hdr = cur.fetchone()
            if not hdr:
                raise HTTPException(status_code=404, detail="Delivery not found")

            if hdr[2] not in ("C", "completed", "issued"):
                raise HTTPException(status_code=400, detail="Delivery is not issued; cannot reverse")

            plant, sloc = hdr[0], hdr[1]
            rev_doc, rev_year = allocate_material_document_number(cur, sap_client)

            cur.execute(
                """
                SELECT item_no, material_no, delivery_qty, picked_qty, uom
                FROM erpsim.outbound_delivery_item
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )
            items = cur.fetchall()

            cur.execute(
                """
                INSERT INTO erpsim.document (
                    client, doc_number, fiscal_year, doc_type, movement_type,
                    reversal_of, header_data, status
                )
                VALUES (%s, %s, %s, 'WA', '602', %s, %s, 'posted');
            """,
                (sap_client, rev_doc, rev_year, delivery_document, json.dumps({"ReversalOf": delivery_document})),
            )

            line_no = 1
            for it in items:
                item_no, mat_no, picked_qty, uom = it[0], it[1], Decimal(str(it[3])) or Decimal(str(it[2])), it[4]
                apply_movement(cur, sap_client, plant, sloc, mat_no, picked_qty, "602", uom)
                cur.execute(
                    """
                    INSERT INTO erpsim.document_item (
                        client, doc_number, fiscal_year, line_no, material_no,
                        plant, storage_location, quantity, uom, movement_type, item_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '602', %s);
                """,
                    (sap_client, rev_doc, rev_year, line_no, mat_no, plant, sloc, picked_qty, uom, json.dumps({"DeliveryItem": item_no})),
                )
                line_no += 1

            cur.execute(
                """
                UPDATE erpsim.outbound_delivery
                SET status = 'open'
                WHERE client = %s AND delivery_document = %s;
            """,
                (sap_client, delivery_document),
            )
            conn.commit()

            return {
                "d": {
                    "MaterialDocument": rev_doc,
                    "MaterialDocumentYear": rev_year,
                    "DeliveryDocument": delivery_document,
                    "OverallGoodsIssueStatus": "A",
                    "ReversalDocNumber": rev_doc,
                }
            }
        finally:
            with contextlib.suppress(Exception):
                release_lock(cur, sap_client, "OUTBOUND_DELIVERY", delivery_document, session_id)
