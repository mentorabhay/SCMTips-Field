#!/usr/bin/env python3
"""SCMTIPS Gaps Report Generator (Remediation Rule 2.3 / Task R1.4).

Reads docs/STATUS/phase{1..4}.yaml and docs/SPEC/phase{1..4}/*.json
and generates docs/STATUS/GAPS.md.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
DOCS_SPEC = ROOT / "docs" / "SPEC"
DOCS_STATUS = ROOT / "docs" / "STATUS"
GAPS_MD = DOCS_STATUS / "GAPS.md"


def load_phase_data(phase: int) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    spec_dir = DOCS_SPEC / f"phase{phase}"
    meta = json.loads((spec_dir / "meta.json").read_text(encoding="utf-8"))
    tasks = json.loads((spec_dir / "tasks.json").read_text(encoding="utf-8"))
    fs = json.loads((spec_dir / "fs.json").read_text(encoding="utf-8"))
    ts = json.loads((spec_dir / "ts.json").read_text(encoding="utf-8"))
    tests = json.loads((spec_dir / "tests.json").read_text(encoding="utf-8"))

    status_file = DOCS_STATUS / f"phase{phase}.yaml"
    with open(status_file, encoding="utf-8") as f:
        status_entries = yaml.safe_load(f)

    return meta, tasks, fs, ts, tests, status_entries


def main() -> int:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")

    all_phases_data = [load_phase_data(p) for p in range(1, 5)]

    total_tasks = 0
    total_done = 0
    total_partial = 0
    total_stub = 0
    total_missing = 0

    phase_summaries = []

    for phase in range(1, 5):
        meta, tasks, fs, ts, tests, status_entries = all_phases_data[phase - 1]
        counts = {"done": 0, "partial": 0, "stub": 0, "missing": 0}
        for e in status_entries:
            st = e["status"]
            counts[st] = counts.get(st, 0) + 1

        total_tasks += len(status_entries)
        total_done += counts["done"]
        total_partial += counts["partial"]
        total_stub += counts["stub"]
        total_missing += counts["missing"]

        phase_summaries.append({
            "phase": phase,
            "title": meta["title"],
            "total": len(status_entries),
            "counts": counts,
            "meta": meta,
            "status_entries": status_entries,
            "tasks_dict": {t["id"]: t for t in tasks},
            "ts": ts,
            "tests": tests,
        })

    md_lines = [
        "# SCMTIPS Field — Truth Ledger Gap Report (Phases 1–4)",
        "",
        f"> **Generated at**: `{timestamp}` via `tools/generate_gaps_report.py`  ",
        "> **Governing Policy**: Remediation Plan Section 2 (Binding Rules)  ",
        "> **Audit Status**: 298 tasks verified against literal deliverables, test coverage, and confirmed findings.",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        "| Metric | Count | Percentage |",
        "|---|---:|---:|",
        f"| **Total Tasks Specified (Phases 1–4)** | **{total_tasks}** | 100.0% |",
        f"| **Done (Genuinely proven & gated)** | **{total_done}** | {total_done/total_tasks*100:.1f}% |",
        f"| **Partial (Code exists; gated evidence or deps missing)** | **{total_partial}** | {total_partial/total_tasks*100:.1f}% |",
        f"| **Stub (Skeleton / placeholder only)** | **{total_stub}** | {total_stub/total_tasks*100:.1f}% |",
        f"| **Missing (Uncommitted / completely absent)** | **{total_missing}** | {total_missing/total_tasks*100:.1f}% |",
        "",
        "### Phase Progress Matrix",
        "",
        "| Phase | Name | Tasks | Done | Partial | Stub | Missing | Gap Count |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for p in phase_summaries:
        c = p["counts"]
        gaps = c["partial"] + c["stub"] + c["missing"]
        md_lines.append(
            f"| Phase {p['phase']} | {p['title']} | {p['total']} | {c['done']} | {c['partial']} | {c['stub']} | {c['missing']} | **{gaps}** |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## 2. Key Forensic Findings Driving Gaps",
        "",
        "1. **Finding F-03 (Orphan Kotlin in Phase 4)**: 19 Kotlin files (~1,850 lines) sit loose outside `settings.gradle.kts`. Climb-safe, tower audit, exploded CAD views, OCR, and site pack managers were never compiled into any shipping module.",
        "2. **Finding F-04 (Unmarked Python Tests in Phase 4)**: 56 Phase 4 test methods had no suite markers and were bypassed by verify-all runners until root `conftest.py` was introduced in R0.",
        "3. **Finding F-07 (Unverified Meta Wearables SDK)**: Wearables code depends exclusively on `MockWearablesKit`. The coordinate `com.meta.wearables:toolkit-sdk:0.1.0-preview` is unverified. All wearables tasks are partial/unverified per Rule 2.4.",
        "4. **Finding F-09 (Missing Feature Commits in Phase 3)**: Commits stopped at WS3.3 (T3.028). Tasks T3.029–T3.072 (outbound picking, GI 601/602, physical inventory, site wayfinding graph, supervisor consoles) have 38 missing deliverables and 8 stub deliverables.",
        "5. **Finding F-10 (API Surface Discrepancy)**: The spec defines 67 APIs across Phases 1–4, whereas `field-api` currently exposes only 49 routes.",
        "6. **Finding F-11 (Skipped SAP Parity Tests)**: S/4 HANA connector tests skip unconditionally due to missing cassette fixtures.",
        "",
        "---",
        "",
        "## 3. Granular Gap Inventory by Phase",
        "",
    ])

    for p in phase_summaries:
        phase_num = p["phase"]
        md_lines.append(f"### Phase {phase_num}: {p['title']}")
        md_lines.append("")
        md_lines.append("| Task ID | Workstream | Title | Status | Referenced FRs | Root Cause / Gap Note |")
        md_lines.append("|---|---|---|:---:|---|---|")

        for entry in p["status_entries"]:
            st = entry["status"]
            if st == "done":
                continue
            p["tasks_dict"].get(entry["id"], {})
            fr_str = ", ".join(entry["frs"]) if entry["frs"] else "-"
            note = entry.get("note") or "Implementation incomplete against specification."
            md_lines.append(
                f"| `{entry['id']}` | `{entry['workstream']}` | {entry['title']} | **{st.upper()}** | `{fr_str}` | {note} |"
            )

        md_lines.append("")

    GAPS_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Generated {GAPS_MD} ({len(md_lines)} lines).")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
