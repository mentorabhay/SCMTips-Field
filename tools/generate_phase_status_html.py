"""Generates HTML status dashboards for Phases 1-4 from truth ledgers (Task R6)."""

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS_DIR = ROOT / "docs" / "STATUS"
REPORTS_DIR = ROOT / "docs" / "reports"

PHASE_TITLES = {
    1: "Phase 1: Foundations, Contract & Simulated ERP",
    2: "Phase 2: Android Client, Wearables Foundation & Visual Perceptions",
    3: "Phase 3: Warehouse Operations, Picking, Inventory & Core Seams",
    4: "Phase 4: Cell Tower Maintenance, Climb-Safe & Asset Models",
}


def generate_html(phase: int) -> str:
    yaml_file = STATUS_DIR / f"phase{phase}.yaml"
    if not yaml_file.exists():
        return ""

    tasks = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or []

    counts = {"done": 0, "partial": 0, "stub": 0, "missing": 0}
    for t in tasks:
        s = t.get("status", "missing")
        counts[s] = counts.get(s, 0) + 1

    total = len(tasks)
    pct_done = round((counts["done"] / total) * 100.0, 1) if total else 0.0

    rows_html = []
    for t in tasks:
        tid = t.get("id", "")
        title = t.get("title", "")
        ws = t.get("workstream", "")
        st = t.get("status", "missing")
        frs = ", ".join(t.get("frs", []))
        note = t.get("note", "")
        evidence = "<br>".join(t.get("evidence", [])) or "—"
        tests = "<br>".join(t.get("tests", [])[:2]) or "—"

        status_badge_class = {
            "done": "badge-done",
            "partial": "badge-partial",
            "stub": "badge-stub",
            "missing": "badge-missing",
        }.get(st, "badge-missing")

        rows_html.append(f"""
        <tr>
          <td class="font-mono font-bold">{tid}</td>
          <td><span class="ws-tag">{ws}</span></td>
          <td>{title}</td>
          <td><span class="badge {status_badge_class}">{st.upper()}</span></td>
          <td class="font-mono text-xs">{frs or '—'}</td>
          <td class="text-xs break-all">{evidence}</td>
          <td class="text-xs break-all">{tests}</td>
          <td class="text-xs text-slate-400">{note}</td>
        </tr>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SCMTips-Field — {PHASE_TITLES[phase]} Status Dashboard</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #0b0f19;
      color: #e2e8f0;
      margin: 0;
      padding: 30px;
    }}
    .container {{
      max-width: 1400px;
      margin: 0 auto;
    }}
    h1 {{
      color: #f8fafc;
      margin-bottom: 6px;
    }}
    .subtitle {{
      color: #94a3b8;
      margin-bottom: 24px;
      font-size: 14px;
    }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .metric-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 16px;
    }}
    .metric-title {{
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 600;
      color: #94a3b8;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
      margin-top: 6px;
    }}
    .progress-bar-bg {{
      background: #334155;
      border-radius: 9999px;
      height: 12px;
      width: 100%;
      overflow: hidden;
      margin-bottom: 30px;
    }}
    .progress-bar-fill {{
      background: linear-gradient(90deg, #0284c7, #10b981);
      height: 100%;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 8px;
      overflow: hidden;
      font-size: 13px;
    }}
    th {{
      background: #1f2937;
      color: #cbd5e1;
      padding: 12px 14px;
      text-align: left;
      font-weight: 600;
    }}
    td {{
      padding: 10px 14px;
      border-top: 1px solid #1f2937;
      vertical-align: top;
    }}
    tr:hover {{
      background: #1e293b;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge-done {{ background: #064e3b; color: #34d399; border: 1px solid #059669; }}
    .badge-partial {{ background: #78350f; color: #fbbf24; border: 1px solid #d97706; }}
    .badge-stub {{ background: #451a03; color: #fb923c; border: 1px solid #ea580c; }}
    .badge-missing {{ background: #450a0a; color: #f87171; border: 1px solid #dc2626; }}
    .ws-tag {{ background: #1e293b; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-family: monospace; border: 1px solid #475569; }}
    .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .break-all {{ word-break: break-all; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{PHASE_TITLES[phase]}</h1>
    <div class="subtitle">Official Truth Ledger Status Dashboard & Evidence Report • Generated under Remediation Plan Section 2 Binding Rules</div>

    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-title">Total Tasks</div>
        <div class="metric-value" style="color: #f8fafc;">{total}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Proven Done</div>
        <div class="metric-value" style="color: #34d399;">{counts['done']} ({pct_done}%)</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Partial / Unverified</div>
        <div class="metric-value" style="color: #fbbf24;">{counts['partial']}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Stub / Placeholder</div>
        <div class="metric-value" style="color: #fb923c;">{counts['stub']}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Missing</div>
        <div class="metric-value" style="color: #f87171;">{counts['missing']}</div>
      </div>
    </div>

    <div class="progress-bar-bg">
      <div class="progress-bar-fill" style="width: {pct_done}%;"></div>
    </div>

    <table>
      <thead>
        <tr>
          <th style="width: 80px;">Task ID</th>
          <th style="width: 80px;">Stream</th>
          <th>Title</th>
          <th style="width: 90px;">Status</th>
          <th style="width: 120px;">FRs</th>
          <th style="width: 250px;">Deliverable Evidence</th>
          <th style="width: 220px;">Test Evidence</th>
          <th>Remediation Note</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in range(1, 5):
        html = generate_html(p)
        out_path = REPORTS_DIR / f"PHASE{p}_STATUS.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"Generated {out_path.name}")


if __name__ == "__main__":
    main()
