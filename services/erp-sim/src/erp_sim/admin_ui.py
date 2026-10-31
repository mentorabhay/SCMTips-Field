"""Server-Rendered Admin UI for Simulated ERP (Task T1.054).

Provides HTML views at /_sim/ui without build steps:
- /_sim/ui: System overview & KPIs
- /_sim/ui/documents: Transactional documents & reversal chains
- /_sim/ui/documents/{doc}/{year}: one document, its items and its reversal chain
- /_sim/ui/stock: Current stock balances
- /_sim/ui/locks: Active locks & number ranges
- /_sim/ui/faults: Active fault injection rules; add or switch off a rule

The two write actions (add/switch off a fault rule, reset) are for the person at the PC: they are refused
unless the request comes from this machine and, when the browser sends an Origin, from this same page.
"""

import html
import ipaddress
import os
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from erp_sim.db import get_conn
from erp_sim.seed import reset_database

router = APIRouter(prefix="/_sim/ui", tags=["Simulator UI"])

FAULTS_ENABLED = os.getenv("ERPSIM_FAULTS_ENABLED", "true").lower() in ("true", "1", "yes")
CLIENT = "100"

# What the simulator's services check before they act (service, operation), for the fault form.
FAULT_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("API_INBOUND_DELIVERY_SRV", "PostGoodsReceipt", "Goods receipt 101 (Receive)"),
    ("API_OUTBOUND_DELIVERY_SRV", "PostGoodsIssue", "Goods issue 601 (Pick)"),
    ("API_PHYSICAL_INVENTORY_DOC_SRV", "PostDifferences", "Count differences 701/702 (Count)"),
    ("API_EQUIPMENT", "Install", "Install unit (Swap)"),
    ("API_EQUIPMENT", "Dismantle", "Dismantle unit (Swap)"),
    ("API_MATERIAL_DOCUMENT_SRV", "Cancel", "Reverse a material document"),
    ("API_INBOUND_DELIVERY_SRV", "Read", "Read an inbound delivery"),
    ("API_OUTBOUND_DELIVERY_SRV", "Read", "Read an outbound delivery"),
)
FAULT_KINDS: tuple[tuple[str, str], ...] = (
    ("http_5xx", "SAP answers HTTP 500 (the job is retried, then blocks)"),
    ("lock", "Object locked by another user (retried)"),
    ("timeout", "Gateway timeout"),
    ("latency", "Slow answer (1.5 s), still succeeds"),
    ("partial", "Incomplete answer"),
)


def _fetch_scalar(cur: Any) -> int:
    row = cur.fetchone()
    return int(row[0]) if row else 0


def e(value: Any) -> str:
    """HTML-escape a value for a page; None becomes a dash."""
    return "-" if value is None else html.escape(str(value), quote=True)


def is_local_request(request: Request) -> bool:
    """True only for a request from this machine; when the browser sends an Origin, it must be this server."""
    host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(host).is_loopback:
            return False
    except ValueError:
        return False
    origin = request.headers.get("origin")
    if origin and origin != "null":
        o = urlsplit(origin)
        try:
            same_host = o.hostname is not None and ipaddress.ip_address(o.hostname).is_loopback
        except ValueError:
            same_host = o.hostname == "localhost"
        if not same_host or (o.port or 80) != request.url.port:
            return False
    return True


def _require_local(request: Request) -> None:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="Simulator actions are only accepted from this PC.")


NAV: tuple[tuple[str, str], ...] = (
    ("/_sim/ui", "Overview"),
    ("/_sim/ui/documents", "Documents & Reversals"),
    ("/_sim/ui/stock", "Stock Balances"),
    ("/_sim/ui/locks", "Locks & Ranges"),
    ("/_sim/ui/faults", "Fault Rules"),
)

