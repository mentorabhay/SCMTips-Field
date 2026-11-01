"""API_INBOUND_DELIVERY_SRV Implementation (Task T3.001).

Implements:
- A_InbDeliveryHeader / A_InbDeliveryItem reads
- PATCH of ActualDeliveryQuantity with ETag
- Function imports: PostGoodsReceipt (mvt 101, material doc 4900000000+, status 'C')
- Function imports: PutawayItem / PutawayDelivery

M5 (simulator extension, not S/4): PATCH A_InbDeliveryItem may carry YY1_QualityQuantity and
YY1_QualityStorageLocation: that part of the item's actual quantity is posted 101 to the quality storage location
(e.g. 101Q of plant 1010, "Quality Inspection Holding"; it must exist in the delivery's plant), the rest 101 to the
delivery's storage location, as two items of the same material document (item_data YY1_FieldQuality true on the
quality one). Divergence from S/4 (UNVERIFIED): S/4's inbound delivery item has no such fields; a real system splits
the delivery item per storage location, or receives into stock type "quality inspection" (QM inspection lot) in
the same storage location. The S/4 adapter does not post this yet (field_sap/s4/adapter.py).
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
from erp_sim.numbering import allocate_material_document_number
from erp_sim.stock import apply_movement

router = APIRouter(prefix="/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV", tags=["Inbound Delivery"])


class PatchItemBody(BaseModel):
    ActualDeliveryQuantity: str | float | None = None
    StorageBin: str | None = None
    # M3 soft pegging (sandbox deliveries only): the delivery quantity becomes what was counted.
    OriginalDeliveryQuantity: str | float | None = None
    # M5 (simulator extension): flagged units of the actual quantity, posted to the quality storage location.
    YY1_QualityQuantity: str | float | None = None
    YY1_QualityStorageLocation: str | None = None


def generate_item_etag(delivery_document: str, item_no: str, actual_qty: Any) -> str:
    return f'W/"{delivery_document}-{item_no}-{str(actual_qty)}"'


@router.get("/A_InbDeliveryHeader")
async def list_inbound_deliveries(
    filter_query: str | None = Query(None, alias="$filter"),
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(cur, sap_client, "API_INBOUND_DELIVERY_SRV", "Query", "*")

        query = """
            SELECT delivery_document, plant, storage_location, status, header_data, last_change_date_time
            FROM erpsim.inbound_delivery
            WHERE client = %s
        """
        params: list[Any] = [sap_client]

        if filter_query:
            import re
            m_plant = re.search(r"(?:ReceivingPlant|plant)\s+eq\s+'([^']+)'", filter_query, re.IGNORECASE)
            if m_plant:
                query += " AND plant = %s"
                params.append(m_plant.group(1))
            m_sloc = re.search(r"(?:StorageLocation|storage_location)\s+eq\s+'([^']+)'", filter_query, re.IGNORECASE)
            if m_sloc:
                query += " AND storage_location = %s"
                params.append(m_sloc.group(1))

        query += " ORDER BY delivery_document ASC;"
        cur.execute(query, tuple(params))
        results = []
        for hdr in cur.fetchall():
            doc_no = hdr[0]
            d_data: dict[str, Any] = {
                "DeliveryDocument": doc_no,
                "ReceivingPlant": hdr[1],
                "StorageLocation": hdr[2],
                "OverallGoodsMovementStatus": "C" if hdr[3] in ("posted", "completed", "C") else "A",
                "OverallGoodsReceiptStatus": "C" if hdr[3] in ("posted", "completed", "C") else "A",
                "HeaderData": hdr[4],
                "Supplier": (hdr[4] or {}).get("Supplier") or (hdr[4] or {}).get("Vendor", "")
                if isinstance(hdr[4], dict) else "",
                "LastChangeDateTime": hdr[5].isoformat() if hdr[5] else None,
            }
            if expand and "to_DeliveryDocumentItem" in expand:
                cur.execute(
                    """
                    SELECT item_no, material_no, delivery_qty, actual_qty, uom, status
                    FROM erpsim.inbound_delivery_item
                    WHERE client = %s AND delivery_document = %s
                    ORDER BY item_no ASC;
                    """,
                    (sap_client, doc_no),
                )
                items = []
                for row in cur.fetchall():
                    items.append({
                        "__metadata": {
                            "etag": generate_item_etag(doc_no, row[0], row[3]),
                        },
                        "DeliveryDocument": doc_no,
                        "DeliveryDocumentItem": row[0],
                        "Material": row[1],
                        "ActualDeliveryQuantity": str(row[2]),
                        "ActualGoodsMovementQty": str(row[3]),
                        "DeliveryQuantityUnit": row[4],
                        "ItemStatus": row[5],
                    })
                d_data["to_DeliveryDocumentItem"] = {"results": items}
            results.append(d_data)

    return {"d": {"results": results}}


@router.get("/A_InbDeliveryHeader('{delivery_document}')")
async def get_inbound_delivery(
    delivery_document: str,
    expand: str | None = Query(None, alias="$expand"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        await evaluate_faults(
            cur, sap_client, "API_INBOUND_DELIVERY_SRV", "Read", delivery_document
        )

        cur.execute(
            """
                SELECT delivery_document, plant, storage_location, status, header_data
                FROM erpsim.inbound_delivery
                WHERE client = %s AND delivery_document = %s;
            """,
            (sap_client, delivery_document),
        )
        hdr = cur.fetchone()
        if not hdr:
            # Auto-provision SAMPLE 180000123 if accessed
            if delivery_document == "180000123":
                cur.execute(
                    """
                    INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)
                    VALUES (%s, %s, '1010', '101A', 'open', %s)
                    ON CONFLICT DO NOTHING;
                """,
                    (sap_client, delivery_document, json.dumps({"Vendor": "SAMPLE-VENDOR-01"})),
                )
                cur.execute(
                    """
                    INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty, actual_qty, uom, status)
                    VALUES (%s, %s, '000010', 'SAMPLE-MAT-0001', 24.000, 0.000, 'EA', 'open')
                    ON CONFLICT DO NOTHING;
                """,
                    (sap_client, delivery_document),
                )
                conn.commit()
                hdr = (delivery_document, "1010", "101A", "open", json.dumps({"Vendor": "SAMPLE-VENDOR-01"}))
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
            "ReceivingPlant": hdr[1],
            "StorageLocation": hdr[2],
            "OverallGoodsMovementStatus": "C" if hdr[3] in ("posted", "completed", "C") else "A",
            "OverallGoodsReceiptStatus": "C" if hdr[3] in ("posted", "completed", "C") else "A",
            "HeaderData": hdr[4],
        }

        if expand and "to_DeliveryDocumentItem" in expand:
            cur.execute(
                """
                    SELECT item_no, material_no, delivery_qty, actual_qty, uom, status
                    FROM erpsim.inbound_delivery_item
                    WHERE client = %s AND delivery_document = %s
                    ORDER BY item_no ASC;
                """,
                (sap_client, delivery_document),
            )
            items = []
            for row in cur.fetchall():
                items.append({
                    "__metadata": {
                        "etag": generate_item_etag(hdr[0], row[0], row[3]),
                    },
                    "DeliveryDocument": hdr[0],
                    "DeliveryDocumentItem": row[0],
                    "Material": row[1],
                    "ActualDeliveryQuantity": str(row[2]),
                    "ActualGoodsMovementQty": str(row[3]),
                    "DeliveryQuantityUnit": row[4],
                    "ItemStatus": row[5],
                })
            d_data["to_DeliveryDocumentItem"] = {"results": items}

    return {"d": d_data}


@router.get("/A_InbDeliveryItem(DeliveryDocument='{delivery_document}',DeliveryDocumentItem='{item_no}')")
async def get_inbound_delivery_item(
    delivery_document: str,
    item_no: str,
    response: Response,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT item_no, material_no, delivery_qty, actual_qty, uom, status
                FROM erpsim.inbound_delivery_item
                WHERE client = %s AND delivery_document = %s AND item_no = %s;
            """,
            (sap_client, delivery_document, item_no),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        etag = generate_item_etag(delivery_document, item_no, row[3])
        response.headers["ETag"] = etag
        return {
            "d": {
                "__metadata": {"etag": etag},
                "DeliveryDocument": delivery_document,
                "DeliveryDocumentItem": row[0],
                "Material": row[1],
                "ActualDeliveryQuantity": str(row[2]),
                "ActualGoodsMovementQty": str(row[3]),
                "DeliveryQuantityUnit": row[4],
                "ItemStatus": row[5],
            }
        }


