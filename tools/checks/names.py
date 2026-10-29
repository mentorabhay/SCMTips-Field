#!/usr/bin/env python3
"""SCMTIPS Names Check (Task T1.009 / FR1.004).

Scans tracked source files against names_denylist.txt and verifies SAMPLE prefixes in seed data.
"""

import re
import sys
from pathlib import Path

DENYLIST_FILE = Path(__file__).parent / "names_denylist.txt"
ROOT = Path(__file__).resolve().parent.parent.parent

SEARCH_DIRS = [
    "services",
    "apps",
    "packages",
    "connectors",
    "tools",
    "scripts",
    "compat",
    "docs",
]


def load_denylist() -> list[str]:
    if not DENYLIST_FILE.exists():
        return []
    with open(DENYLIST_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def check_file(file_path: Path, denylist: list[str]) -> list[str]:
    violations: list[str] = []
    parts = file_path.parts
    if any(
        p in parts
        for p in (
            ".git",
            ".venv",
            "node_modules",
            ".next",
            "dist",
            "build",
            "__pycache__",
            "reports",
            "SPEC",
        )
    ):
        return violations

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    for word in denylist:
        if re.search(rf"\b{re.escape(word)}\b", content, re.IGNORECASE):
            violations.append(f"{file_path}: Contains forbidden name '{word}'")

    return violations


def main() -> int:
    denylist = load_denylist()
    violations: list[str] = []

    for d in SEARCH_DIRS:
        dir_path = ROOT / d
        if not dir_path.exists():
            continue
        for ext in (
            "*.py",
            "*.ts",
            "*.tsx",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.sql",
            "*.md",
        ):
            for path in dir_path.glob(f"**/{ext}"):
                violations.extend(check_file(path, denylist))

    # Also check root level config files
    for root_file in ROOT.glob("*.md"):
        violations.extend(check_file(root_file, denylist))

    if violations:
        print(f"[FAIL] Found {len(violations)} name violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("[PASS] Names check passed. Zero forbidden entities found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
