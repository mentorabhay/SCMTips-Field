"""The two upsert rows of a goods receipt (handover 01a), built from what the ERP says.

1. Stock, per (item, location): ``{"item_code", "location_code", "as_of", "on_hand_qty"}`` where ``on_hand_qty`` is
   the ERP's on-hand AFTER the receipt (absolute, not the delta), read through ErpReadPort.read_stock.
2. The PO line, per PO line received: ``{"kind": "PO", "ref": "<PO>-<item>", "item_code", "location_code", "qty",
   "due_date", "status": "received"}`` where ``qty`` is the quantity this receipt posted for the line.

Assumptions (the handover gives one example row each): ``as_of`` and ``due_date`` are the posting date of the
material document; the PO item is sent without leading zeros (``4500001234-10``); a receipt item without a PO
reference gives a stock row but no PO row. Several items of one receipt are aggregated per row key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from field_sap.ports.erp_port import ErpReadPort, MaterialDocument

from field_worker.core_feeds.codes import CodeMap

GR_MOVEMENT = "101"
StockKey = tuple[str, str, str | None]  # (material, plant, storage location or None for the plant total)


@dataclass(frozen=True)
class FeedRows:
    inventory: list[dict[str, Any]]
    open_supply: list[dict[str, Any]]
    unreferenced_items: int


def number(q: Decimal) -> int | float:
    """JSON number: integral quantities as integers (``420``), others as decimals."""
    return int(q) if q == q.to_integral_value() else float(q)


def po_ref(po: str, item: str) -> str:
    return f"{po}-{item.lstrip('0') or '0'}"


def stock_keys(doc: MaterialDocument, codes: CodeMap) -> list[StockKey]:
    """The on-hand reads a receipt needs, one per stock row."""
    keys: list[StockKey] = []
    for it in doc.items:
        if it.movement_type != GR_MOVEMENT:
            continue
        _loc, per_sloc = codes.location(it.plant, it.storage_location)
        key: StockKey = (it.material, it.plant, it.storage_location if per_sloc else None)
        if key not in keys:
            keys.append(key)
    return keys


def build_rows(doc: MaterialDocument, on_hand: Mapping[StockKey, Decimal], codes: CodeMap) -> FeedRows:
    as_of = doc.posting_date or datetime.now(UTC).date().isoformat()
    inventory: dict[tuple[str, str], dict[str, Any]] = {}
    supply: dict[str, dict[str, Any]] = {}
    supply_qty: dict[str, Decimal] = {}
    unreferenced = 0
    for it in doc.items:
        if it.movement_type != GR_MOVEMENT:
            continue
        item_code = codes.item(it.material)
        loc, per_sloc = codes.location(it.plant, it.storage_location)
        key: StockKey = (it.material, it.plant, it.storage_location if per_sloc else None)
        inventory[(item_code, loc)] = {"item_code": item_code, "location_code": loc, "as_of": as_of,
                                       "on_hand_qty": number(on_hand[key])}
        if not it.purchase_order:
            unreferenced += 1
            continue
        ref = po_ref(it.purchase_order, it.purchase_order_item)
        supply_qty[ref] = supply_qty.get(ref, Decimal("0")) + it.quantity
        supply[ref] = {"kind": "PO", "ref": ref, "item_code": item_code, "location_code": loc,
                       "qty": number(supply_qty[ref]), "due_date": as_of, "status": "received"}
    return FeedRows(list(inventory.values()), list(supply.values()), unreferenced)


async def read_rows(port: ErpReadPort, doc_number: str, fiscal_year: str,
                    codes: CodeMap) -> tuple[MaterialDocument, FeedRows]:
    """Read the posted document and the on-hand after it from the ERP, then build the rows."""
    doc = await port.read_material_document(doc_number, fiscal_year)
    on_hand = {k: await port.read_stock(k[0], k[1], k[2]) for k in stock_keys(doc, codes)}
    return doc, build_rows(doc, on_hand, codes)
