"""The ERP's stock and open purchase orders, sent to the core's two feeds as a snapshot (M4 Q10; hackathon leg I9).

The goods-receipt rows (publisher.py) tell the core what changed at a receipt. The snapshot tells it what the ERP
holds, so the core's on-hand and open supply equal the system of record's even for changes Field did not post (and
after the core's data was reloaded). Every FIELD_CORE_SNAPSHOT_INTERVAL_S (900 s; 0 = off), only when both feed URLs
are set (FeedConfig.snapshot_enabled):

1. Plants. The ERP plants of the tenant's active production sites (field.worker_erp_sites, field.site.mode), for the
   tenants FIELD_CORE_SNAPSHOT_TENANTS names (empty: every tenant). A plant that any sandbox (home / training) site
   uses is never read: sandbox stock is never sent (TO_FIELD section 4).
2. Read, through ErpReadPort (never computed): ``list_stock(plant)`` (unrestricted stock per storage location) and
   ``list_purchase_order_items(plant)`` (each PO line with what has been received against it).
3. Rows, in the core's codes (CodeMap: identity for an erp-sim seeded from the core's export, so no mapping):
   - stock, per (item, location): ``{"item_code", "location_code", "as_of": <today, UTC>, "on_hand_qty"}``, the sum
     over the plant's storage locations (or one storage location's, when the code map names it);
   - PO line, per (ref, item): ``{"kind": "PO", "ref", "item_code", "location_code", "qty", "due_date", "status",
     "supplier_code"?, "lane_code"?}``. Still open: ``qty`` = the open quantity, ``due_date`` = the schedule line's,
     ``status`` = the ERP's (open / released / in_transit). Fully received: ``qty`` = the received quantity,
     ``due_date`` = the last receipt's posting date, ``status`` ``received``: the same row the receipt sent.
   A key that two plants of the tenant produce (two ERP plants mapped to one core location, e.g. a code-mapped plant
   next to one seeded from the core's export) is ambiguous: neither row is sent, and the worker logs
   ``core_snapshot_conflict``.
4. Only what changed. A row whose values were already staged for the core (pending or delivered, by a receipt or an
   earlier snapshot, within FIELD_CORE_SNAPSHOT_RESEND_H) is left out, so a quiet ERP sends nothing and a repeat run
   is a no-op; after the resend window a row is sent again. Stock compares ``on_hand_qty`` only (a new day alone is no
   change).
5. Stage, bounded: the rows of a plant and feed are split into deliveries of at most FIELD_CORE_SNAPSHOT_BATCH rows
   in field.core_feed_delivery (doc_number ``SNAPSHOT-<plant>``, a fresh event id each), with created_at = the moment
   the ERP was read, so they take their place in the one staging order with the receipts. Delivery, signing,
   ``{"rows": [...]}``, 409 = delivered, retries, dead letters and the supersede rule are the publisher's.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import structlog
from field_sap.ports.erp_port import ErpError, ErpReadPort, PurchaseOrderLine, StockLine

from field_worker.core_feeds.codes import CodeMap, load_code_map
from field_worker.core_feeds.config import FeedConfig
from field_worker.core_feeds.publisher import ROW_KEY, body_rows, feed_body
from field_worker.core_feeds.rows import number

logger = structlog.get_logger(__name__)

SNAPSHOT_DOC = "SNAPSHOT"


def stock_rows(lines: Iterable[StockLine], codes: CodeMap, as_of: str) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], Decimal] = {}
    for ln in lines:
        loc, _per_sloc = codes.location(ln.plant, ln.storage_location)
        key = (codes.item(ln.material), loc)
        totals[key] = totals.get(key, Decimal("0")) + ln.quantity
    return [{"item_code": i, "location_code": loc, "as_of": as_of, "on_hand_qty": number(q)}
            for (i, loc), q in sorted(totals.items())]


def supply_rows(lines: Iterable[PurchaseOrderLine], codes: CodeMap, today: str) -> list[dict[str, Any]]:
    """One row per (ref, item code); several ERP lines of one PO and item are added up."""
    acc: dict[tuple[str, str], dict[str, Any]] = {}
    for ln in lines:
        ref, _mapped = codes.purchase_order(ln.purchase_order)
        item = codes.item(ln.material)
        loc, _per_sloc = codes.location(ln.plant, ln.storage_location)
        a = acc.setdefault((ref, item), {"loc": loc, "order": Decimal("0"), "received": Decimal("0"), "due": "",
                                         "last_gr": "", "status": ln.status, "supplier": ln.supplier,
                                         "lane": ln.lane})
        a["order"] += ln.order_qty
        a["received"] += ln.received_qty
        a["due"] = min((d for d in (a["due"], ln.delivery_date) if d), default="")
        a["last_gr"] = max(a["last_gr"], ln.last_receipt_date)
    out: list[dict[str, Any]] = []
    for (ref, item), a in sorted(acc.items()):
        open_qty = max(Decimal("0"), a["order"] - a["received"])
        row: dict[str, Any] = {"kind": "PO", "ref": ref, "item_code": item, "location_code": a["loc"]}
        if open_qty > 0:
            row |= {"qty": number(open_qty), "due_date": a["due"] or today, "status": a["status"] or "open"}
        else:
            row |= {"qty": number(a["received"]), "due_date": a["last_gr"] or today, "status": "received"}
        if a["supplier"]:
            row["supplier_code"] = str(a["supplier"]).upper()
        if a["lane"]:
            row["lane_code"] = str(a["lane"]).upper()
        out.append(row)
    return out


def _same(feed: str, row: dict[str, Any], sent: dict[str, Any]) -> bool:
    if feed == "inventory":
        return bool(float(row["on_hand_qty"]) == float(sent.get("on_hand_qty", "nan")))
    return row == sent


class ErpSnapshotFeed:
    def __init__(self, erp_port: ErpReadPort, db_url: str, config: FeedConfig | None = None,
                 codes: CodeMap | None = None) -> None:
        self.erp_port = erp_port
        self.db_url = db_url
        self.config = config or FeedConfig.from_env()
        self.codes = codes or load_code_map(self.config.code_map_path)

    def _conn(self, tenant: str) -> psycopg.Connection[Any]:
        conn = psycopg.connect(self.db_url, autocommit=True)
        conn.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)",
                     (tenant,))
        return conn

    def plants(self, only: str | None = None) -> dict[str, dict[str, str]]:
        """tenant -> {ERP plant: a production site id}, without plants a sandbox site uses (``only``: one tenant)."""
        with psycopg.connect(self.db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT tenant_id::text, site_id::text, erp_plant FROM field.worker_erp_sites()")
            sites = [(str(t), str(s), str(p)) for t, s, p in cur.fetchall()]
        out: dict[str, dict[str, str]] = {}
        wanted = set(self.config.snapshot_tenants)
        for tenant in sorted({t for t, _, _ in sites if (not wanted or t in wanted) and only in (None, t)}):
            ids = [s for t, s, _ in sites if t == tenant]
            with self._conn(tenant) as conn, conn.cursor() as cur:
                cur.execute("SELECT id::text, mode FROM field.site WHERE tenant_id = %s AND id = ANY(%s::uuid[])",
                            (tenant, ids))
                mode = {str(i): str(m) for i, m in cur.fetchall()}
            prod: dict[str, str] = {}
            sandbox: set[str] = set()
            for t, s, p in sites:
                if t != tenant:
                    continue
                if mode.get(s) == "production":
                    prod.setdefault(p, s)
                else:
                    sandbox.add(p)
            if sandbox & set(prod):
                logger.info("core_snapshot_plant_skipped", tenant_id=tenant, plants=sorted(sandbox & set(prod)),
                            reason="a sandbox site uses the plant")
            plants = {p: s for p, s in prod.items() if p not in sandbox}
            if plants:
                out[tenant] = plants
        return out

    def _sent(self, tenant: str, feed: str) -> dict[tuple[str, str], dict[str, Any]]:
        """The newest row per key staged for the core (pending or delivered) within the resend window."""
        with self._conn(tenant) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM field.core_feed_delivery WHERE tenant_id = %s AND feed = %s"
                " AND status IN ('pending', 'delivered') AND created_at > NOW() - make_interval(secs => %s)"
                " ORDER BY created_at, id",
                (tenant, feed, self.config.snapshot_resend_h * 3600),
            )
            key = ROW_KEY[feed]
            out: dict[tuple[str, str], dict[str, Any]] = {}
            for (b,) in cur.fetchall():
                for r in body_rows(str(b)):
                    out[key(r)] = r
            return out

    def _stage(self, tenant: str, site: str, plant: str, feed: str, rows: list[dict[str, Any]],
               read_at: datetime) -> int:
        n = 0
        size = self.config.snapshot_batch
        with self._conn(tenant) as conn:
            for i in range(0, len(rows), size):
                chunk = rows[i:i + size]
                conn.execute(
                    """
                    INSERT INTO field.core_feed_delivery (tenant_id, site_id, event_id, feed, doc_number, fiscal_year,
                           body, row_count, status, max_attempts, created_at, next_attempt_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, NOW())
                    """,
                    (tenant, site, str(uuid.uuid4()), feed, f"{SNAPSHOT_DOC}-{plant}"[:64], str(read_at.year),
                     feed_body(chunk), len(chunk), self.config.max_attempts, read_at),
                )
                n += 1
        return n

    async def snapshot_tenant(self, tenant: str, plants: dict[str, str], full: bool = False) -> dict[str, int]:
        """Stage what changed for one tenant (``full``: every row, as if nothing had been sent; the dev stack uses it
        after switching cores). Returns {"stock_rows", "po_rows", "deliveries", "unchanged", "conflicts"}."""
        counts = {"stock_rows": 0, "po_rows": 0, "deliveries": 0, "unchanged": 0, "conflicts": 0}
        sent = {feed: {} if full else self._sent(tenant, feed) for feed in ROW_KEY}
        read: list[tuple[str, str, datetime, dict[str, list[dict[str, Any]]]]] = []
        for plant, site in sorted(plants.items()):
            read_at = datetime.now(UTC)
            today = read_at.date().isoformat()
            try:
                stock = await self.erp_port.list_stock(plant)
                pos = await self.erp_port.list_purchase_order_items(plant)
            except (ErpError, NotImplementedError) as e:
                logger.warning("core_snapshot_erp_read_failed", tenant_id=tenant, plant=plant, error=str(e)[:200])
                continue
            read.append((plant, site, read_at, {"inventory": stock_rows(stock, self.codes, today),
                                                "open_supply": supply_rows(pos, self.codes, today)}))
        owners: dict[tuple[str, tuple[str, str]], set[str]] = {}
        for plant, _site, _at, rows_by_feed in read:
            for feed, rows in rows_by_feed.items():
                for r in rows:
                    owners.setdefault((feed, ROW_KEY[feed](r)), set()).add(plant)
        clash = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
        if clash:
            counts["conflicts"] = len(clash)
            logger.error("core_snapshot_conflict", tenant_id=tenant, rows=len(clash),
                         example=[f"{f} {k} from {p}" for (f, k), p in list(clash.items())[:3]])
        for plant, site, read_at, rows_by_feed in read:
            mine = {"stock_rows": 0, "po_rows": 0, "deliveries": 0, "unchanged": 0}
            for feed, rows in rows_by_feed.items():
                key = ROW_KEY[feed]
                rows = [r for r in rows if (feed, key(r)) not in clash]
                changed = [r for r in rows if not (key(r) in sent[feed] and _same(feed, r, sent[feed][key(r)]))]
                mine["unchanged"] += len(rows) - len(changed)
                if changed:
                    mine["deliveries"] += self._stage(tenant, site, plant, feed, changed, read_at)
                    mine["stock_rows" if feed == "inventory" else "po_rows"] += len(changed)
                    for r in changed:
                        sent[feed][key(r)] = r
            for k, v in mine.items():
                counts[k] += v
            logger.info("core_snapshot_staged", tenant_id=tenant, plant=plant, **mine)
        return counts

    async def run_once(self, full: bool = False) -> dict[str, int]:
        """One snapshot of every tenant's production plants. Nothing at all unless the snapshot is enabled."""
        total = {"tenants": 0, "stock_rows": 0, "po_rows": 0, "deliveries": 0, "unchanged": 0, "conflicts": 0}
        if not self.config.snapshot_enabled or self.config.problems():
            return total
        for tenant, plants in self.plants().items():
            got = await self.snapshot_tenant(tenant, plants, full=full)
            total["tenants"] += 1
            for k, v in got.items():
                total[k] += v
        return total

