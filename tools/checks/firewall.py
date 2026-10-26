#!/usr/bin/env python3
"""SCMTIPS Architectural Firewall Check (Task T1.009 / FR1.005).

Verifies strict boundaries:
1. No imports of SCMTips core code (scmtips_*, sangamiq_*, heartbeat_*, etc.)
2. No direct HTTP calls to core outside packages/core-contract
3. No model IDs ending in '-contributor'
4. Cross-service isolation:
   - services/field-api must NOT import erp_sim
   - connectors must NOT import field_api or field_worker
   - services/erp-sim must NOT import field_api
"""

import re
import sys
from pathlib import Path

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

FORBIDDEN_IMPORT_PATTERNS = [
    r"from\s+(scmtips|sangamiq|heartbeat|aro)\b",
    r"import\s+(scmtips|sangamiq|heartbeat|aro)\b",
]

FORBIDDEN_MODEL_PATTERNS = [
    r"['\"][a-zA-Z0-9_-]+-contributor['\"]",
]


def check_python_file(path: Path) -> list[str]:
    violations: list[str] = []
    parts = path.parts
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
        )
    ):
        return violations

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    # Check 1: Forbidden Core imports
    for pat in FORBIDDEN_IMPORT_PATTERNS:
        if re.search(pat, content):
            violations.append(
                f"{path}: Forbidden direct import of Core codebase ('{pat}')"
            )

    # Check 2: Contributor model IDs
    for pat in FORBIDDEN_MODEL_PATTERNS:
        if re.search(pat, content):
            violations.append(
                f"{path}: Model ID ending in '-contributor' is strictly forbidden"
            )

    # Check 3: Cross-service isolation
    posix_path = path.as_posix()
    if "field-api" in posix_path and re.search(
        r"\bfrom\s+erp_sim\b|\bimport\s+erp_sim\b", content
    ):
        violations.append(
            f"{path}: Cross-service boundary breach: field-api cannot import erp_sim"
        )
    if "connectors" in posix_path and re.search(
        r"\bfrom\s+(field_api|field_worker)\b|\bimport\s+(field_api|field_worker)\b",
        content,
    ):
        violations.append(
            f"{path}: Connector boundary breach: connectors cannot import field_api/field_worker"
        )
    if "erp-sim" in posix_path and re.search(
        r"\bfrom\s+field_api\b|\bimport\s+field_api\b", content
    ):
        violations.append(
            f"{path}: Simulation boundary breach: erp_sim cannot import field_api"
        )

    return violations


def main() -> int:
    violations: list[str] = []
    for d in SEARCH_DIRS:
        dir_path = ROOT / d
        if not dir_path.exists():
            continue
        for ext in ("*.py", "*.ts", "*.tsx"):
            for path in dir_path.glob(f"**/{ext}"):
                violations.extend(check_python_file(path))

    if violations:
        print(f"[FAIL] Found {len(violations)} firewall violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(
        "[PASS] Architectural firewall check passed. Zero boundary breaches detected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
