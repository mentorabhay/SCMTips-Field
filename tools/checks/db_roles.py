#!/usr/bin/env python3
"""Production code never defaults to the PostgreSQL superuser (CI finding, 2026-10-30).

Eight modules fell back to postgres:...@/field when FIELD_DATABASE_URL was unset. The superuser bypasses
row-level security, so local runs passed while CI (application role, NOBYPASSRLS) failed. field-api
code must use field_api.db (the application role) and field-worker code the worker role.

Allowed: erp-sim (a separate simulator database) and field_api/cli.py (the admin migration CLI).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN = ["services/field-api/src", "services/field-worker/src", "connectors"]
ALLOWED = {"services/field-api/src/field_api/cli.py"}
SUPERUSER_DSN = re.compile(r"postgres(?:ql)?(?:\+\w+)?://postgres[:@]")


def violations(root: Path = ROOT) -> list[str]:
    bad: list[str] = []
    for base in SCAN:
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in ALLOWED or "/tests/" in f"/{rel}":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if SUPERUSER_DSN.search(line):
                    bad.append(f"{rel}:{n}: superuser DSN default")
    return bad


def main() -> int:
    bad = violations()
    if bad:
        print(f"[FAIL] {len(bad)} superuser database default(s) in production code:")
        for b in bad:
            print(f"  - {b}")
        return 1
    print("[PASS] production code connects as the application / worker roles only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
