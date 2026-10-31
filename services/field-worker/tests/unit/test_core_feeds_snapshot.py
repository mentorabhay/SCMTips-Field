"""M4 Q10: the ERP's stock and open purchase orders reach the core's two feeds as a snapshot of what changed.

The rows are read from the in-process erp-sim app through ErpReadPort (SimAdapter: list_stock and
list_purchase_order_items), staged by ErpSnapshotFeed in field.core_feed_delivery and delivered by the receipts'
publisher over HTTP (ASGI) to the stand-in core's feed receivers (tools/fake-core, a dev double), which verify the
signature. Against the real core: `stack smoke --erp-feed` with FIELD_CORE_TARGET=core.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import psycopg
import pytest
from erp_sim.app import app as erpsim_app
from fake_core.app import app as core_app
from fake_core.standin.state import StandInState
from field_sap.sim.adapter import SimAdapter
from field_worker.core_feeds import CodeMap, CoreFeedPublisher, ErpSnapshotFeed, FeedConfig
from field_worker.posting import DATABASE_URL, PostingQueueWorker, enqueue_posting_job

ERPSIM = os.getenv("ERPSIM_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim")
ADMIN = os.environ["FIELD_ADMIN_DATABASE_URL"]
STANDIN: StandInState = core_app.state.standin
SIM = SimAdapter(app=erpsim_app)
INV_SECRET, SUP_SECRET = "inv-" + uuid.uuid4().hex, "sup-" + uuid.uuid4().hex


@pytest.fixture(autouse=True)
def _feeds(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(STANDIN.feeds, "s-inv", ("inventory", INV_SECRET))
    monkeypatch.setitem(STANDIN.feeds, "s-sup", ("open_supply", SUP_SECRET))
    yield


def cfg(**kw: Any) -> FeedConfig:
    base: dict[str, Any] = {"inventory_url": "http://core/v1/inbound/feeds/s-inv", "inventory_secret": INV_SECRET,
                            "supply_url": "http://core/v1/inbound/feeds/s-sup", "supply_secret": SUP_SECRET,
                            "max_attempts": 3, "backoff_s": 0.0, "backoff_max_s": 0.0}
    return FeedConfig(**{**base, **kw})


def to_standin(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=core_app), base_url="http://core", timeout=timeout)


def answering(answer: Callable[[httpx.Request], int]) -> Callable[[float], httpx.AsyncClient]:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(answer(req), json={"accepted": True})
    return lambda t: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=t)


def site(tenant: str, plant: str, mode: str = "production") -> str:
    sid = str(uuid.uuid4())
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, erp_storage_locations, status,"
                  " mode) VALUES (%s, %s, %s, 'snapshot test', 'warehouse', %s, ARRAY['0001'], 'active', %s)",
                  (sid, tenant, f"S-{uuid.uuid4().hex[:8].upper()}", plant, mode))
    return sid


def erp(plant: str, stock: dict[str, int], pos: list[tuple[str, str, int, str]]) -> None:
    """erp-sim master data as `stack seed-core-export` loads it: stock in 0001, PO lines (po, material, qty, status)."""
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 't') ON CONFLICT DO NOTHING",
                    (plant,))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES ('100', %s, '0001', 't') ON CONFLICT DO NOTHING", (plant,))
        for m, q in {**stock, **{p[1]: 0 for p in pos if p[1] not in stock}}.items():
            cur.execute("INSERT INTO erpsim.material (client, material_no, description, base_uom)"
                        " VALUES ('100', %s, 't', 'EA') ON CONFLICT DO NOTHING", (m,))
            if m in stock:
                cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity)"
                            " VALUES ('100', %s, '0001', %s, %s)", (plant, m, q))
        for po, m, q, status in pos:
            cur.execute("INSERT INTO erpsim.purchase_order (client, purchase_order, supplier)"
                        " VALUES ('100', %s, 'SUP-S02')", (po,))
            cur.execute("INSERT INTO erpsim.purchase_order_item (client, purchase_order, item_no, material_no, plant,"
                        " storage_location, order_qty, delivery_date, status, ext)"
                        " VALUES ('100', %s, '10', %s, %s, '0001', %s, '2026-11-20', %s, %s)",
                        (po, m, plant, q, status, json.dumps({"lane_code": "L02"})))


def asn(material: str, qty: int, plant: str, po: str | None) -> str:
    deliv = f"18{uuid.uuid4().int % 10**8:08d}"
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
                    " VALUES ('100', %s, %s, '0001', 'open')", (deliv, plant))
        cur.execute("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no,"
                    " delivery_qty, actual_qty, uom, status, purchase_order, purchase_order_item)"
                    " VALUES ('100', %s, '000010', %s, %s, 0, 'EA', 'open', %s, %s)",
                    (deliv, material, qty, po, "10" if po else None))
    return deliv


async def post_gr(tenant: str, deliv: str, plant: str) -> None:
    enqueue_posting_job(tenant_id=tenant, queue_key=f"IBD:{deliv}", doc_family="GoodsReceipt", site_id="WH1",
                        plant=plant, header_data={"DeliveryDocument": deliv}, items=[], ref_doc_no=deliv)
    assert await PostingQueueWorker(erp_port=SIM, db_url=DATABASE_URL).process_one_job(tenant) is True


def deliveries(tenant: str) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("SELECT id::text, feed, status, row_count, body, doc_number, skip_reason FROM field.core_feed_delivery"
                    " WHERE tenant_id = %s ORDER BY created_at, id", (tenant,))
        cols = ("id", "feed", "status", "row_count", "body", "doc_number", "skip_reason")
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def pushed(feed: str, items: set[str]) -> list[dict[str, Any]]:
    fid = "s-inv" if feed == "inventory" else "s-sup"
    return [r for p in STANDIN.pushes if p.feed_id == fid for r in p.rows if r.get("item_code") in items]


def codes(tag: str) -> tuple[str, str, str, str, str]:
    plant = f"P{tag[:5]}"
    return plant, f"CP-A{tag}", f"CP-B{tag}", f"RM-C{tag}", f"PO-26-{tag}"


async def test_m4_c15_snapshot_sends_the_erps_stock_and_open_pos_then_only_what_changed() -> None:
    tenant, tag = str(uuid.uuid4()), uuid.uuid4().hex[:6].upper()
    plant, a, b, c, po = codes(tag)
    sid = site(tenant, plant)
    erp(plant, {a: 1680, b: 560}, [(po, c, 1600, "in_transit")])
    snap = ErpSnapshotFeed(SIM, DATABASE_URL, cfg(), CodeMap())
    assert snap.plants()[tenant] == {plant: sid}
    got = await snap.snapshot_tenant(tenant, {plant: sid})
    assert (got["stock_rows"], got["po_rows"], got["deliveries"], got["unchanged"]) == (2, 1, 2, 0)
    staged = deliveries(tenant)
    assert {(d["feed"], d["row_count"], d["doc_number"], d["status"]) for d in staged} == {
        ("inventory", 2, f"SNAPSHOT-{plant}", "pending"), ("open_supply", 1, f"SNAPSHOT-{plant}", "pending")}
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin, codes=CodeMap())
    assert await pub.deliver_due(tenant) == 2
    assert {d["status"] for d in deliveries(tenant)} == {"delivered"}
    stock = {r["item_code"]: r for r in pushed("inventory", {a, b})}
    assert {k: (r["location_code"], r["on_hand_qty"]) for k, r in stock.items()} == {a: (plant, 1680), b: (plant, 560)}
    assert len(stock[a]["as_of"]) == 10
    [line] = pushed("open_supply", {c})
    assert line == {"kind": "PO", "ref": po, "item_code": c, "location_code": plant, "qty": 1600,
                    "due_date": "2026-11-20", "status": "in_transit", "supplier_code": "SUP-S02", "lane_code": "L02"}
    # the same ERP again: nothing staged
    again = await snap.snapshot_tenant(tenant, {plant: sid})
    assert (again["deliveries"], again["unchanged"]) == (0, 3)
    # one change in the ERP (a receipt without a PO): only that stock row is staged
    await post_gr(tenant, asn(b, 40, plant, None), plant)
    third = await snap.snapshot_tenant(tenant, {plant: sid})
    assert (third["stock_rows"], third["po_rows"], third["deliveries"]) == (1, 0, 1)
    assert json.loads(deliveries(tenant)[-1]["body"])["rows"][0]["on_hand_qty"] == 600


async def test_m4_c15_a_received_po_line_is_sent_received_and_an_older_open_retry_never_reopens_it() -> None:
    tenant, tag = str(uuid.uuid4()), uuid.uuid4().hex[:6].upper()
    plant, _, _, c, po = codes(tag)
    sid = site(tenant, plant)
    erp(plant, {}, [(po, c, 150, "open")])
    snap = ErpSnapshotFeed(SIM, DATABASE_URL, cfg(backoff_s=3600, backoff_max_s=3600), CodeMap())
    await snap.snapshot_tenant(tenant, {plant: sid})
    failing = CoreFeedPublisher(SIM, DATABASE_URL, cfg(backoff_s=3600, backoff_max_s=3600),
                                client_factory=answering(lambda r: 503), codes=CodeMap())
    assert await failing.deliver_due(tenant) == 1  # the snapshot's "open 150" row fails and waits an hour
    # the goods receipt of the whole line: the receipt rows are staged and delivered first
    await post_gr(tenant, asn(c, 150, plant, po), plant)
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin, codes=CodeMap())
    assert await pub.stage_new_receipts(tenant) == 1
    assert await pub.deliver_due(tenant) == 2
    with psycopg.connect(ADMIN, autocommit=True) as conn:  # the old retry becomes due
        conn.execute("UPDATE field.core_feed_delivery SET next_attempt_at = NOW() WHERE tenant_id = %s"
                     " AND status = 'pending'", (tenant,))
    assert await pub.deliver_due(tenant) == 1
    old = deliveries(tenant)[0]
    assert (old["feed"], old["status"], old["skip_reason"]) == ("open_supply", "skipped", "superseded")
    assert [r["status"] for r in pushed("open_supply", {c})] == ["received"]  # the "open" row never reached the core
    # the next snapshot reads the line as received; it differs from the receipt's row only by supplier and lane
    nxt = await snap.snapshot_tenant(tenant, {plant: sid})
    assert nxt["po_rows"] == 1
    row = json.loads(deliveries(tenant)[-1]["body"])["rows"][0]
    gr_row = pushed("open_supply", {c})[0]
    assert row == {**gr_row, "supplier_code": "SUP-S02", "lane_code": "L02"}
    assert (row["status"], row["qty"]) == ("received", 150)
    assert (await snap.snapshot_tenant(tenant, {plant: sid}))["deliveries"] == 0


async def test_m4_c15_sandbox_plants_are_never_read_and_rows_come_in_bounded_batches() -> None:
    tenant, tag = str(uuid.uuid4()), uuid.uuid4().hex[:6].upper()
    plant, home = f"P{tag[:5]}", f"H{tag[:5]}"
    sid = site(tenant, plant)
    site(tenant, home, mode="sandbox")
    shared = f"X{tag[:5]}"
    site(tenant, shared)
    site(tenant, shared, mode="sandbox")  # a production site on a plant a sandbox site uses: not read either
    snap = ErpSnapshotFeed(SIM, DATABASE_URL, cfg(snapshot_batch=2), CodeMap())
    assert snap.plants()[tenant] == {plant: sid}
    erp(plant, {f"RM-{i}{tag}": 10 + i for i in range(5)}, [])
    got = await snap.snapshot_tenant(tenant, {plant: sid})
    assert (got["stock_rows"], got["deliveries"]) == (5, 3)
    assert sorted(d["row_count"] for d in deliveries(tenant)) == [1, 2, 2]  # one read: the chunks share a time


async def test_m4_c15_nothing_without_both_feeds_or_with_interval_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from field_worker.worker import FieldWorker

    assert (await ErpSnapshotFeed(SIM, DATABASE_URL, cfg(supply_url=""), CodeMap()).run_once())["tenants"] == 0
    assert (await ErpSnapshotFeed(SIM, DATABASE_URL, cfg(snapshot_interval_s=0), CodeMap()).run_once())["tenants"] == 0
    for v in ("FIELD_CORE_INVENTORY_FEED_URL", "FIELD_CORE_SUPPLY_FEED_URL", "FIELD_CORE_SNAPSHOT_INTERVAL_S"):
        monkeypatch.delenv(v, raising=False)
    assert FieldWorker(erp_port=SIM).erp_snapshot is None
    monkeypatch.setenv("FIELD_CORE_INVENTORY_FEED_URL", "http://core/v1/inbound/feeds/a")
    monkeypatch.setenv("FIELD_CORE_SUPPLY_FEED_URL", "http://core/v1/inbound/feeds/b")
    w = FieldWorker(erp_port=SIM)
    assert isinstance(w.erp_snapshot, ErpSnapshotFeed) and w.erp_snapshot.config.snapshot_interval_s == 900
    monkeypatch.setenv("FIELD_CORE_SNAPSHOT_INTERVAL_S", "0")
    assert FieldWorker(erp_port=SIM).erp_snapshot is None


async def test_m4_c15_only_the_named_tenants_and_never_an_ambiguous_row() -> None:
    tenant, other, tag = str(uuid.uuid4()), str(uuid.uuid4()), uuid.uuid4().hex[:6].upper()
    plant, mapped = f"P{tag[:5]}", f"M{tag[:5]}"
    a, b = f"CP-A{tag}", f"CP-B{tag}"
    site(other, f"O{tag[:5]}")
    sid = site(tenant, plant)
    sid2 = site(tenant, mapped)
    only = ErpSnapshotFeed(SIM, DATABASE_URL, cfg(snapshot_tenants=(tenant,)), CodeMap())
    assert set(only.plants()) == {tenant}
    erp(plant, {a: 5, b: 7}, [])
    erp(mapped, {"SAMPLE-X" + tag: 9}, [])
    # a code map that sends the second plant's material to the first plant's item and location: two figures, one key
    from types import MappingProxyType

    codes_ = CodeMap(materials=MappingProxyType({"SAMPLE-X" + tag: a}), locations=MappingProxyType({mapped: plant}))
    snap = ErpSnapshotFeed(SIM, DATABASE_URL, cfg(), codes_)
    got = await snap.snapshot_tenant(tenant, {plant: sid, mapped: sid2})
    assert (got["conflicts"], got["stock_rows"]) == (1, 1)
    [d] = deliveries(tenant)
    assert [r["item_code"] for r in json.loads(d["body"])["rows"]] == [b]  # a's two figures: neither is sent
