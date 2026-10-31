"""ErpReadPort contract (M4 F4): the goods-receipt feed rows are read from the ERP, not computed.

SimAdapter against the in-process erp-sim app: a GR 101 for an ASN whose item references a PO line is read
back as a material document carrying PurchaseOrder / PurchaseOrderItem, and the on-hand is the ERP's stock
(A_MatlStkInAcctMod). The S/4 adapter conforms to the protocol and refuses (UNVERIFIED).
"""

from __future__ import annotations

import asyncio
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
