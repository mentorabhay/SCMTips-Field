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
    # ref = the PO number exactly (core reply TO_FIELD section 4), unmapped here: erp-sim's PO number unchanged
    assert sup == [{"kind": "PO", "ref": "4500001234", "item_code": material, "location_code": "1010",
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


async def test_m4_c18_only_the_configured_tenants_receipts_reach_the_core() -> None:
    """K5 finding: the feeds belong to one core organisation, so another Field tenant's receipts are never sent."""
    mine, other = str(uuid.uuid4()), str(uuid.uuid4())
    m_mine, m_other = f"RM-T{uuid.uuid4().hex[:6].upper()}", f"RM-O{uuid.uuid4().hex[:6].upper()}"
    await post_gr(mine, asn(m_mine, 5, "4500000011"))
    await post_gr(other, asn(m_other, 7, "4500000012"))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(feed_tenants=(mine,), core_target="core"),
                            client_factory=to_standin)
    assert mine in pub.tenants() and other not in pub.tenants()
    await pub.run_once()
    assert len(pushes_for(m_mine)) == 2 and pushes_for(m_other) == [] and deliveries(other) == []
    # FIELD_CORE_FEED_TENANTS unset: the snapshot's tenants decide (one organisation for both)
    assert cfg(snapshot_tenants=(mine,)).receipt_tenants == (mine,)
    assert cfg(feed_tenants=(other,), snapshot_tenants=(mine,)).receipt_tenants == (other,)


async def test_m4_c18_the_real_core_needs_its_tenant_named_else_nothing_is_sent() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-R{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 4, "4500000013"))
    unnamed = cfg(core_target="core")
    assert unnamed.problems() == ["FIELD_CORE_FEED_TENANTS"]
    assert await CoreFeedPublisher(SIM, DATABASE_URL, unnamed, client_factory=to_standin).run_once() == (0, 0)
    assert deliveries(tenant) == [] and pushes_for(material) == []
    # back-compat: the stand-in core (or no target) with no tenants named still serves every tenant
    assert cfg(core_target="standin").problems() == [] and cfg().receipt_tenants == ()
    assert tenant in CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin).tenants()


def test_m4_c18_feed_tenants_and_target_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CORE_FEED_TENANTS", " a , b ,")
    monkeypatch.setenv("FIELD_CORE_SNAPSHOT_TENANTS", "c")
    monkeypatch.setenv("FIELD_CORE_TARGET", "Core")
    c = FeedConfig.from_env()
    assert c.feed_tenants == ("a", "b") and c.snapshot_tenants == ("c",) and c.core_target == "core"
    assert c.receipt_tenants == ("a", "b")


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
    bodies = {d["feed"]: json.loads(d["body"])["rows"] for d in deliveries(tenant)}
    assert bodies["inventory"][0]["item_code"] == "RM-307" and bodies["inventory"][0]["location_code"] == "PLANT-GOA"
    assert bodies["open_supply"][0]["ref"] == "4500001234"  # no purchase_orders entry: the erp-sim number as it is
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
    assert rows.open_supply == [{"kind": "PO", "ref": "4500000009", "item_code": "M1", "location_code": "1010",
                                 "qty": 6.5, "due_date": "2026-11-03", "status": "received"}]
    assert rows.unreferenced_items == 1 and rows.unmapped_purchase_orders == ("4500000009",)


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


# --- the core's reply (TO_FIELD, 31 Oct, section 4): PO ref, {"rows"}, 409 = delivered, stale stock dropped ----------

def capture(answer: Callable[[httpx.Request], int], seen: list[httpx.Request]) -> Callable[[float], httpx.AsyncClient]:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(answer(req), json={"code": "duplicate"} if answer(req) == 409 else {"accepted": True})
    return lambda t: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=t)