STYLE = """
        :root {
            --bg: #0b0f19;
            --surface: #131b2e;
            --border: #23314f;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --accent: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; }
        a { color: var(--primary); text-decoration: none; }
        .nav { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        .nav a { color: var(--text-muted); font-size: 14px; font-weight: 500; }
        .nav a.active { color: var(--primary); border-bottom: 2px solid var(--primary); padding-bottom: 12px; }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-bottom: 20px; }
        h1, h2, h3 { margin-bottom: 12px; font-weight: 600; }
        p.muted, .muted { color: var(--text-muted); font-size: 13px; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
        th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
        th { color: var(--text-muted); text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }
        td.num { text-align: right; font-variant-numeric: tabular-nums; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        .badge-green { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .badge-red { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        .badge-yellow { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .badge-grey { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }
        .btn { background: var(--primary); color: #000; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; }
        .btn-red { background: #ef4444; color: #fff; }
        .btn-quiet { background: transparent; color: var(--text); border: 1px solid var(--border); }
        .mono { font-family: "JetBrains Mono", Consolas, monospace; }
        .grid4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .kpi { font-size: 28px; font-weight: 700; color: var(--primary); margin-top: 4px; }
        form.inline { display: inline; }
        .formgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; align-items: end; }
        label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-muted); }
        select, input { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-size: 13px; }
        pre { white-space: pre-wrap; font-size: 12px; color: var(--text-muted); }
"""


