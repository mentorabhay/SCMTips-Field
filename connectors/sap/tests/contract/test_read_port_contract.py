"""ErpReadPort contract (M4 F4): the goods-receipt feed rows are read from the ERP, not computed.

SimAdapter against the in-process erp-sim app: a GR 101 for an ASN whose item references a PO line is read
back as a material document carrying PurchaseOrder / PurchaseOrderItem, and the on-hand is the ERP's stock
(A_MatlStkInAcctMod). The S/4 adapter conforms to the protocol and refuses (UNVERIFIED).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from decimal import Decimal

import psycopg
import pytest
from erp_sim.app import app as erpsim_app
from field_sap.ports.erp_port import ErpError, ErpPostingRequest, ErpReadPort
from field_sap.s4.adapter import S4Config, S4ODataAdapter
from field_sap.sim.adapter import SimAdapter

ERPSIM = os.getenv("ERPSIM_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim")


def _asn(material: str, qty: int, po: str | None, po_item: str | None, plant: str = "1010", sloc: str = "101A") -> str:
    deliv = f"18{uuid.uuid4().int % 10**8:08d}"
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'test') ON CONFLICT DO NOTHING",
                    (plant,))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES ('100', %s, %s, 'test') ON CONFLICT DO NOTHING", (plant, sloc))
        cur.execute("INSERT INTO erpsim.material (client, material_no, description, base_uom)"
                    " VALUES ('100', %s, 'contract test', 'EA') ON CONFLICT DO NOTHING", (material,))
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
                    " VALUES ('100', %s, %s, %s, 'open')", (deliv, plant, sloc))
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
            " actual_qty, uom, status, purchase_order, purchase_order_item)"
            " VALUES ('100', %s, '000010', %s, %s, 0, 'EA', 'open', %s, %s)",
            (deliv, material, qty, po, po_item),
        )
    return deliv


def _gr(adapter: SimAdapter, deliv: str) -> tuple[str, str]:
    res = asyncio.run(adapter.post_inbound_goods_receipt(ErpPostingRequest(
        idempotency_key=f"rp_{uuid.uuid4().hex[:12]}", doc_family="GoodsReceipt", site_id="WH1", plant="1010",
        posting_date="2026-11-03", header_data={"DeliveryDocument": deliv}, items=())))
    return res.document_number, res.fiscal_year


@pytest.mark.contract
def test_m4_c03_gr_document_carries_the_po_line_and_stock_is_the_erps() -> None:
    sim = SimAdapter(app=erpsim_app)
    assert isinstance(sim, ErpReadPort)
    material = f"RM-T{uuid.uuid4().hex[:6].upper()}"
    before = asyncio.run(sim.read_stock(material, "1010"))
    assert before == Decimal("0")
    doc_no, year = _gr(sim, _asn(material, 120, "4500001234", "10"))
    doc = asyncio.run(sim.read_material_document(doc_no, year))
    assert doc.document_number == doc_no and len(doc.posting_date) == 10 and doc.sandbox is False
    [item] = doc.items
    assert (item.material, item.plant, item.storage_location, item.quantity, item.movement_type) == (
        material, "1010", "101A", Decimal("120.000"), "101")
    assert (item.purchase_order, item.purchase_order_item) == ("4500001234", "10")
    # a second receipt into another storage location of the same plant: the plant total is the sum
    doc2, year2 = _gr(sim, _asn(material, 5, None, None, sloc="102B"))
    assert asyncio.run(sim.read_stock(material, "1010")) == Decimal("125")
    assert asyncio.run(sim.read_stock(material, "1010", "101A")) == Decimal("120")
    [plain] = asyncio.run(sim.read_material_document(doc2, year2)).items
    assert (plain.purchase_order, plain.purchase_order_item) == ("", "")


@pytest.mark.contract
def test_m4_c03_unknown_document_and_bad_filter_are_errors() -> None:
    sim = SimAdapter(app=erpsim_app)
    with pytest.raises(ErpError):
        asyncio.run(sim.read_material_document("4999999999", "1999"))
    from fastapi.testclient import TestClient

    r = TestClient(erpsim_app).get("/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
                                   params={"$filter": "Plant eq '1010'"})
    assert r.status_code == 400


@pytest.mark.contract
def test_m4_c03_s4_adapter_conforms_and_refuses_reads() -> None:
    s4 = S4ODataAdapter(S4Config(base_url="https://s4hana.sample.corp:44300"))
    assert isinstance(s4, ErpReadPort)
    with pytest.raises(NotImplementedError):
        asyncio.run(s4.read_stock("RM-307", "PLANT-GOA"))
    with pytest.raises(NotImplementedError):
        asyncio.run(s4.read_material_document("4900000001", "2026"))


def _po(material: str, plant: str, po: str, qty: int, status: str = "open", lane: str = "L02",
        sloc: str = "0001") -> None:
    """An erp-sim purchase-order line (as `stack seed-core-export` loads it from the core's export)."""
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'test') ON CONFLICT DO NOTHING",
                    (plant,))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES ('100', %s, %s, 'test') ON CONFLICT DO NOTHING", (plant, sloc))
        cur.execute("INSERT INTO erpsim.material (client, material_no, description, base_uom)"
                    " VALUES ('100', %s, 'contract test', 'EA') ON CONFLICT DO NOTHING", (material,))
        cur.execute("INSERT INTO erpsim.purchase_order (client, purchase_order, supplier) VALUES ('100', %s, 'SUP-S02')",
                    (po,))
        cur.execute("INSERT INTO erpsim.purchase_order_item (client, purchase_order, item_no, material_no, plant,"
                    " storage_location, order_qty, uom, delivery_date, status, ext)"
                    " VALUES ('100', %s, '10', %s, %s, %s, %s, 'EA', '2026-11-20', %s, %s)",
                    (po, material, plant, sloc, qty, status, json.dumps({"lane_code": lane})))


