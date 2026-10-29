#!/usr/bin/env python3
"""SCMTIPS Spec JSON Extractor (Remediation Rule 2.3 / Task R1.1).

Extracts phase-specific JSON documents from Plan/scmtips-field-spec.html:
- docs/SPEC/phase<N>/meta.json
- docs/SPEC/phase<N>/tasks.json
- docs/SPEC/phase<N>/fs.json
- docs/SPEC/phase<N>/ts.json
- docs/SPEC/phase<N>/tests.json
"""

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPEC_HTML = ROOT / "Plan" / "scmtips-field-spec.html"
DOCS_SPEC = ROOT / "docs" / "SPEC"

PHASE_TITLES = {
    1: "Foundations, contract and simulated ERP",
    2: "Android Client, Wearables Foundation & Visual Perceptions",
    3: "Warehouse Operations, Picking, Inventory & Core Seams",
    4: "Cell Tower Maintenance, Climb-Safe & Asset Models",
}


def clean_html(raw: str) -> str:
    # Strip HTML tags and normalize whitespace
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    no_entities = (
        no_tags.replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return " ".join(no_entities.split()).strip()


def parse_tasks(text: str) -> dict[int, list[dict[str, Any]]]:
    tasks_by_phase: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    pattern = re.compile(
        r'<tr id="id-(T([1-4])\.\d{3})"[^>]*data-ws="([^"]*)"[^>]*data-role="([^"]*)">\s*'
        r'<td class="id">([^<]+)</td>\s*'
        r'<td class="mono">([^<]+)</td>\s*'
        r'<td><b>(.*?)</b>(?:<br><span class="muted">(.*?)</span>)?(?:<br><span class=dep>(.*?)</span>)?</td>\s*'
        r'<td><span class="role">([^<]+)</span></td>\s*'
        r'<td class="num mono">([^<]+)</td>\s*'
        r'<td class="mono"[^>]*>(.*?)</td>\s*'
        r'<td>(.*?)</td>\s*</tr>'
    )

    for m in pattern.finditer(text):
        task_id = m.group(1)
        phase = int(m.group(2))
        ws = m.group(3)
        role = m.group(4)
        title = clean_html(m.group(7))
        desc = clean_html(m.group(8) or "")
        dep = clean_html(m.group(9) or "")
        days_str = m.group(11).strip()
        deliverable = clean_html(m.group(12))
        done_when_raw = m.group(13)
        
        # Extract referenced FRs from done_when
        frs = re.findall(r"FR[1-4]\.\d{3}", done_when_raw)
        done_when = clean_html(done_when_raw)

        try:
            days = float(days_str)
        except ValueError:
            days = 0.0

        task_obj = {
            "id": task_id,
            "phase": phase,
            "workstream": ws,
            "role": role,
            "title": title,
            "description": desc,
            "depends_on": dep,
            "estimate_days": days,
            "deliverable": deliverable,
            "done_when": done_when,
            "frs": sorted(list(set(frs))),
        }
        tasks_by_phase[phase].append(task_obj)

    return tasks_by_phase


def parse_frs(text: str) -> dict[int, list[dict[str, Any]]]:
    frs_by_phase: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    pattern = re.compile(
        r'<tr id="id-(FR([1-4])\.\d{3})">\s*'
        r'<td class="id">([^<]+)</td>\s*'
        r'<td class="mono"[^>]*>([^<]+)</td>\s*'
        r'<td>(.*?)</td>\s*</tr>'
    )

    for m in pattern.finditer(text):
        fr_id = m.group(1)
        phase = int(m.group(2))
        category = clean_html(m.group(4))
        desc = clean_html(m.group(5))

        frs_by_phase[phase].append({
            "id": fr_id,
            "phase": phase,
            "category": category,
            "description": desc,
        })

    return frs_by_phase


def parse_apis(text: str) -> dict[int, list[dict[str, Any]]]:
    apis_by_phase: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    pattern = re.compile(
        r'<details id="id-(API([1-4])\.\d{2})">\s*'
        r'<summary><span[^>]*>([^<]+)</span><span class="m ([^"]+)">([^<]+)</span><span class="p">([^<]+)(?:<span[^>]*>(.*?)</span>)?</span></summary>\s*'
        r'<div class="inner">(.*?)</div>\s*</details>'
    )

    for m in pattern.finditer(text):
        api_id = m.group(1)
        phase = int(m.group(2))
        method = m.group(5).strip()
        path = m.group(6).strip()
        summary = clean_html(m.group(7) or "")
        inner = clean_html(m.group(8))

        apis_by_phase[phase].append({
            "id": api_id,
            "phase": phase,
            "method": method,
            "path": path,
            "summary": summary,
            "details": inner,
        })

    return apis_by_phase


def parse_properties(text: str) -> dict[int, list[dict[str, Any]]]:
    prs_by_phase: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    pattern = re.compile(
        r'<details[^>]*id="id-(PR([1-4])\.\d{2})">\s*'
        r'<summary><b>([^<]+)</b><span[^>]*>([^<]+)</span><span class="pill[^"]*">([^<]+)</span><span[^>]*>([^<]+)</span></summary>\s*'
        r'<div class="inner">(.*?)</div>\s*</details>'
    )

    for m in pattern.finditer(text):
        pr_id = m.group(1)
        phase = int(m.group(2))
        name = clean_html(m.group(4))
        engine = clean_html(m.group(5))
        runs = clean_html(m.group(6))
        statement = clean_html(m.group(7))

        prs_by_phase[phase].append({
            "id": pr_id,
            "phase": phase,
            "name": name,
            "engine": engine,
            "runs": runs,
            "statement": statement,
        })

    return prs_by_phase


def parse_test_cases(text: str) -> dict[int, list[dict[str, Any]]]:
    tcs_by_phase: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}

    pattern = re.compile(
        r'<tr id="id-(TC([1-4])\.\d{3})">\s*'
        r'<td class="id">([^<]+)</td>\s*'
        r'<td>(.*?)</td>\s*'
        r'<td>(.*?)</td>\s*'
        r'<td>(.*?)</td>\s*'
        r'<td[^>]*>(.*?)</td>\s*</tr>'
    )

    for m in pattern.finditer(text):
        tc_id = m.group(1)
        phase = int(m.group(2))
        action = clean_html(m.group(4))
        setup = clean_html(m.group(5))
        expected = clean_html(m.group(6))
        notes = clean_html(m.group(7))

        tcs_by_phase[phase].append({
            "id": tc_id,
            "phase": phase,
            "action": action,
            "setup": setup,
            "expected": expected,
            "notes": notes,
        })

    return tcs_by_phase