def page(active: str, body: str, title: str = "SCMTIPS ERP-Sim Console") -> str:
    nav = "".join(
        f'<a href="{href}"{" class=\"active\"" if href == active else ""}>{e(label)}</a>' for href, label in NAV
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{e(title)}</title>
    <style>{STYLE}</style>
</head>
<body>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 16px; gap: 12px; flex-wrap: wrap;">
        <h2>SCMTIPS ERP Simulator <span style="font-size:12px; font-weight:400; color:var(--text-muted)">[Client {CLIENT} · simulated SAP S/4]</span></h2>
        <form action="/_sim/ui/reset" method="post" onsubmit="return confirm('Reset all ERP test data to the sample? Open field jobs will no longer match SAP.')">
            <button class="btn btn-red" type="submit">Reset to Sample</button>
        </form>
    </div>
    <nav class="nav">{nav}</nav>
    {body}
</body>
</html>"""


def _status_badge(status: str | None) -> str:
    cls = {"reversed": "badge-red", "posted": "badge-green"}.get(status or "", "badge-grey")
    return f'<span class="badge {cls}">{e(status)}</span>'


def _flags(header: Any) -> str:
    """Badges for documents posted for a sandbox site (M3): ``sandbox`` and, if opted in, ``simulated``."""
    head = header if isinstance(header, dict) else {}
    out = ' <span class="badge badge-yellow" title="posted for a sandbox (home / training) site">sandbox</span>' \
        if head.get("sandbox") else ""
    if head.get("simulated"):
        out += ' <span class="badge badge-red" title="caused by stack home --simulate-differences">simulated</span>'
    return out


def _doc_link(doc: str | None, year: str | None) -> str:
    if not doc:
        return "-"
    return f'<a class="mono" href="/_sim/ui/documents/{e(doc)}/{e(year)}">{e(doc)}</a>'


def _when(ts: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return "-" if ts is None else e(ts.strftime(fmt))


@router.get("", response_class=HTMLResponse)
async def admin_overview() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM erpsim.document;")
            doc_count = _fetch_scalar(cur)

            cur.execute("SELECT count(*) FROM erpsim.inbound_delivery;")
            ibd_count = _fetch_scalar(cur)

            cur.execute("SELECT count(*) FROM erpsim.stock WHERE quantity > 0;")
            stock_count = _fetch_scalar(cur)

            cur.execute("SELECT count(*) FROM erpsim.fault_rule WHERE active = true;")
            fault_count = _fetch_scalar(cur)

            cur.execute(
                """
                SELECT doc_number, fiscal_year, doc_type, movement_type, reversal_of, status, created_at, header_data
                FROM erpsim.document
                ORDER BY created_at DESC LIMIT 10;
            """
            )
            recent_docs = cur.fetchall()

    rows_html = "".join(
        f"""<tr>
            <td>{_doc_link(r[0], r[1])}</td>
            <td>{e(r[1])}</td>
            <td>{e(r[2])}</td>
            <td><span class="badge badge-green">{e(r[3])}</span>{_flags(r[7])}</td>
            <td>{e(r[4])}</td>
            <td>{_status_badge(r[5])}</td>
            <td class="mono">{_when(r[6], "%H:%M:%S")}</td>
        </tr>"""
        for r in recent_docs
    )
    empty = '<tr><td colspan="7" class="muted" style="text-align:center">No documents posted yet. Receive a delivery on the phone, or run the stack smoke test.</td></tr>'
    return page(
        "/_sim/ui",
        f"""
    <div class="grid4">
        <div class="card"><div class="muted">Material Documents</div><div class="kpi">{doc_count}</div></div>
        <div class="card"><div class="muted">Inbound Deliveries</div><div class="kpi">{ibd_count}</div></div>
        <div class="card"><div class="muted">Active Stock SKUs</div><div class="kpi">{stock_count}</div></div>
        <div class="card"><div class="muted">Active Fault Rules</div>
            <div class="kpi" style="color:{"#ef4444" if fault_count else "#10b981"}">{fault_count}</div></div>
    </div>
    <div class="card">
        <h3>Recent Transactions</h3>
        <table>
            <thead><tr><th>Doc Number</th><th>Year</th><th>Type</th><th>Movement</th><th>Reversal Of</th><th>Status</th><th>Time</th></tr></thead>
            <tbody>{rows_html or empty}</tbody>
        </table>
    </div>""",
    )


@router.get("/documents", response_class=HTMLResponse)
async def admin_documents(movement: str | None = None) -> str:
    """Material documents, newest first, with item totals and the document each one reverses or is reversed by."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.doc_number, d.fiscal_year, d.doc_type, d.movement_type, d.status, d.created_at, d.reversal_of,
                   (SELECT r.doc_number FROM erpsim.document r
                     WHERE r.client = d.client AND r.reversal_of = d.doc_number ORDER BY r.created_at LIMIT 1),
                   count(i.line_no), coalesce(sum(i.quantity), 0),
                   string_agg(DISTINCT i.material_no, ', '), d.header_data
            FROM erpsim.document d
            LEFT JOIN erpsim.document_item i
              ON i.client = d.client AND i.doc_number = d.doc_number AND i.fiscal_year = d.fiscal_year
            WHERE d.client = %s AND (%s::text IS NULL OR d.movement_type = %s)
            GROUP BY d.client, d.doc_number, d.fiscal_year, d.doc_type, d.movement_type, d.status, d.created_at,
                     d.reversal_of, d.header_data
            ORDER BY d.created_at DESC
            LIMIT 200;
            """,
            (CLIENT, movement, movement),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT DISTINCT movement_type FROM erpsim.document WHERE client = %s AND movement_type IS NOT NULL"
            " ORDER BY 1;",
            (CLIENT,),
        )
        movements = [str(r[0]) for r in cur.fetchall()]

    chips = " ".join(
        f'<a class="badge {"badge-green" if m == movement else "badge-grey"}" href="/_sim/ui/documents?movement={e(m)}">{e(m)}</a>'
        for m in movements
    )
    if movement:
        chips += ' <a class="badge badge-grey" href="/_sim/ui/documents">all</a>'
    body_rows = "".join(
        f"""<tr>
            <td>{_doc_link(r[0], r[1])}</td>
            <td>{e(r[1])}</td>
            <td>{e(r[2])}</td>
            <td><span class="badge badge-green">{e(r[3])}</span>{_flags(r[11])}</td>
            <td class="num">{int(r[8])}</td>
            <td class="num mono">{e(r[9])}</td>
            <td class="mono">{e(r[10])}</td>
            <td>{_doc_link(r[6], r[1]) if r[6] else "-"}</td>
            <td>{_doc_link(r[7], r[1]) if r[7] else "-"}</td>
            <td>{_status_badge(r[4])}</td>
            <td class="mono">{_when(r[5])}</td>
        </tr>"""
        for r in rows
    )
    empty = '<tr><td colspan="11" class="muted" style="text-align:center">No documents yet.</td></tr>'
    return page(
        "/_sim/ui/documents",
        f"""
    <div class="card">
        <h3>Material Documents</h3>
        <p class="muted">101 goods receipt · 601 goods issue · 701/702 inventory differences · 561 initial stock entry · 102/602 reversals. A yellow <span class="badge badge-yellow">sandbox</span> badge marks documents posted for a sandbox (home / training) site. Newest 200. Movement: {chips or "none yet"}</p>
        <table>
            <thead><tr><th>Doc Number</th><th>Year</th><th>Type</th><th>Movement</th><th>Items</th><th>Total Qty</th>
                <th>Materials</th><th>Reverses</th><th>Reversed By</th><th>Status</th><th>Posted</th></tr></thead>
            <tbody>{body_rows or empty}</tbody>
        </table>
    </div>""",
    )


@router.get("/documents/{doc_number}/{fiscal_year}", response_class=HTMLResponse)
async def admin_document(doc_number: str, fiscal_year: str) -> HTMLResponse:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_number, fiscal_year, doc_type, movement_type, reversal_of, header_data, status, created_at
            FROM erpsim.document WHERE client = %s AND doc_number = %s AND fiscal_year = %s;
            """,
            (CLIENT, doc_number, fiscal_year),
        )
        head = cur.fetchone()
        if head is None:
            return HTMLResponse(
                page(
                    "/_sim/ui/documents",
                    f'<div class="card"><h3>Document {e(doc_number)} / {e(fiscal_year)} not found</h3>'
                    '<p class="muted">It may have been removed by "Reset to Sample". '
                    '<a href="/_sim/ui/documents">All documents</a></p></div>',
                ),
                status_code=404,
            )
        cur.execute(
            """
            SELECT line_no, material_no, plant, storage_location, quantity, uom, movement_type, item_data
            FROM erpsim.document_item WHERE client = %s AND doc_number = %s AND fiscal_year = %s ORDER BY line_no;
            """,
            (CLIENT, doc_number, fiscal_year),
        )
        items = cur.fetchall()
        cur.execute(
            "SELECT doc_number, fiscal_year, movement_type, status, created_at FROM erpsim.document"
            " WHERE client = %s AND reversal_of = %s ORDER BY created_at;",
            (CLIENT, doc_number),
        )
        reversed_by = cur.fetchall()

    item_rows = "".join(
        f"""<tr><td class="num">{e(r[0])}</td><td class="mono">{e(r[1])}</td><td>{e(r[2])}</td><td>{e(r[3])}</td>
            <td class="num mono">{e(r[4])}</td><td>{e(r[5])}</td><td><span class="badge badge-green">{e(r[6])}</span></td>
            <td><pre>{e(r[7]) if r[7] else ""}</pre></td></tr>"""
        for r in items
    )
    chain = "".join(
        f"<li>Reversed by {_doc_link(r[0], r[1])} ({e(r[2])}, {_status_badge(r[3])}, {_when(r[4])})</li>"
        for r in reversed_by
    )
    if head[4]:
        chain = f"<li>Reverses {_doc_link(head[4], head[1])}</li>" + chain
    return HTMLResponse(
        page(
            "/_sim/ui/documents",
            f"""
    <div class="card">
        <h3>Material Document <span class="mono">{e(head[0])}</span> / {e(head[1])}</h3>
        <table>
            <tbody>
                <tr><th>Type</th><td>{e(head[2])}</td><th>Movement</th><td><span class="badge badge-green">{e(head[3])}</span>{_flags(head[5])}</td></tr>
                <tr><th>Status</th><td>{_status_badge(head[6])}</td><th>Posted</th><td class="mono">{_when(head[7])}</td></tr>
            </tbody>
        </table>
        <h3 style="margin-top:16px">Reversal chain</h3>
        <ul style="margin-left:18px">{chain or '<li class="muted">Not reversed.</li>'}</ul>
        <h3 style="margin-top:16px">Header data</h3>
        <pre>{e(head[5]) if head[5] else "-"}</pre>
    </div>
    <div class="card">
        <h3>Items</h3>
        <table>
            <thead><tr><th>Line</th><th>Material</th><th>Plant</th><th>SLoc</th><th>Qty</th><th>UoM</th><th>Movement</th><th>Item data</th></tr></thead>
            <tbody>{item_rows or '<tr><td colspan="8" class="muted">No items.</td></tr>'}</tbody>
        </table>
    </div>""",
            title=f"Document {doc_number}",
        )
    )


