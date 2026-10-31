"""`stack erp-feed` and `stack smoke --erp-feed`: the ERP's stock and open POs to the core's feeds (M4 Q10).

``stack erp-feed`` stages a snapshot now with the code the worker runs on its schedule (field_worker.core_feeds
.ErpSnapshotFeed, FIELD_CORE_SNAPSHOT_INTERVAL_S): the running field-worker then delivers it, signed, like the
goods-receipt rows. ``stack smoke --erp-feed`` proves the whole leg for the drone world that `stack seed-core-export`
loaded from the core's export (the core's own codes, no FIELD_CORE_CODE_MAP for them):

1. erp-sim holds the core's plants and purchase orders, and the tenant has a production Field site on each plant
   (the site pack's), so the snapshot reads them;
2. a snapshot is staged and every delivery of it is delivered (the worker);
3. the core's on-hand per item and location and its PO lines (qty, status, due date) equal what erp-sim holds:
   FIELD_CORE_TARGET=core reads the real core's own API (``/v1/inventory``, ``/v1/open-supply``) as its operator
   would; ``standin`` reads the stand-in's upsert view (``/_standin/feeds/state``, a dev double);
4. a second snapshot right after stages nothing (only changes are sent).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from tools.dev_stack import stack
from tools.dev_stack.stack import SmokeFailure, _accepted, _expect

__all__ = ["SmokeFailure", "smoke_erp_feed", "stage_now"]


def _worker_url() -> str:
    return os.environ.get("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")


def snapshot_feed() -> Any:
    from field_sap.sim.adapter import SimAdapter
    from field_worker.core_feeds import ErpSnapshotFeed, FeedConfig

    cfg = FeedConfig.from_env()
    if not cfg.enabled or cfg.problems():
        raise SmokeFailure("the core feeds are not configured: FIELD_CORE_INVENTORY_FEED_URL / _SUPPLY_FEED_URL and"
                           f" their secrets in .env.local (missing: {cfg.problems() or 'the URLs'})")
    erp = os.environ.get("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")
    return ErpSnapshotFeed(SimAdapter(base_url=erp), _worker_url(), cfg)


def drone_plants() -> dict[str, int]:
    """erp-sim plants holding purchase orders (the core's export loads them), with their PO line count."""
    import psycopg

    with psycopg.connect(stack._admin_url("erpsim")) as c, c.cursor() as cur:
        cur.execute("SELECT plant, count(*) FROM erpsim.purchase_order_item WHERE client = '100' GROUP BY plant")
        return {str(p): int(n) for p, n in cur.fetchall()}


def snapshot_deliveries(tenant: str, since: datetime) -> list[tuple[str, str, int]]:
    import psycopg

    with psycopg.connect(stack._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT feed, status, row_count FROM field.core_feed_delivery WHERE tenant_id = %s"
                    " AND doc_number LIKE 'SNAPSHOT-%%' AND created_at >= %s ORDER BY created_at, id", (tenant, since))
        return [(str(f), str(s), int(n)) for f, s, n in cur.fetchall()]


def stage_now(tenant: str | None = None, full: bool = False) -> tuple[str, dict[str, int]]:
    """One snapshot of the tenant's production plants (or of every tenant). Returns (tenant or '*', counts).
    ``full``: every row, whatever was sent before (after switching FIELD_CORE_TARGET, or a stand-in restart: the
    delivery history then describes another core)."""
    import asyncio

    feed = snapshot_feed()
    plants = feed.plants(tenant)
    if tenant is not None:
        if tenant not in plants:
            raise SmokeFailure(f"tenant {tenant} has no active production Field site on an ERP plant (a sandbox"
                               " plant is never read): run `stack seed-core-export <export> ` with the site pack")
        return tenant, dict(asyncio.run(feed.snapshot_tenant(tenant, plants[tenant], full=full)))
    return "*", dict(asyncio.run(feed.run_once(full=full)))


def _latest_on_hand(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """The core keeps inventory per (item, location, as_of): the latest as_of is the on-hand."""
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for r in rows:
        k = (str(r["item_code"]), str(r["location_code"]))
        if k not in best or str(r.get("as_of")) >= best[k][0]:
            best[k] = (str(r.get("as_of")), float(r["on_hand_qty"]))
    return {k: v for k, (_, v) in best.items()}


def erp_view(plants: list[str], codes: Any) -> tuple[dict[tuple[str, str], float],
                                                     dict[tuple[str, str], dict[str, Any]]]:
    """What erp-sim holds, in the core's codes as the snapshot sends it (``codes``: the feed's CodeMap, the identity
    for the drone world): on-hand per (item, location) and the PO rows per (ref, item)."""
    import asyncio

    from field_sap.sim.adapter import SimAdapter
    from field_worker.core_feeds.snapshot import stock_rows, supply_rows

    sim = SimAdapter(base_url=os.environ.get("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002"))
    today = datetime.now(UTC).date().isoformat()
    stock: dict[tuple[str, str], float] = {}
    pos: dict[tuple[str, str], dict[str, Any]] = {}
    for p in plants:
        for r in stock_rows(asyncio.run(sim.list_stock(p)), codes, today):
            stock[(r["item_code"], r["location_code"])] = float(r["on_hand_qty"])
        for r in supply_rows(asyncio.run(sim.list_purchase_order_items(p)), codes, today):
            pos[(r["ref"], r["item_code"])] = r
    return stock, pos


def compare(stock: dict[tuple[str, str], float], pos: dict[tuple[str, str], dict[str, Any]],
            core_stock: dict[tuple[str, str], float], core_pos: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """Differences between erp-sim and the core for the erp-sim rows (the core may hold more, e.g. work orders)."""
    out: list[str] = []
    for k, q in sorted(stock.items()):
        if core_stock.get(k) != q:
            out.append(f"on-hand {k[0]}@{k[1]}: erp-sim {q:g}, core {core_stock.get(k)}")
    for k, r in sorted(pos.items()):
        c = core_pos.get(k)
        if c is None:
            out.append(f"PO {k[0]} {k[1]}: not at the core")
            continue
        got = (Decimal(str(c.get("qty"))), str(c.get("status")), str(c.get("due_date"))[:10],
               str(c.get("location_code")))
        want = (Decimal(str(r["qty"])), r["status"], r["due_date"], r["location_code"])
        if got != want:
            out.append(f"PO {k[0]} {k[1]}: erp-sim {want}, core {got}")
    return out


def _wait_delivered(tenant: str, since: datetime, wait: float) -> list[tuple[str, str, int]]:
    deadline = time.monotonic() + wait
    rows = snapshot_deliveries(tenant, since)
    while time.monotonic() < deadline:
        rows = snapshot_deliveries(tenant, since)
        if rows and all(s in ("delivered", "skipped") for _, s, _ in rows):
            return rows
        if any(s == "dead" for _, s, _ in rows):
            break
        time.sleep(1)
    raise SmokeFailure(f"the snapshot deliveries were not all delivered within {wait:.0f} s (is field-worker up?): "
                       f"{rows}")


def smoke_erp_feed(api: str, state: dict[str, Any], wait: float) -> None:
    target = stack.core_target()
    with_pos = drone_plants()
    if target == "core":
        from tools.dev_stack import core_smoke

        base = core_smoke.core_base()
        web: Any = core_smoke.CoreWeb(base, "OPERATOR")
        signed = core_smoke.app_sign_in(base, "OPERATOR", f"smoke-erp-feed-{os.getpid()}", "PHONE_ONLY")
        tenant = str(signed["claims"]["tenant_id"])
        where = f"the real SCMTIPS core {base}"
    elif target == "standin":
        web = None
        tenant = str(state["tenant"])
        where = "the stand-in core (a dev double)"
    else:
        raise SmokeFailure("smoke --erp-feed runs against a core: set FIELD_CORE_TARGET=standin or core")
    feed = snapshot_feed()
    mine = feed.plants(tenant).get(tenant, {})
    plants = {p: n for p, n in with_pos.items() if p in mine}
    _expect(bool(plants), f"none of tenant {tenant}'s production plants ({sorted(mine)}) holds purchase orders in"
                          " erp-sim: run `stack seed-core-export <SCMTips>/samples/exports/erp-sim` (the core's drone"
                          " world and its site pack) with FIELD_CORE_TARGET as now")
    print(f"erp-feed erp-sim plants {', '.join(f'{p} ({n} PO lines)' for p, n in sorted(plants.items()))}; tenant"
          f" {tenant}; production sites on them; target {where}")
    since = datetime.now(UTC)
    _, counts = stage_now(tenant, full=True)  # independent of what earlier runs sent (maybe to another core)
    print(f"         snapshot staged: {counts['stock_rows']} stock rows, {counts['po_rows']} PO rows in"
          f" {counts['deliveries']} deliveries (batch {feed.config.snapshot_batch}); {counts['unchanged']} unchanged")
    rows = _wait_delivered(tenant, since, wait) if counts["deliveries"] else []
    if rows:
        print(f"         field-worker delivered them all, signed: {rows}")
    stock, pos = erp_view(sorted(mine), feed.codes)
    if target == "core":
        core_stock = _latest_on_hand(core_smoke._all(web, "/v1/inventory"))
        core_pos = {(str(x["ref"]), str(x["item_code"])): x for x in core_smoke._all(web, "/v1/open-supply")
                    if str(x.get("kind", "PO")).upper() == "PO"}
        web.close()
    else:
        st = _accepted(httpx.get(f"{os.environ['FIELD_CORE_BASE_URL'].rstrip('/')}/_standin/feeds/state", timeout=10),
                       "stand-in feed state")
        core_stock = _latest_on_hand(st["inventory"])
        core_pos = {(str(x["ref"]), str(x["item_code"])): x for x in st["open_supply"]}
    diff = compare(stock, pos, core_stock, core_pos)
    _expect(not diff, f"{len(diff)} difference(s) between erp-sim and the core: {diff[:8]}")
    sample = [k for k in (("CP-204", "PLANT-GOA"), ("CP-207", "PLANT-GOA"), ("RM-307", "PLANT-GOA")) if k in stock]
    print(f"         core = erp-sim for {len(stock)} on-hand rows and {len(pos)} PO lines, e.g. "
          + "; ".join(f"{i}@{loc} {stock[(i, loc)]:g}" for i, loc in sample))
    open_lines = sorted((k for k, r in pos.items() if r["status"] != "received"),
                        key=lambda k: (not k[0].startswith("PO-"), k))[:3]
    if open_lines:
        print("         e.g. " + "; ".join(f"{ref} {it} {pos[(ref, it)]['qty']} {pos[(ref, it)]['status']} due"
                                          f" {pos[(ref, it)]['due_date']}" for ref, it in open_lines))
    _, again = stage_now(tenant)
    _expect(again["deliveries"] == 0, f"a second snapshot right after staged {again}")
    print(f"         second snapshot: nothing staged ({again['unchanged']} rows unchanged)")
