#!/usr/bin/env python3
"""SCMTIPS Truth Ledger Generator (Remediation Rule 2.3 / Task R1.2).

Generates docs/STATUS/phase{1..4}.yaml with all tasks initialized to status: unverified.
"""

import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
DOCS_SPEC = ROOT / "docs" / "SPEC"
DOCS_STATUS = ROOT / "docs" / "STATUS"
DOCS_STATUS.mkdir(parents=True, exist_ok=True)


def generate_phase_yaml(phase: int) -> int:
    tasks_file = DOCS_SPEC / f"phase{phase}" / "tasks.json"
    if not tasks_file.exists():
        raise FileNotFoundError(f"Missing {tasks_file}")

    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    entries = []

    for t in tasks:
        entries.append({
            "id": t["id"],
            "title": t["title"],
            "workstream": t["workstream"],
            "role": t["role"],
            "status": "unverified",
            "evidence": [],
            "tests": [],
            "frs": t["frs"],
            "verified_at": None,
            "note": None,
        })

    out_file = DOCS_STATUS / f"phase{phase}.yaml"
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(entries, f, sort_keys=False, allow_unicode=True, indent=2)

    print(f"Generated {out_file} with {len(entries)} unverified entries.")
    return len(entries)


def main() -> int:
    total = 0
    for phase in range(1, 5):
        total += generate_phase_yaml(phase)

    print(f"\n[PASS] Truth ledgers generated: {total} total entries initialized to unverified.")
    assert total == 298, f"Expected 298 tasks, got {total}"
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