@router.get("/stock", response_class=HTMLResponse)
async def admin_stock() -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT plant, storage_location, material_no, quantity, uom, updated_at
                FROM erpsim.stock
                ORDER BY material_no ASC LIMIT 500;
            """
        )
        rows = cur.fetchall()

    items_html = "".join(
        f"""<tr>
            <td>{e(r[0])}</td>
            <td><span class="badge badge-yellow">{e(r[1])}</span></td>
            <td class="mono">{e(r[2])}</td>
            <td class="num mono" style="font-weight:600;">{e(r[3])}</td>
            <td>{e(r[4])}</td>
            <td class="mono">{_when(r[5])}</td>
        </tr>"""
        for r in rows
    )
    return page(
        "/_sim/ui/stock",
        f"""
    <div class="card">
        <h3>Real-Time Stock Balances (Physical Inventory Ledger)</h3>
        <p class="muted">SAP inventory management stock per plant and storage location (no bins: bins live in the field app).</p>
        <table>
            <thead><tr><th>Plant</th><th>SLoc</th><th>Material</th><th>Quantity</th><th>UoM</th><th>Updated</th></tr></thead>
            <tbody>{items_html}</tbody>
        </table>
    </div>""",
    )


@router.get("/locks", response_class=HTMLResponse)
async def admin_locks() -> str:
    now = datetime.now(UTC)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT object_type, object_key, session_id, acquired_at, expires_at FROM erpsim.enqueue_lock"
            " WHERE client = %s ORDER BY acquired_at DESC LIMIT 200;",
            (CLIENT,),
        )
        locks = cur.fetchall()
        cur.execute(
            'SELECT object, "current", lower, upper FROM erpsim.number_range WHERE client = %s ORDER BY object;',
            (CLIENT,),
        )
        ranges = cur.fetchall()

    lock_rows = "".join(
        f"""<tr><td>{e(r[0])}</td><td class="mono">{e(r[1])}</td><td class="mono">{e(r[2])}</td>
            <td class="mono">{_when(r[3])}</td><td class="mono">{_when(r[4])}</td>
            <td>{'<span class="badge badge-grey">expired</span>' if r[4] is not None and r[4] < now else '<span class="badge badge-yellow">held</span>'}</td></tr>"""
        for r in locks
    )

    def used(cur_no: int, lower: int, upper: int) -> str:
        span = max(1, upper - lower + 1)
        pct = max(0.0, min(100.0, (cur_no - lower + 1) * 100.0 / span))
        return f"{pct:.4f} %" if pct < 0.01 else f"{pct:.2f} %"

    range_rows = "".join(
        f"""<tr><td class="mono">{e(r[0])}</td><td class="num mono">{e(r[1])}</td><td class="num mono">{e(r[2])}</td>
            <td class="num mono">{e(r[3])}</td><td class="num">{used(int(r[1]), int(r[2]), int(r[3]))}</td></tr>"""
        for r in ranges
    )
    return page(
        "/_sim/ui/locks",
        f"""
    <div class="card">
        <h3>Enqueue Locks</h3>
        <p class="muted">SAP-style object locks. A held lock makes another posting on the same object wait or fail with "locked"; expired locks are taken over.</p>
        <table>
            <thead><tr><th>Object</th><th>Key</th><th>Session</th><th>Acquired</th><th>Expires</th><th>State</th></tr></thead>
            <tbody>{lock_rows or '<tr><td colspan="6" class="muted" style="text-align:center">No locks held.</td></tr>'}</tbody>
        </table>
    </div>
    <div class="card">
        <h3>Number Ranges</h3>
        <p class="muted">The last number handed out for each document type; the next document gets the next number.</p>
        <table>
            <thead><tr><th>Object</th><th>Last Number</th><th>From</th><th>To</th><th>Used</th></tr></thead>
            <tbody>{range_rows or '<tr><td colspan="5" class="muted" style="text-align:center">No number ranges.</td></tr>'}</tbody>
        </table>
    </div>""",
    )


@router.get("/faults", response_class=HTMLResponse)
async def admin_faults() -> str:
    now = datetime.now(UTC)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, service, operation, doc_key, probability, count, ttl_s, active, created_at
            FROM erpsim.fault_rule WHERE client = %s ORDER BY active DESC, created_at DESC LIMIT 100;
            """,
            (CLIENT,),
        )
        rules = cur.fetchall()

    def state(active: bool, created: datetime, ttl_s: int, count: int) -> str:
        if not active or count <= 0:
            return '<span class="badge badge-grey">off</span>'
        if (now - created).total_seconds() > ttl_s:
            return '<span class="badge badge-grey">expired</span>'
        return '<span class="badge badge-red">armed</span>'

    rule_rows = "".join(
        f"""<tr><td>{e(r[1])}</td><td class="mono">{e(r[2] or "any service")}</td><td class="mono">{e(r[3] or "any")}</td>
            <td class="mono">{e(r[4] or "any")}</td><td class="num">{float(r[5]):.0%}</td><td class="num">{e(r[6])}</td>
            <td class="num">{e(r[7])} s</td><td>{state(bool(r[8]), r[9], int(r[7]), int(r[6]))}</td>
            <td>{_when(r[9], "%H:%M:%S")}</td>
            <td>{f'<form class="inline" method="post" action="/_sim/ui/faults/{e(r[0])}/off"><button class="btn btn-quiet" type="submit">Switch off</button></form>' if r[8] else ""}</td></tr>"""
        for r in rules
    )
    targets = "".join(
        f'<option value="{e(svc)}|{e(op)}">{e(label)}</option>' for svc, op, label in FAULT_TARGETS
    )
    kinds = "".join(f'<option value="{e(k)}">{e(label)}</option>' for k, label in FAULT_KINDS)
    form = (
        f"""
        <form method="post" action="/_sim/ui/faults" class="formgrid">
            <label>When SAP is asked to<select name="target">{targets}</select></label>
            <label>it should<select name="kind">{kinds}</select></label>
            <label>this many times<input name="count" type="number" min="1" max="50" value="1"></label>
            <label>for the next (minutes)<input name="minutes" type="number" min="1" max="120" value="10"></label>
            <div><button class="btn btn-red" type="submit">Arm fault</button></div>
        </form>"""
        if FAULTS_ENABLED
        else '<p class="muted">Fault injection is switched off (ERPSIM_FAULTS_ENABLED=false).</p>'
    )
    return page(
        "/_sim/ui/faults",
        f"""
    <div class="card">
        <h3>Make SAP fail on purpose</h3>
        <p class="muted" style="margin-bottom:12px">Use this to see how the field app copes. One failure: the worker retries and the
        document still posts. More failures than the worker's retries: the job shows as Blocked on the console's Postings to SAP page
        until you retry it there. A rule switches itself off when its count is used up or its time runs out. Only accepted from this PC.</p>
        {form}
    </div>
    <div class="card">
        <h3>Fault Rules</h3>
        <table>
            <thead><tr><th>Kind</th><th>Service</th><th>Operation</th><th>Document</th><th>Chance</th><th>Left</th><th>TTL</th>
                <th>State</th><th>Created</th><th></th></tr></thead>
            <tbody>{rule_rows or '<tr><td colspan="10" class="muted" style="text-align:center">No fault rules. SAP answers normally.</td></tr>'}</tbody>
        </table>
    </div>""",
    )


