#!/usr/bin/env python3
"""SCMTIPS Test Collection Check (Remediation Rule 2.2 / Task R0.6).

Verifies that EVERY pytest test in the repository is collected and assigned to at least
one verify-all test job (unit, property, contract, compat). Fails if any test is uncollected
or unmarked.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def get_collected_tests(cmd: list[str]) -> set[str]:
    res = subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    tests = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        # Test node IDs contain '::'
        if "::" in line and not line.startswith("=") and not line.startswith("<") and not line.startswith("warnings summary"):
            # Clean up line: take the first token before space if any
            node_id = line.split()[0]
            if "::" in node_id:
                tests.add(node_id)
    return tests


def main() -> int:
    print("Collecting all pytest tests in repository...")
    all_tests = get_collected_tests(["uv", "run", "pytest", "--collect-only"])
    if not all_tests:
        print("[FAIL] No tests collected by pytest. Check repository structure.")
        return 1

    print(f"Total collected tests: {len(all_tests)}")

    # Collect tests selected by verify-all jobs:
    # 1. unit marker
    unit_tests = get_collected_tests(["uv", "run", "pytest", "-m", "unit", "--collect-only"])
    # 2. property marker
    prop_tests = get_collected_tests(["uv", "run", "pytest", "-m", "property", "--collect-only"])
    # 3. contract marker
    contract_tests = get_collected_tests(["uv", "run", "pytest", "-m", "contract", "--collect-only"])
    # 4. compat directory
    compat_tests = get_collected_tests(["uv", "run", "pytest", "compat/tests", "--collect-only"])

    gated_tests = unit_tests | prop_tests | contract_tests | compat_tests
    unmarked_tests = all_tests - gated_tests

    if unmarked_tests:
        print(f"[FAIL] Found {len(unmarked_tests)} test(s) NOT covered by any verify-all test gate:")
        for t in sorted(unmarked_tests):
            print(f"  - {t}")
        return 1

    print(f"[PASS] All {len(all_tests)} tests are accounted for in verify-all gates (unit={len(unit_tests)}, property={len(prop_tests)}, contract={len(contract_tests)}, compat={len(compat_tests)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
