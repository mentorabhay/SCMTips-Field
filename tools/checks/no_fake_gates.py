#!/usr/bin/env python3
"""SCMTIPS No Fake Gates Check (Remediation Rule 2.1 / Task R0.6).

Verifies that scripts, checks, and build wrappers do not contain fake pass patterns:
- print('... clean') / print("... clean")
- echo PASS / echo [PASS]
- simulated execution
- hard-coded exit 0 in wrapper scripts
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

SCAN_TARGETS = [
    ROOT / "scripts",
    ROOT / "tools" / "checks",
    ROOT / "apps" / "field-android" / "gradlew",
    ROOT / "apps" / "field-android" / "gradlew.bat",
]

FORBIDDEN_PATTERNS = [
    (re.compile(r"print\s*\(\s*['\"][^'\"]*clean['\"]\s*\)", re.IGNORECASE), "Fake clean print pattern"),
    (re.compile(r"echo\s+.*PASS", re.IGNORECASE), "Fake echo PASS pattern"),
    (re.compile(r"['\"]simulated execution['\"]|simulated execution", re.IGNORECASE), "Simulated execution stub pattern"),
]

WRAPPER_EXIT_ZERO = re.compile(r"^\s*exit\s+0\s*$", re.MULTILINE)


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    if path.name == "no_fake_gates.py":
        return violations
    if "__pycache__" in path.parts or "tests" in path.parts:
        return violations

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    for pat, desc in FORBIDDEN_PATTERNS:
        matches = pat.findall(content)
        if matches:
            violations.append(f"{path}: Found forbidden fake gate pattern: {desc} ({matches[0]!r})")

    # In wrapper scripts (.sh, .bat, gradlew), flag unconditional exit 0
    if path.name in ("gradlew", "gradlew.bat") or path.suffix in (".sh", ".bat"):
        # Match lines that are just 'exit 0' without conditional context
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in ("exit 0", "exit /b 0"):
                violations.append(f"{path}: Found hard-coded exit 0 in build wrapper")

    return violations


def scan_path(target: Path) -> list[str]:
    violations: list[str] = []
    if not target.exists():
        return violations

    if target.is_file():
        violations.extend(check_file(target))
    elif target.is_dir():
        for file_path in target.rglob("*"):
            if file_path.is_file():
                violations.extend(check_file(file_path))
    return violations


def main() -> int:
    all_violations: list[str] = []
    for target in SCAN_TARGETS:
        all_violations.extend(scan_path(target))

    if all_violations:
        print(f"[FAIL] Found {len(all_violations)} fake gate violation(s):")
        for v in all_violations:
            print(f"  - {v}")
        return 1

    print("[PASS] No fake gates detected. All scripts and wrappers are honest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
