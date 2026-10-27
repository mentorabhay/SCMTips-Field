"""Server-Rendered Admin UI for Simulated ERP (Task T1.054).

Provides HTML views at /_sim/ui without build steps:
- /_sim/ui: System overview & KPIs
- /_sim/ui/documents: Transactional documents & reversal chains
- /_sim/ui/stock: Current stock balances
- /_sim/ui/locks: Active locks & number ranges
- /_sim/ui/faults: Active fault injection rules
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from erp_sim.db import get_conn

router = APIRouter(prefix="/_sim/ui", tags=["Simulator UI"])

HTML_HEAD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SCMTIPS ERP-Sim Console</title>
    <style>
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
        .nav { display: flex; gap: 16px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        .nav a { color: var(--text-muted); text-decoration: none; font-size: 14px; font-weight: 500; }
        .nav a.active { color: var(--primary); border-bottom: 2px solid var(--primary); padding-bottom: 12px; }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-bottom: 20px; }
        h1, h2, h3 { margin-bottom: 12px; font-weight: 600; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
        th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
        th { color: var(--text-muted); text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        .badge-green { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .badge-red { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        .badge-yellow { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .btn { background: var(--primary); color: #000; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; }
        .mono { font-family: "JetBrains Mono", Consolas, monospace; }
        .grid4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .kpi { font-size: 28px; font-weight: 700; color: var(--primary); margin-top: 4px; }
    </style>
</head>
<body>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 16px;">
        <h2>SCMTIPS ERP Simulator <span style="font-size:12px; font-weight:400; color:var(--text-muted)">[Client 100 · Port 5450]</span></h2>
        <form action="/_sim/reset" method="post" onsubmit="return confirm('Reset all ERP test data?')">
            <button class="btn" style="background:#ef4444; color:#fff;" type="submit">Reset to Sample</button>
        </form>
    </div>
    <div class="nav">
        <a href="/_sim/ui" class="active">Overview</a>
        <a href="/_sim/ui/documents">Documents & Reversals</a>
        <a href="/_sim/ui/stock">Stock Balances</a>
        <a href="/_sim/ui/locks">Locks & Ranges</a>
        <a href="/_sim/ui/faults">Fault Rules</a>
    </div>
"""

HTML_FOOT = """
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
async def admin_overview() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM erpsim.document;")
            doc_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM erpsim.inbound_delivery;")
            ibd_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM erpsim.outbound_delivery;")
            cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM erpsim.stock WHERE quantity > 0;")
            stock_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM erpsim.enqueue_lock;")
            cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM erpsim.fault_rule WHERE active = true;")
            fault_count = cur.fetchone()[0]

            # Recent documents
            cur.execute(
                """
                SELECT doc_number, fiscal_year, doc_type, movement_type, reversal_of, status, created_at
                FROM erpsim.document
                ORDER BY created_at DESC LIMIT 10;
            """
            )
            recent_docs = cur.fetchall()

    rows_html = "".join(
        f"""<tr>
            <td class="mono"><a href="/_sim/ui/documents/{r[0]}/{r[1]}" style="color:var(--primary);text-decoration:none;">{r[0]}</a></td>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td><span class="badge badge-green">{r[3]}</span></td>
            <td>{r[4] or "-"}</td>
            <td><span class="badge {"badge-red" if r[5] == "reversed" else "badge-green"}">{r[5]}</span></td>
            <td class="mono">{r[6].strftime("%H:%M:%S")}</td>
        </tr>"""
        for r in recent_docs
    )

    return f"""{HTML_HEAD}
    <div class="grid4">
        <div class="card">
            <div style="font-size:12px; color:var(--text-muted)">Material Documents</div>
            <div class="kpi">{doc_count}</div>
        </div>
        <div class="card">
            <div style="font-size:12px; color:var(--text-muted)">Inbound Deliveries</div>
            <div class="kpi">{ibd_count}</div>
        </div>
        <div class="card">
            <div style="font-size:12px; color:var(--text-muted)">Active Stock SKUs</div>
            <div class="kpi">{stock_count}</div>
        </div>
        <div class="card">
            <div style="font-size:12px; color:var(--text-muted)">Active Fault Rules</div>
            <div class="kpi" style="color:{"#ef4444" if fault_count else "#10b981"}">{fault_count}</div>
        </div>
    </div>
    <div class="card">
        <h3>Recent Transactions</h3>
        <table>
            <thead>
                <tr>
                    <th>Doc Number</th><th>Year</th><th>Type</th><th>Movement</th><th>Reversal Of</th><th>Status</th><th>Time</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No documents posted yet. Run seed or post a goods receipt.</td></tr>'}
            </tbody>
        </table>
    </div>
    {HTML_FOOT}"""


@router.get("/stock", response_class=HTMLResponse)
async def admin_stock() -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT plant, storage_location, material_no, quantity, uom, updated_at
                FROM erpsim.stock
                ORDER BY material_no ASC LIMIT 100;
            """
        )
        rows = cur.fetchall()

    items_html = "".join(
        f"""<tr>
            <td>{r[0]}</td>
            <td><span class="badge badge-yellow">{r[1]}</span></td>
            <td class="mono">{r[2]}</td>
            <td class="mono" style="font-weight:600;">{r[3]}</td>
            <td>{r[4]}</td>
            <td class="mono">{r[5].strftime("%Y-%m-%d %H:%M:%S")}</td>
        </tr>"""
        for r in rows
    )

    return f"""{HTML_HEAD}
    <div class="card">
        <h3>Real-Time Stock Balances (Physical Inventory Ledger)</h3>
        <table>
            <thead>
                <tr><th>Plant</th><th>SLoc</th><th>Material</th><th>Quantity</th><th>UoM</th><th>Updated</th></tr>
            </thead>
            <tbody>{items_html}</tbody>
        </table>
    </div>
    {HTML_FOOT}"""
