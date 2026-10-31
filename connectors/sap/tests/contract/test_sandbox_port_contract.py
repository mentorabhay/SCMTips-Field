"""M3 port contract: barcodes on the material read, movement 561, and the sandbox port (M3 contract sections 2, 3).

SimAdapter against the real erp-sim app (in-process ASGI); the S/4 adapter refuses every sandbox operation
because none of them is an SAP capability.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid

import psycopg
import pytest
from erp_sim.app import app as erp_app
from field_sap.ports.erp_port import (
    SANDBOX_NOT_SAP,
    ErpError,
    ErpErrorKind,
    ErpPort,
    ErpPostingRequest,
    ErpSandboxPort,
)
from field_sap.s4.adapter import S4Config, S4ODataAdapter
from field_sap.sim.adapter import SimAdapter

pytestmark = pytest.mark.contract

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"


def _erp(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture
def plant() -> str:
    p = "S" + "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3))
    _erp("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'Sandbox contract') ON CONFLICT DO NOTHING", (p,))
    return p


def test_both_adapters_implement_the_sandbox_port() -> None:
    assert isinstance(SimAdapter(app=erp_app), ErpSandboxPort) and isinstance(SimAdapter(app=erp_app), ErpPort)
    s4 = S4ODataAdapter(S4Config(base_url="https://s4.sample.invalid"))
    assert isinstance(s4, ErpSandboxPort) and isinstance(s4, ErpPort)


def test_s4_adapter_refuses_sandbox_operations() -> None:
    """Not an SAP capability: BUSINESS / FIELD_SANDBOX_NOT_SAP, never a call to S/4 (M3-S01)."""
    s4 = S4ODataAdapter(S4Config(base_url="https://s4.sample.invalid"))
    calls = (
        s4.create_sandbox_material("1010", "x", "EA", "123"),
        s4.create_sandbox_inbound_delivery("1010", "0001", "HOME"),
        s4.add_sandbox_inbound_delivery_item("180000001", "M", "1.000", "EA", "k"),
    )
    for coro in calls:
        with pytest.raises(ErpError) as e:
            asyncio.run(coro)
        assert (e.value.kind, e.value.code, e.value.retryable) == (ErpErrorKind.BUSINESS, SANDBOX_NOT_SAP, False)


def test_sim_sandbox_material_delivery_and_561(plant: str) -> None:
    """A barcode becomes HOME-nnnn of the plant only (idempotent on the barcode); its barcodes come back on
    list_materials; an empty sandbox delivery gains items; 561 posts an initial entry once per key."""
    sim = SimAdapter(app=erp_app)
    code = "20" + "".join(random.choices("0123456789", k=11))
    m = asyncio.run(sim.create_sandbox_material(plant, "Garden hose", "EA", code))
    assert m.created and m.material_no.startswith("HOME-") and m.barcode == code
    again = asyncio.run(sim.create_sandbox_material(plant, "another name", "EA", code))
    assert (again.material_no, again.created, again.description) == (m.material_no, False, "Garden hose")

    page = asyncio.run(sim.list_materials(plant, limit=500))
    mine = next(i for i in page.items if i.material_no == m.material_no)
    assert [(b.barcode, b.is_main) for b in mine.barcodes] == [(code, True)]
    sample = next(i for i in page.items if i.material_no == "SAMPLE-MAT-0001")
    assert [b.barcode for b in sample.barcodes] == ["SAMPLE-MAT-0001"]
    other = asyncio.run(sim.list_materials("1010", limit=500))
    assert m.material_no not in {i.material_no for i in other.items}  # a sandbox material belongs to its plant

    d = asyncio.run(sim.create_sandbox_inbound_delivery(plant, "0001", "HOME"))
    key = str(uuid.uuid4())
    i1 = asyncio.run(sim.add_sandbox_inbound_delivery_item(d.delivery_document, m.material_no, "1.000", "EA", key))
    i1b = asyncio.run(sim.add_sandbox_inbound_delivery_item(d.delivery_document, m.material_no, "1.000", "EA", key))
    i2 = asyncio.run(sim.add_sandbox_inbound_delivery_item(d.delivery_document, "SAMPLE-MAT-0002", "0.000", "EA",
                                                           str(uuid.uuid4())))
    assert (i1.item_no, i1b.item_no, i2.item_no) == ("000010", "000010", "000020")
    with pytest.raises(ErpError) as e:  # not a sandbox delivery
        asyncio.run(sim.add_sandbox_inbound_delivery_item("180000001", m.material_no, "1", "EA", str(uuid.uuid4())))
    assert e.value.kind == ErpErrorKind.BUSINESS

    req = ErpPostingRequest(idempotency_key=str(uuid.uuid4()), doc_family="InitialStockEntry", site_id="s", plant=plant,
                            posting_date="2026-10-31", header_data={"StorageLocation": "0001", "Sandbox": True},
                            items=({"Material": m.material_no, "QuantityInEntryUnit": "4.000", "EntryUnit": "EA"},))
    r1 = asyncio.run(sim.post_initial_stock_entry(req))
    r2 = asyncio.run(sim.post_initial_stock_entry(req))
    assert r1.document_number and r1.document_number == r2.document_number
    assert asyncio.run(sim.find_by_idempotency_key(req.idempotency_key)).document_number == r1.document_number
    assert _erp("SELECT quantity FROM erpsim.stock WHERE plant = %s AND material_no = %s", (plant, m.material_no)) == [(4,)]
    assert _erp("SELECT movement_type, header_data->>'sandbox' FROM erpsim.document WHERE doc_number = %s",
                (r1.document_number,)) == [("561", "true")]
