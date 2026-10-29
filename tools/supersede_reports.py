"""Prepends SUPERSEDED banners to historical phase walkthroughs and reports."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "docs" / "reports"

BANNER = """> [!WARNING]
> **SUPERSEDED ON 2026-10-29**: This historical walkthrough report has been superseded following the Remediation Plan audit (Findings F-01 through F-12). For verified task evidence, live test passes, and honest status ledgers, refer to [`docs/STATUS/phase<N>.yaml`](../STATUS/), [`docs/STATUS/GAPS.md`](../STATUS/GAPS.md), and [`PHASE<N>_STATUS.html`](./PHASE1_STATUS.html).

"""

FILES_TO_SUPERSEDE = [
    "PHASE1_REPORT.md",
    "F1-report.md",
    "SCMTIPS_FIELD_PHASE1_WALKTHROUGH.md",
    "SCMTIPS_FIELD_PHASE1_DETAILED_WALKTHROUGH.md",
    "SCMTIPS_FIELD_PHASE2_DETAILED_WALKTHROUGH.md",
    "SCMTIPS_FIELD_PHASE3_DETAILED_WALKTHROUGH.md",
    "SCMTIPS_FIELD_PHASE4_DETAILED_WALKTHROUGH.md",
]

for fname in FILES_TO_SUPERSEDE:
    p = REPORTS_DIR / fname
    if p.exists():
        content = p.read_text(encoding="utf-8")
        if "SUPERSEDED ON 2026-10-29" not in content:
            p.write_text(BANNER + content, encoding="utf-8")
            print(f"Marked {fname} as SUPERSEDED.")