@router.patch("/A_InbDeliveryItem(DeliveryDocument='{delivery_document}',DeliveryDocumentItem='{item_no}')")
async def patch_inbound_delivery_item(
    delivery_document: str,
    item_no: str,
    body: PatchItemBody,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    SELECT item_no, material_no, delivery_qty, actual_qty, uom, status
                    FROM erpsim.inbound_delivery_item
                    WHERE client = %s AND delivery_document = %s AND item_no = %s;
                """,
                (sap_client, delivery_document, item_no),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found")

            current_etag = generate_item_etag(delivery_document, item_no, row[3])
            if if_match and if_match != "*" and if_match != current_etag:
                raise HTTPException(status_code=412, detail="Precondition Failed: ETag mismatch")

            new_qty = Decimal(str(body.ActualDeliveryQuantity)) if body.ActualDeliveryQuantity is not None else row[3]
            deliv_qty = row[2]
            if body.OriginalDeliveryQuantity is not None:
                cur.execute("SELECT header_data FROM erpsim.inbound_delivery WHERE client = %s AND delivery_document = %s",
                            (sap_client, delivery_document))
                head = cur.fetchone()
                if not (head and isinstance(head[0], dict) and head[0].get("sandbox")):
                    raise HTTPException(status_code=400, detail={"error": {"code": "ZSIM/NOT-SANDBOX", "message": {
                        "lang": "en", "value": "The delivery quantity is changed only on sandbox deliveries"}}})
                deliv_qty = Decimal(str(body.OriginalDeliveryQuantity))
            cur.execute(
                """
                    UPDATE erpsim.inbound_delivery_item
                    SET actual_qty = %s, delivery_qty = %s,
                        status = CASE WHEN status = 'open' THEN 'qty_set' ELSE status END
                    WHERE client = %s AND delivery_document = %s AND item_no = %s;
                """,
                (new_qty, deliv_qty, sap_client, delivery_document, item_no),
            )
            if body.YY1_QualityQuantity is not None:
                _set_quality(cur, sap_client, delivery_document, item_no, Decimal(str(body.YY1_QualityQuantity)),
                             (body.YY1_QualityStorageLocation or "").strip(), Decimal(str(new_qty)))
            conn.commit()

            new_etag = generate_item_etag(delivery_document, item_no, new_qty)
            response.headers["ETag"] = new_etag
            return {
                "d": {
                    "__metadata": {"etag": new_etag},
                    "DeliveryDocument": delivery_document,
                    "DeliveryDocumentItem": item_no,
                    "ActualDeliveryQuantity": str(new_qty),
                }
            }


def _bad_request(code: str, text: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": {"code": code, "message": {"lang": "en", "value": text}}})


def _set_quality(cur: Any, client: str, delivery_document: str, item_no: str, qty: Decimal, sloc: str,
                 actual: Decimal) -> None:
    """M5: the flagged part of one item and its quality storage location (validated against the plant)."""
    if qty < 0 or qty > actual:
        raise _bad_request("ZSIM/QUALITY-QTY", f"quality quantity {qty} must be between 0 and the actual {actual}")
    if qty > 0:
        cur.execute(
            "SELECT 1 FROM erpsim.storage_location s JOIN erpsim.inbound_delivery d"
            " ON d.client = s.client AND d.plant = s.plant"
            " WHERE d.client = %s AND d.delivery_document = %s AND s.storage_location = %s",
            (client, delivery_document, sloc))
        if cur.fetchone() is None:
            raise _bad_request("ZSIM/SLOC-NOT-FOUND", f"storage location {sloc!r} does not exist in the delivery's plant")
    cur.execute("UPDATE erpsim.inbound_delivery_item SET quality_qty = %s, quality_sloc = %s"
                " WHERE client = %s AND delivery_document = %s AND item_no = %s",
                (qty, sloc if qty > 0 else None, client, delivery_document, item_no))


@router.post("/PostGoodsReceipt")
async def post_goods_receipt(
    request: Request,
    response: Response,
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    sap_client: str = Header("100", alias="sap-client"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    idem_key = idempotency_key
    raw_body = await request.body()
    req_hash = compute_request_hash(raw_body or delivery_document)
    session_id = f"sess_{sap_client}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            await evaluate_faults(
                cur, sap_client, "API_INBOUND_DELIVERY_SRV", "PostGoodsReceipt", delivery_document
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
                            "OverallGoodsMovementStatus": "C",
                            "OverallGoodsReceiptStatus": "C",
                        }
                    }

            acquire_lock(cur, sap_client, "INBOUND_DELIVERY", delivery_document, session_id)
            try:
                cur.execute(
                    """
                    SELECT plant, storage_location, status, header_data
                    FROM erpsim.inbound_delivery
                    WHERE client = %s AND delivery_document = %s;
                """,
                    (sap_client, delivery_document),
                )
                hdr = cur.fetchone()
                if not hdr and delivery_document == "180000123":
                    # Auto-provision on demand
                    cur.execute(
                        """
                        INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)
                        VALUES (%s, %s, '1010', '101A', 'open', %s)
                        ON CONFLICT DO NOTHING;
                    """,
                        (sap_client, delivery_document, json.dumps({})),
                    )
                    cur.execute(
                        """
                        INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty, actual_qty, uom, status)
                        VALUES (%s, %s, '000010', 'SAMPLE-MAT-0001', 24.000, 24.000, 'EA', 'open')
                        ON CONFLICT DO NOTHING;
                    """,
                        (sap_client, delivery_document),
                    )
                    conn.commit()
                    hdr = ("1010", "101A", "open", {})

                if not hdr:
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

                plant, sloc, status, deliv_head = hdr
                gr_head: dict[str, Any] = {"DeliveryDocument": delivery_document}
                for flag in ("sandbox", "simulated"):  # M3: a sandbox site's receipt says so in its document
                    if isinstance(deliv_head, dict) and deliv_head.get(flag):
                        gr_head[flag] = True
                if status in ("posted", "completed", "C"):
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "code": "ZSIM/ALREADY-POSTED",
                                "message": {
                                    "lang": "en",
                                    "value": f"Delivery {delivery_document} is already posted",
                                },
                            }
                        },
                    )

                doc_no, doc_year = allocate_material_document_number(cur, sap_client)

                cur.execute(
                    """
                    SELECT item_no, material_no, delivery_qty, actual_qty, uom, status,
                           purchase_order, purchase_order_item, quality_qty, quality_sloc
                    FROM erpsim.inbound_delivery_item
                    WHERE client = %s AND delivery_document = %s
                    ORDER BY item_no;
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
                    VALUES (%s, %s, %s, 'WE', '101', NULL, %s, 'posted');
                """,
                    (
                        sap_client,
                        doc_no,
                        doc_year,
                        json.dumps(gr_head),
                    ),
                )

                line_no = 1
                for item in items:
                    item_no, mat_no, deliv_qty, act_qty, uom, item_status, po_no, po_item, q_qty, q_sloc = item
                    # A PATCHed quantity always wins, including 0 (nothing received); an item never
                    # PATCHed receives its delivery quantity (S/4 default).
                    qty_to_post = Decimal(str(act_qty if item_status == "qty_set" else deliv_qty))
                    if qty_to_post == 0:
                        continue
                    # M5: the flagged part goes to the quality storage location (simulator extension, see above)
                    quality = min(Decimal(str(q_qty or 0)), qty_to_post) if q_sloc else Decimal(0)
                    for part_sloc, part_qty, part_flag in ((sloc, qty_to_post - quality, False),
                                                           (q_sloc, quality, True)):
                        if part_qty <= 0:
                            continue
                        apply_movement(cur, sap_client, plant, part_sloc, mat_no, part_qty, "101", uom)
                        cur.execute(
                            """
                            INSERT INTO erpsim.document_item (
                                client, doc_number, fiscal_year, line_no, material_no,
                                plant, storage_location, quantity, uom, movement_type, item_data
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '101', %s);
                        """,
                            (
                                sap_client,
                                doc_no,
                                doc_year,
                                line_no,
                                mat_no,
                                plant,
                                part_sloc,
                                part_qty,
                                uom,
                                # M4 F4: the PO line of an ASN item travels into the GR item (S/4 does the same)
                                json.dumps({"DeliveryItem": item_no,
                                            **({"PurchaseOrder": po_no, "PurchaseOrderItem": po_item or ""}
                                               if po_no else {}),
                                            **({"YY1_FieldQuality": True} if part_flag else {})}),
                            ),
                        )
                        line_no += 1
                    cur.execute(
                        """
                        UPDATE erpsim.inbound_delivery_item
                        SET actual_qty = %s, status = 'received'
                        WHERE client = %s AND delivery_document = %s AND item_no = %s;
                    """,
                        (qty_to_post, sap_client, delivery_document, item_no),
                    )

                cur.execute(
                    """
                    UPDATE erpsim.inbound_delivery
                    SET status = 'completed'
                    WHERE client = %s AND delivery_document = %s;
                """,
                    (sap_client, delivery_document),
                )

                if idem_key:
                    record_dedupe(cur, sap_client, idem_key, req_hash, doc_no, doc_year)
                conn.commit()

                return {
                    "d": {
                        "MaterialDocument": doc_no,
                        "MaterialDocumentYear": doc_year,
                        "DeliveryDocument": delivery_document,
                        "OverallGoodsMovementStatus": "C",
                        "OverallGoodsReceiptStatus": "C",
                    }
                }
            finally:
                with contextlib.suppress(Exception):
                    release_lock(cur, sap_client, "INBOUND_DELIVERY", delivery_document, session_id)


@router.post("/PutawayItem")
async def putaway_item(
    delivery_document: str = Query(..., alias="DeliveryDocument"),
    item_no: str = Query(..., alias="DeliveryDocumentItem"),
    storage_bin: str = Query(..., alias="StorageBin"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    UPDATE erpsim.inbound_delivery_item
                    SET status = 'putaway'
                    WHERE client = %s AND delivery_document = %s AND item_no = %s;
                """,
                (sap_client, delivery_document, item_no),
            )
            conn.commit()
            return {
                "d": {
                    "DeliveryDocument": delivery_document,
                    "DeliveryDocumentItem": item_no,
                    "StorageBin": storage_bin,
                    "PutawayStatus": "C",
                }
            }