@pytest.mark.contract
def test_m4_c15_purchase_order_lines_carry_what_was_received_and_reversals_reopen_them() -> None:
    sim = SimAdapter(app=erpsim_app)
    plant = f"P{uuid.uuid4().hex[:6].upper()}"
    material, po = f"CP-T{uuid.uuid4().hex[:6].upper()}", f"PO-T{uuid.uuid4().hex[:6].upper()}"
    _po(material, plant, po, 1600, status="in_transit")
    [line] = asyncio.run(sim.list_purchase_order_items(plant))
    assert (line.purchase_order, line.item, line.material, line.plant, line.storage_location) == (
        po, "10", material, plant, "0001")
    assert (line.order_qty, line.received_qty, line.open_qty) == (Decimal("1600"), Decimal("0"), Decimal("1600"))
    assert (line.delivery_date, line.supplier, line.status, line.lane, line.last_receipt_date) == (
        "2026-11-20", "SUP-S02", "in_transit", "L02", "")
    # a partial receipt against the PO line (an ASN item that references it), then the rest
    doc1, year1 = _gr(sim, _asn(material, 600, po, "10", plant=plant, sloc="0001"))
    [after1] = asyncio.run(sim.list_purchase_order_items(plant))
    assert (after1.received_qty, after1.open_qty, len(after1.last_receipt_date)) == (Decimal("600"), Decimal("1000"), 10)
    _gr(sim, _asn(material, 1000, po, "10", plant=plant, sloc="0001"))
    [done] = asyncio.run(sim.list_purchase_order_items(plant))
    assert (done.received_qty, done.open_qty) == (Decimal("1600"), Decimal("0"))
    # reversing the first receipt (102) opens 600 again
    asyncio.run(sim.cancel_material_document(ErpPostingRequest(
        idempotency_key=f"rv_{uuid.uuid4().hex[:12]}", doc_family="Reversal", site_id="WH1", plant=plant,
        posting_date="2026-11-03", header_data={"MaterialDocument": doc1, "MaterialDocumentYear": year1}, items=())))
    [reopened] = asyncio.run(sim.list_purchase_order_items(plant))
    assert (reopened.received_qty, reopened.open_qty) == (Decimal("1000"), Decimal("600"))


@pytest.mark.contract
def test_m4_c15_plant_stock_lists_every_material_and_storage_location_in_pages() -> None:
    sim = SimAdapter(app=erpsim_app)
    plant = f"P{uuid.uuid4().hex[:6].upper()}"
    mats = sorted(f"RM-T{uuid.uuid4().hex[:6].upper()}" for _ in range(3))
    for i, m in enumerate(mats):
        _gr(sim, _asn(m, 10 + i, None, None, plant=plant, sloc="0001"))
    _gr(sim, _asn(mats[0], 5, None, None, plant=plant, sloc="0002"))
    lines = asyncio.run(sim._pages("/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
                                   f"Plant eq '{plant}' and InventoryStockType eq '01'", page=2))
    assert [(r["Material"], r["StorageLocation"]) for r in lines] == [
        (mats[0], "0001"), (mats[0], "0002"), (mats[1], "0001"), (mats[2], "0001")]  # all pages, in order
    stock = asyncio.run(sim.list_stock(plant))
    assert {(s.material, s.storage_location): s.quantity for s in stock} == {
        (mats[0], "0001"): Decimal("10"), (mats[0], "0002"): Decimal("5"), (mats[1], "0001"): Decimal("11"),
        (mats[2], "0001"): Decimal("12")}
    from fastapi.testclient import TestClient

    r = TestClient(erpsim_app).get("/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderItem",
                                   params={"$filter": f"Material eq '{mats[0]}'"})
    assert r.status_code == 400


@pytest.mark.contract
def test_m4_c15_s4_adapter_refuses_the_snapshot_reads() -> None:
    s4 = S4ODataAdapter(S4Config(base_url="https://s4hana.sample.corp:44300"))
    assert isinstance(s4, ErpReadPort)
    with pytest.raises(NotImplementedError):
        asyncio.run(s4.list_stock("PLANT-GOA"))
    with pytest.raises(NotImplementedError):
        asyncio.run(s4.list_purchase_order_items("PLANT-GOA"))