def main() -> int:
    if not SPEC_HTML.exists():
        print(f"[FAIL] Spec HTML file not found at {SPEC_HTML}")
        return 1

    print(f"Reading spec HTML from {SPEC_HTML}...")
    text = SPEC_HTML.read_text(encoding="utf-8", errors="ignore")

    print("Parsing tasks...")
    tasks = parse_tasks(text)
    print("Parsing FRs...")
    frs = parse_frs(text)
    print("Parsing APIs...")
    apis = parse_apis(text)
    print("Parsing properties...")
    prs = parse_properties(text)
    print("Parsing test cases...")
    tcs = parse_test_cases(text)

    for phase in range(1, 5):
        phase_dir = DOCS_SPEC / f"phase{phase}"
        phase_dir.mkdir(parents=True, exist_ok=True)

        # 1. meta.json
        meta_data = {
            "phase": phase,
            "title": PHASE_TITLES.get(phase, f"Phase {phase}"),
            "task_count": len(tasks[phase]),
            "fr_count": len(frs[phase]),
            "api_count": len(apis[phase]),
            "property_count": len(prs[phase]),
            "test_case_count": len(tcs[phase]),
        }
        (phase_dir / "meta.json").write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

        # 2. tasks.json
        (phase_dir / "tasks.json").write_text(json.dumps(tasks[phase], indent=2), encoding="utf-8")

        # 3. fs.json
        fs_data = {
            "phase": phase,
            "functional_requirements": frs[phase],
        }
        (phase_dir / "fs.json").write_text(json.dumps(fs_data, indent=2), encoding="utf-8")

        # 4. ts.json
        ts_data = {
            "phase": phase,
            "apis": apis[phase],
        }
        (phase_dir / "ts.json").write_text(json.dumps(ts_data, indent=2), encoding="utf-8")

        # 5. tests.json
        tests_data = {
            "phase": phase,
            "properties": prs[phase],
            "test_cases": tcs[phase],
        }
        (phase_dir / "tests.json").write_text(json.dumps(tests_data, indent=2), encoding="utf-8")

        print(f"Phase {phase}: wrote meta, tasks ({len(tasks[phase])}), fs ({len(frs[phase])}), ts ({len(apis[phase])}), tests (PR={len(prs[phase])}, TC={len(tcs[phase])}) to {phase_dir}")

    total_tasks = sum(len(tasks[p]) for p in range(1, 5))
    print(f"\n[PASS] Spec JSON extraction complete. Extracted {total_tasks} tasks across Phases 1-4.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