@router.post("/faults")
async def admin_fault_create(
    request: Request,
    target: str = Form(...),
    kind: str = Form(...),
    count: int = Form(1),
    minutes: int = Form(10),
) -> RedirectResponse:
    _require_local(request)
    if not FAULTS_ENABLED:
        raise HTTPException(status_code=403, detail="Fault injection disabled")
    service, _, operation = target.partition("|")
    if (service, operation) not in {(s, o) for s, o, _l in FAULT_TARGETS}:
        raise HTTPException(status_code=422, detail="Unknown target")
    if kind not in {k for k, _l in FAULT_KINDS}:
        raise HTTPException(status_code=422, detail="Unknown fault kind")
    if not (1 <= count <= 50 and 1 <= minutes <= 120):
        raise HTTPException(status_code=422, detail="count must be 1-50 and minutes 1-120")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO erpsim.fault_rule (id, client, kind, service, operation, doc_key, probability, count, ttl_s, seed, active)
            VALUES (%s, %s, %s, %s, %s, NULL, 1.0, %s, %s, NULL, true);
            """,
            (uuid.uuid4(), CLIENT, kind, service, operation, count, minutes * 60),
        )
        conn.commit()
    return RedirectResponse("/_sim/ui/faults", status_code=303)


@router.post("/faults/{rule_id}/off")
async def admin_fault_off(request: Request, rule_id: uuid.UUID) -> RedirectResponse:
    _require_local(request)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE erpsim.fault_rule SET active = false WHERE id = %s AND client = %s;", (rule_id, CLIENT))
        conn.commit()
    return RedirectResponse("/_sim/ui/faults", status_code=303)


@router.post("/reset")
async def admin_reset(request: Request) -> RedirectResponse:
    _require_local(request)
    reset_database(CLIENT)
    return RedirectResponse("/_sim/ui", status_code=303)
