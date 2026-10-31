"""M4 F4: a posted goods receipt (101) reaches the core's two feeds as signed upsert rows (handover 01a).

The receipt is posted by the real posting worker through the SimAdapter into the in-process erp-sim app; the
rows are read back from erp-sim through ErpReadPort; delivery goes over HTTP (ASGI) to the stand-in core's feed
receivers (tools/fake-core, a dev double), which verify the signature and the 5-minute timestamp. Against the real
core this is UNVERIFIED (the core is not deployed).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from erp_sim.app import app as erpsim_app
from fake_core.app import app as core_app
from fake_core.standin.state import StandInState
from field_sap.ports.erp_port import MaterialDocument, MaterialDocumentItem
from field_sap.sim.adapter import SimAdapter
from field_worker.core_feeds import (
    CodeMap,
    CoreFeedPublisher,
    FeedConfig,
    build_rows,
    load_code_map,
    sign,
    verify,
)
from field_worker.core_feeds.publisher import backoff_s
from field_worker.posting import DATABASE_URL, PostingQueueWorker, enqueue_posting_job
from hypothesis import given, settings
from hypothesis import strategies as st

ERPSIM = os.getenv("ERPSIM_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim")
STANDIN: StandInState = core_app.state.standin
SIM = SimAdapter(app=erpsim_app)
INV_SECRET, SUP_SECRET = "inv-" + uuid.uuid4().hex, "sup-" + uuid.uuid4().hex


@pytest.fixture(autouse=True)
def _feeds(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(STANDIN.feeds, "t-inv", ("inventory", INV_SECRET))
    monkeypatch.setitem(STANDIN.feeds, "t-sup", ("open_supply", SUP_SECRET))
    yield


def cfg(**kw: Any) -> FeedConfig:
    base: dict[str, Any] = {"inventory_url": "http://core/v1/inbound/feeds/t-inv", "inventory_secret": INV_SECRET,
                            "supply_url": "http://core/v1/inbound/feeds/t-sup", "supply_secret": SUP_SECRET,
                            "max_attempts": 3, "backoff_s": 0.0, "backoff_max_s": 0.0}
    return FeedConfig(**{**base, **kw})


def to_standin(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=core_app), base_url="http://core", timeout=timeout)


def asn(material: str, qty: int, po: str | None, po_item: str | None = "10", plant: str = "1010",
        sloc: str = "101A", sandbox: bool = False) -> str:
    deliv = f"18{uuid.uuid4().int % 10**8:08d}"
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        for sql, args in (
            ("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 't') ON CONFLICT DO NOTHING", (plant,)),
            ("INSERT INTO erpsim.storage_location (client, plant, storage_location, name) VALUES ('100', %s, %s, 't')"
             " ON CONFLICT DO NOTHING", (plant, sloc)),
            ("INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES ('100', %s, 't', 'EA')"
             " ON CONFLICT DO NOTHING", (material,)),
            ("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status,"
             " header_data) VALUES ('100', %s, %s, %s, 'open', %s)",
             (deliv, plant, sloc, json.dumps({"sandbox": True} if sandbox else {}))),
            ("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
             " actual_qty, uom, status, purchase_order, purchase_order_item)"
             " VALUES ('100', %s, '000010', %s, %s, 0, 'EA', 'open', %s, %s)", (deliv, material, qty, po, po_item)),
        ):
            cur.execute(sql, args)
    return deliv


async def post_gr(tenant: str, deliv: str, plant: str = "1010") -> None:
    enqueue_posting_job(tenant_id=tenant, queue_key=f"IBD:{deliv}", doc_family="GoodsReceipt", site_id="WH1",
                        plant=plant, header_data={"DeliveryDocument": deliv}, items=[], ref_doc_no=deliv)
    assert await PostingQueueWorker(erp_port=SIM, db_url=DATABASE_URL).process_one_job(tenant) is True


def deliveries(tenant: str) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("SELECT feed, status, attempts, body, last_status, skip_reason, last_error, event_id::text"
                    " FROM field.core_feed_delivery WHERE tenant_id = %s ORDER BY feed", (tenant,))
        cols = ("feed", "status", "attempts", "body", "last_status", "skip_reason", "last_error", "event_id")
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def pushes_for(item: str) -> list[dict[str, Any]]:
    return [{"feed": p.feed_id, "rows": p.rows, "key": p.idempotency_key} for p in STANDIN.pushes
            if any(r.get("item_code") == item for r in p.rows)]


async def test_m4_c04_gr_101_delivers_two_signed_rows_read_from_the_erp() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-F{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 120, "4500001234"))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin)
    assert tenant in pub.tenants()
    assert await pub.stage_new_receipts(tenant) == 1
    assert await pub.deliver_due(tenant) == 2
    rows = {d["feed"]: d for d in deliveries(tenant)}
    assert {f: (d["status"], d["attempts"], d["last_status"]) for f, d in rows.items()} == {
        "inventory": ("delivered", 1, 200), "open_supply": ("delivered", 1, 200)}
    on_hand = await SIM.read_stock(material, "1010")
    got = pushes_for(material)
    inv = next(p for p in got if p["feed"] == "t-inv")["rows"]
    sup = next(p for p in got if p["feed"] == "t-sup")["rows"]
    assert inv == [{"item_code": material, "location_code": "1010", "as_of": inv[0]["as_of"],
                    "on_hand_qty": int(on_hand)}] and on_hand == Decimal("120")
    assert sup == [{"kind": "PO", "ref": "4500001234-10", "item_code": material, "location_code": "1010",
                    "qty": 120, "due_date": inv[0]["as_of"], "status": "received"}]
    event = rows["inventory"]["event_id"]
    assert {p["key"] for p in got} == {f"{event}:inventory", f"{event}:open_supply"}
    # idempotent on the event id: staging and delivering again sends nothing new
    assert await pub.stage_new_receipts(tenant) == 0 and await pub.deliver_due(tenant) == 0
    assert len(pushes_for(material)) == 2 and len(deliveries(tenant)) == 2


async def test_m4_c04_nothing_without_both_urls() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-N{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 3, "4500000001"))
    for c in (FeedConfig(), cfg(supply_url=""), cfg(inventory_url="")):
        assert c.enabled is False
        assert await CoreFeedPublisher(SIM, DATABASE_URL, c, client_factory=to_standin).run_once() == (0, 0)
    assert await CoreFeedPublisher(SIM, DATABASE_URL, cfg(supply_secret=""), client_factory=to_standin).run_once() == (
        0, 0)  # a URL without its secret is never sent unsigned
    assert cfg(supply_secret="").problems() == ["FIELD_CORE_SUPPLY_FEED_SECRET"]
    assert deliveries(tenant) == [] and pushes_for(material) == []


async def test_m4_c04_retry_with_backoff_then_dead_letter_and_permanent_refusal() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-R{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 7, "4500000002", "20"))
    calls: list[str] = []

    def answering(code_for: Callable[[str], int]) -> Callable[[float], httpx.AsyncClient]:
        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req.url.path)
            assert req.headers["X-SCMTIPS-Signature"].startswith("sha256=")
            code = code_for(req.url.path)
            if code < 0:
                raise httpx.ConnectError("core down", request=req)
            return httpx.Response(code, json={"code": "x"})
        return lambda t: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=t)

    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(max_attempts=3),
                            client_factory=answering(lambda p: 503 if p.endswith("t-inv") else 422))
    await pub.stage_new_receipts(tenant)
    await pub.deliver_due(tenant)
    rows = {d["feed"]: d for d in deliveries(tenant)}
    assert (rows["open_supply"]["status"], rows["open_supply"]["attempts"]) == ("dead", 1)  # 422: never retried
    assert (rows["inventory"]["status"], rows["inventory"]["attempts"]) == ("pending", 1)
    pub._client_factory = answering(lambda p: -1)  # network error: retried
    await pub.deliver_due(tenant)
    pub._client_factory = answering(lambda p: 503)
    await pub.deliver_due(tenant)
    inv = next(d for d in deliveries(tenant) if d["feed"] == "inventory")
    assert (inv["status"], inv["attempts"], inv["last_status"]) == ("dead", 3, 503)
    assert "HTTP 503" in inv["last_error"]
    assert await pub.deliver_due(tenant) == 0  # dead letters are not tried again
    assert calls.count("/v1/inbound/feeds/t-sup") == 1


async def test_m4_c04_a_retry_waits_for_its_backoff() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-W{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 2, None))
    down = CoreFeedPublisher(SIM, DATABASE_URL, cfg(backoff_s=60, backoff_max_s=60),
                             client_factory=lambda t: httpx.AsyncClient(
                                 transport=httpx.MockTransport(lambda r: httpx.Response(500)), timeout=t))
    await down.stage_new_receipts(tenant)
    assert await down.deliver_due(tenant) == 1
    assert await down.deliver_due(tenant) == 0  # not due for about a minute
    rows = {d["feed"]: d for d in deliveries(tenant)}
    assert rows["open_supply"]["status"] == "skipped" and rows["open_supply"]["skip_reason"] == "no PO reference"
    assert backoff_s(1, 60, 600, lambda: 0.0) == pytest.approx(48) and backoff_s(9, 5, 600, lambda: 1.0) == 600
    assert backoff_s(3, 5, 600, lambda: 0.5) == pytest.approx(20)


async def test_m4_c04_sandbox_receipts_are_skipped_unless_switched_on() -> None:
    tenant, material = str(uuid.uuid4()), f"HOME-T{uuid.uuid4().hex[:5].upper()}"
    await post_gr(tenant, asn(material, 1, None, sandbox=True))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin)
    await pub.stage_new_receipts(tenant)
    assert {(d["status"], d["skip_reason"]) for d in deliveries(tenant)} == {("skipped", "sandbox receipt")}
    tenant2, material2 = str(uuid.uuid4()), f"HOME-U{uuid.uuid4().hex[:5].upper()}"
    await post_gr(tenant2, asn(material2, 1, "4500000003", sandbox=True))
    on = CoreFeedPublisher(SIM, DATABASE_URL, cfg(include_sandbox=True), client_factory=to_standin)
    await on.stage_new_receipts(tenant2)
    await on.deliver_due(tenant2)
    assert {d["status"] for d in deliveries(tenant2)} == {"delivered"}


async def test_m4_c04_core_codes_from_the_mapping_file(tmp_path: Path) -> None:
    tenant, material = str(uuid.uuid4()), f"SAMPLE-T{uuid.uuid4().hex[:5].upper()}"
    f = tmp_path / "codes.json"
    f.write_text(json.dumps({"materials": {material: "rm-307"}, "locations": {"1010": "PLANT-GOA"}}), encoding="utf-8")
    await post_gr(tenant, asn(material, 5, "4500001234", "000010"))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(code_map_path=str(f)), client_factory=to_standin)
    await pub.stage_new_receipts(tenant)
    await pub.deliver_due(tenant)
    bodies = {d["feed"]: json.loads(d["body"]) for d in deliveries(tenant)}
    assert bodies["inventory"][0]["item_code"] == "RM-307" and bodies["inventory"][0]["location_code"] == "PLANT-GOA"
    assert bodies["open_supply"][0]["ref"] == "4500001234-10"
    assert {d["status"] for d in deliveries(tenant)} == {"delivered"}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"materials": {"X": ""}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_code_map(str(bad))


def test_m4_c04_rows_aggregate_and_storage_location_mapping() -> None:
    doc = MaterialDocument("4900000001", "2026", "2026-11-03", (
        MaterialDocumentItem("1", "M1", "1010", "101A", Decimal("4"), "EA", "101", "4500000009", "10"),
        MaterialDocumentItem("2", "M1", "1010", "101A", Decimal("2.5"), "EA", "101", "4500000009", "10"),
        MaterialDocumentItem("3", "M2", "1010", "102B", Decimal("1"), "EA", "101"),
    ))
    codes = CodeMap(locations=__import__("types").MappingProxyType({"1010/102B": "GOA-B"}))
    rows = build_rows(doc, {("M1", "1010", None): Decimal("16.5"), ("M2", "1010", "102B"): Decimal("1")}, codes)
    assert rows.inventory == [
        {"item_code": "M1", "location_code": "1010", "as_of": "2026-11-03", "on_hand_qty": 16.5},
        {"item_code": "M2", "location_code": "GOA-B", "as_of": "2026-11-03", "on_hand_qty": 1}]
    assert rows.open_supply == [{"kind": "PO", "ref": "4500000009-10", "item_code": "M1", "location_code": "1010",
                                 "qty": 6.5, "due_date": "2026-11-03", "status": "received"}]
    assert rows.unreferenced_items == 1


def test_m4_c04_worker_builds_the_publisher_only_with_both_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    from field_worker.worker import FieldWorker

    for v in ("FIELD_CORE_INVENTORY_FEED_URL", "FIELD_CORE_SUPPLY_FEED_URL"):
        monkeypatch.delenv(v, raising=False)
    assert FieldWorker(erp_port=SIM).core_feeds is None
    monkeypatch.setenv("FIELD_CORE_INVENTORY_FEED_URL", "http://core/v1/inbound/feeds/a")
    monkeypatch.setenv("FIELD_CORE_SUPPLY_FEED_URL", "http://core/v1/inbound/feeds/b")
    assert isinstance(FieldWorker(erp_port=SIM).core_feeds, CoreFeedPublisher)


@settings(max_examples=80, deadline=None)
@given(st.binary(max_size=300), st.text(min_size=1, max_size=40), st.integers(min_value=-200, max_value=200))
def test_m4_c04_property_signature_verifies_and_detects_tampering(body: bytes, secret: str, skew: int) -> None:
    """The signature is HMAC-SHA256(secret, ts + "." + body): it verifies within 5 minutes, and any change to the
    body, the timestamp or the secret breaks it."""
    now = time.time()
    ts = int(now) + skew
    sig = sign(secret, ts, body)
    assert verify(secret, ts, body, sig, now=now)
    assert not verify(secret, ts, body + b"x", sig, now=now)
    assert not verify(secret + "x", ts, body, sig, now=now)
    assert not verify(secret, ts + 1, body, sig, now=now)
    assert not verify(secret, ts, body, sig, now=now + 301 + abs(skew))
