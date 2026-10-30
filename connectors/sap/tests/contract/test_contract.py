"""ErpPort contract suite (T1.060 / TC1.148 / FR1.050).

Runs the port scenarios against SimAdapter talking to the real erp-sim app (in-process ASGI, real
erp-sim Postgres schema). The same scenarios are meant to run against S4ODataAdapter once it is
implemented; it currently raises NotImplementedError and is UNVERIFIED (docs/META_FIELD.md).
No in-memory FakeAdapter exists yet, so TC1.148 is only half covered.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest
from erp_sim.app import app as erp_app
from field_sap.ports.erp_port import ErpPort, ErpPostingRequest
from field_sap.sim.adapter import SimAdapter

pytestmark = pytest.mark.contract

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"


@pytest.fixture
def world() -> dict[str, str]:
    plant = f"C{uuid.uuid4().hex[:3].upper()}"
    deliv = f"18{random.randint(10_000_000, 99_999_999)}"
    mat = f"CT-{uuid.uuid4().hex[:8].upper()}"
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'Contract plant')", (plant,))
        cur.execute(
            "INSERT INTO erpsim.storage_location (client, plant, storage_location, name) VALUES ('100', %s, '0001', 'SL')",
            (plant,),
        )
        cur.execute(
            "INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES ('100', %s, 'Contract mat', 'EA')",
            (mat,),
        )
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
            " VALUES ('100', %s, %s, '0001', 'open')",
            (deliv, plant),
        )
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery_item"
            " (client, delivery_document, item_no, material_no, delivery_qty, actual_qty, uom, status)"
            " VALUES ('100', %s, '000010', %s, 5, 0, 'EA', 'open')",
            (deliv, mat),
        )
    return {"plant": plant, "deliv": deliv, "mat": mat}


def _stock(plant: str, mat: str) -> Decimal:
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s", (plant, mat)
        )
        row = cur.fetchone()
        return Decimal(row[0]) if row else Decimal(0)


def _req(key: str, family: str, plant: str, header: dict[str, object]) -> ErpPostingRequest:
    return ErpPostingRequest(
        idempotency_key=key, doc_family=family, site_id="contract", plant=plant,
        posting_date=datetime.now(UTC).strftime("%Y-%m-%d"), header_data=header, items=(),
    )


@pytest.mark.parametrize("make", [lambda: SimAdapter(app=erp_app)], ids=["sim"])
def test_tc1_148_goods_receipt_is_idempotent_findable_and_reversible(make: Callable[[], ErpPort], world: dict[str, str]) -> None:
    port: ErpPort = make()
    key = str(uuid.uuid4())

    async def run() -> None:
        assert await port.find_by_idempotency_key(key) is None
        before = _stock(world["plant"], world["mat"])
        gr = await port.post_inbound_goods_receipt(_req(key, "GoodsReceipt", world["plant"], {"DeliveryDocument": world["deliv"]}))
        assert gr.document_number and gr.fiscal_year
        assert _stock(world["plant"], world["mat"]) == before + 5
        again = await port.post_inbound_goods_receipt(_req(key, "GoodsReceipt", world["plant"], {"DeliveryDocument": world["deliv"]}))
        assert (again.document_number, again.fiscal_year) == (gr.document_number, gr.fiscal_year)
        assert _stock(world["plant"], world["mat"]) == before + 5, "replay must not post twice"
        found = await port.find_by_idempotency_key(key)
        assert found is not None and found.document_number == gr.document_number
        rev = await port.cancel_material_document(
            _req(str(uuid.uuid4()), "Cancellation", world["plant"],
                 {"MaterialDocument": gr.document_number, "MaterialDocumentYear": gr.fiscal_year})
        )
        assert rev.document_number and rev.document_number != gr.document_number
        assert _stock(world["plant"], world["mat"]) == before

    asyncio.run(run())


@pytest.mark.parametrize("make", [lambda: SimAdapter(app=erp_app)], ids=["sim"])
def test_tc1_148_list_materials_pages_real_master_data(make: Callable[[], ErpPort], world: dict[str, str]) -> None:
    port: ErpPort = make()

    async def run() -> None:
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(1000):
            page = await port.list_materials(plant=world["plant"], cursor=cursor, limit=50)
            assert all(m.plant == world["plant"] for m in page.items)
            seen += [m.material_no for m in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
        assert world["mat"] in seen
        assert len(seen) == len(set(seen)) == page.total_count
        empty = await port.list_materials(plant="NOPE", limit=10)
        assert empty.items == () and empty.next_cursor is None

    asyncio.run(run())