def stage_delivery(tenant: str, body: str, status: str = "pending", age_s: int = 0) -> str:
    """A field.core_feed_delivery row as the publisher stages it (``age_s`` seconds ago)."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("INSERT INTO field.core_feed_delivery (tenant_id, event_id, feed, doc_number, fiscal_year, body,"
                    " row_count, status, max_attempts, created_at, delivered_at)"
                    " VALUES (%s, %s, 'inventory', '4900000001', '2026', %s, 1, %s, 3,"
                    " NOW() - make_interval(secs => %s), CASE WHEN %s = 'delivered' THEN NOW() END) RETURNING id::text",
                    (tenant, str(uuid.uuid4()), body, status, age_s, status))
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def delivery(tenant: str, row_id: str) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("SELECT status, skip_reason, body, row_count, attempts, last_status FROM field.core_feed_delivery"
                    " WHERE id = %s", (row_id,))
        r = cur.fetchone()
    assert r is not None
    return dict(zip(("status", "skip_reason", "body", "row_count", "attempts", "last_status"), r, strict=True))


def test_m4_c10_signature_is_pinned_to_the_cores_format() -> None:
    """sha256= + hex HMAC-SHA256(secret, "<timestamp>.<body>") (TO_FIELD section 4), pinned to a fixed vector."""
    body = b'{"rows":[{"item_code":"RM-307"}]}'
    assert sign("feed-secret", 1730419200, body) == (
        "sha256=dbcc9f43e840730125a4eae0bb1547c495fad85f10b17e02443337c8c602f213")


async def test_m4_c10_po_ref_is_the_cores_po_number_through_the_mapping(tmp_path: Path) -> None:
    tenant, material = str(uuid.uuid4()), f"SAMPLE-P{uuid.uuid4().hex[:5].upper()}"
    po = f"45{uuid.uuid4().int % 10**8:08d}"
    f = tmp_path / "codes.json"
    f.write_text(json.dumps({"materials": {material: "RM-307"}, "locations": {"1010": "PLANT-GOA"},
                             "purchase_orders": {po: "PO-26-1001"}}), encoding="utf-8")
    assert load_code_map(str(f)).purchase_order(po) == ("PO-26-1001", True)
    assert load_code_map(str(f)).purchase_order("4599999999") == ("4599999999", False)
    await post_gr(tenant, asn(material, 6, po, "000020"))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(code_map_path=str(f)), client_factory=to_standin)
    await pub.stage_new_receipts(tenant)
    await pub.deliver_due(tenant)
    sup = next(json.loads(d["body"])["rows"] for d in deliveries(tenant) if d["feed"] == "open_supply")
    assert sup == [{"kind": "PO", "ref": "PO-26-1001", "item_code": "RM-307", "location_code": "PLANT-GOA", "qty": 6,
                    "due_date": sup[0]["due_date"], "status": "received"}]
    assert STANDIN.open_supply[("PO", "PO-26-1001", "RM-307")]["qty"] == 6  # the core's line key
    assert {d["status"] for d in deliveries(tenant)} == {"delivered"}


async def test_m4_c10_body_is_a_rows_object_signed_with_requested_with() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-B{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 2, "4500000011"))
    seen: list[httpx.Request] = []
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=capture(lambda r: 200, seen))
    await pub.stage_new_receipts(tenant)
    assert await pub.deliver_due(tenant) == 2
    for req in seen:
        doc = json.loads(req.content)
        assert set(doc) == {"rows"} and isinstance(doc["rows"], list) and doc["rows"]
        assert req.headers["X-Requested-With"] == "lr"
        secret = INV_SECRET if req.url.path.endswith("t-inv") else SUP_SECRET
        assert req.headers["X-SCMTIPS-Signature"] == sign(secret, int(req.headers["X-SCMTIPS-Timestamp"]), req.content)


async def test_m4_c10_a_409_duplicate_is_delivered_and_never_retried() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-D{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 4, "4500000012"))
    seen: list[httpx.Request] = []
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(max_attempts=8), client_factory=capture(lambda r: 409, seen))
    await pub.stage_new_receipts(tenant)
    assert await pub.deliver_due(tenant) == 2
    assert {(d["feed"], d["status"], d["attempts"], d["last_status"]) for d in deliveries(tenant)} == {
        ("inventory", "delivered", 1, 409), ("open_supply", "delivered", 1, 409)}
    assert await pub.deliver_due(tenant) == 0 and len(seen) == 2


async def test_m4_c10_the_stand_in_answers_409_for_a_resent_body_and_field_counts_it_delivered() -> None:
    """A lost reply: the core took the push, Field did not hear it and sends the same body again -> 409 duplicate."""
    tenant, material = str(uuid.uuid4()), f"RM-L{uuid.uuid4().hex[:6].upper()}"
    await post_gr(tenant, asn(material, 9, "4500000013"))
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=to_standin)
    await pub.stage_new_receipts(tenant)
    await pub.deliver_due(tenant)
    with psycopg.connect(DATABASE_URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("UPDATE field.core_feed_delivery SET status = 'pending', next_attempt_at = NOW()"
                    " WHERE tenant_id = %s AND feed = 'inventory'", (tenant,))
    assert await pub.deliver_due(tenant) == 1
    inv = next(d for d in deliveries(tenant) if d["feed"] == "inventory")
    assert (inv["status"], inv["attempts"], inv["last_status"]) == ("delivered", 2, 409)
    assert [p["rows"] for p in pushes_for(material) if p["feed"] == "t-inv"][0] == json.loads(inv["body"])["rows"]
    assert [p.duplicate for p in STANDIN.pushes if p.feed_id == "t-inv" and any(
        r.get("item_code") == material for r in p.rows)] == [False, True]


async def test_m4_c10_a_stale_stock_retry_is_dropped_once_a_newer_row_is_delivered() -> None:
    tenant, material = str(uuid.uuid4()), f"RM-S{uuid.uuid4().hex[:6].upper()}"
    seen: list[httpx.Request] = []

    def first_stock_fails(req: httpx.Request) -> int:
        rows = json.loads(req.content)["rows"]
        return 503 if req.url.path.endswith("t-inv") and rows[0]["on_hand_qty"] == 3 else 200

    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=capture(first_stock_fails, seen))
    await post_gr(tenant, asn(material, 3, "4500000014"))
    assert await pub.stage_new_receipts(tenant) == 1  # on-hand read from the ERP now: 3
    await post_gr(tenant, asn(material, 4, "4500000015"))
    assert await pub.stage_new_receipts(tenant) == 1  # on-hand 7
    assert await pub.deliver_due(tenant) == 4
    stock = [json.loads(r.content)["rows"][0]["on_hand_qty"] for r in seen if r.url.path.endswith("t-inv")]
    assert stock == [3, 7]  # sent in posting order
    seen.clear()
    assert await pub.deliver_due(tenant) == 1  # the retry of on-hand 3 is claimed ...
    assert seen == []  # ... and dropped: on-hand 7 for the same item and plant is already delivered
    inv = sorted((d for d in deliveries(tenant) if d["feed"] == "inventory"), key=lambda d: d["status"])
    assert [(d["status"], d["skip_reason"]) for d in inv] == [("delivered", None), ("skipped", "superseded")]
    assert await pub.deliver_due(tenant) == 0


async def test_m4_c10_only_the_superseded_rows_of_a_stock_retry_are_dropped_and_old_bodies_are_wrapped() -> None:
    tenant = str(uuid.uuid4())
    old = stage_delivery(tenant, json.dumps([  # staged before 1 Nov: a bare array
        {"item_code": "RM-307", "location_code": "PLANT-GOA", "as_of": "2026-11-01", "on_hand_qty": 5},
        {"item_code": "RM-308", "location_code": "PLANT-GOA", "as_of": "2026-11-01", "on_hand_qty": 2}]), age_s=60)
    stage_delivery(tenant, json.dumps({"rows": [
        {"item_code": "rm-307", "location_code": "plant-goa", "as_of": "2026-11-01", "on_hand_qty": 9}]}),
        status="delivered", age_s=30)
    seen: list[httpx.Request] = []
    pub = CoreFeedPublisher(SIM, DATABASE_URL, cfg(), client_factory=capture(lambda r: 200, seen))
    assert await pub.deliver_due(tenant) == 1
    assert [json.loads(r.content) for r in seen] == [{"rows": [
        {"item_code": "RM-308", "location_code": "PLANT-GOA", "as_of": "2026-11-01", "on_hand_qty": 2}]}]
    d = delivery(tenant, old)
    assert (d["status"], d["row_count"], json.loads(d["body"])) == ("delivered", 1, json.loads(seen[0].content))
    assert verify(INV_SECRET, int(seen[0].headers["X-SCMTIPS-Timestamp"]), seen[0].content,
                  seen[0].headers["X-SCMTIPS-Signature"])
