#!/usr/bin/env python3
"""SCMTIPS Orphan Code Check (Remediation Rule 2.2 / Task R0.6).

Enforces:
1. Every .kt file lives under <module>/src/(main|test|androidTest)/kotlin of a module
   explicitly included in apps/field-android/settings.gradle.kts.
2. Every .py file lives in a recognized package, script, or test directory, and is imported or tested.
"""

import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ANDROID_ROOT = ROOT / "apps" / "field-android"
SETTINGS_GRADLE = ANDROID_ROOT / "settings.gradle.kts"

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "reports",
}


def get_included_android_modules() -> set[str]:
    if not SETTINGS_GRADLE.exists():
        return set()
    content = SETTINGS_GRADLE.read_text(encoding="utf-8")
    # Matches include(":app"), include(":core-capture"), etc.
    modules = set(re.findall(r'include\s*\(\s*["\']:([a-zA-Z0-9_-]+)["\']\s*\)', content))
    # Also support multiple arguments include(":a", ":b")
    for block in re.findall(r'include\s*\(([^)]+)\)', content):
        for mod in re.findall(r'["\']:([a-zA-Z0-9_-]+)["\']', block):
            modules.add(mod)
    return modules


def check_kotlin_orphans() -> list[str]:
    violations: list[str] = []
    if not ANDROID_ROOT.exists():
        return violations

    included_modules = get_included_android_modules()
    valid_module_roots = {ANDROID_ROOT / mod for mod in included_modules}

    all_kt_files = list(ANDROID_ROOT.rglob("*.kt"))
    for kt_path in all_kt_files:
        if any(p in kt_path.parts for p in EXCLUDED_PARTS):
            continue

        # Check if kt_path belongs to one of the included modules under src/*/kotlin
        is_valid = False
        for mod_root in valid_module_roots:
            try:
                rel = kt_path.relative_to(mod_root)
                parts = rel.parts
                # rel must look like src/(main|test|androidTest)/kotlin/...
                if len(parts) >= 4 and parts[0] == "src" and parts[1] in ("main", "test", "androidTest") and parts[2] == "kotlin":
                    is_valid = True
                    break
            except ValueError:
                continue

        if not is_valid:
            violations.append(
                f"Orphan Kotlin file (not under an included module's src/*/kotlin): {kt_path.relative_to(ROOT)}"
            )

    return violations


def check_python_orphans() -> list[str]:
    violations: list[str] = []

    # Collect all python imports across the codebase
    all_content: list[str] = []
    py_files = [p for p in ROOT.rglob("*.py") if not any(part in p.parts for part in EXCLUDED_PARTS)]
    for p in py_files:
        with contextlib.suppress(Exception):
            all_content.append(p.read_text(encoding="utf-8", errors="ignore"))
    corpus = "\n".join(all_content)

    [
        ROOT / "services",
        ROOT / "apps",
        ROOT / "packages",
        ROOT / "connectors",
        ROOT / "tools",
        ROOT / "scripts",
        ROOT / "compat",
    ]

    for p in py_files:
        rel = p.relative_to(ROOT)
        # Top-level scripts or root conftest.py are allowed
        if len(rel.parts) == 1:
            continue
        # Tests and scripts are valid entrypoints
        if "tests" in rel.parts or rel.parts[0] in ("scripts", "tools", "compat") or "scripts" in rel.parts:
            continue
        # Alembic migration versions are entrypoints loaded dynamically
        if "alembic" in rel.parts or "versions" in rel.parts:
            continue
        # Check if under a recognized package src
        if "src" not in rel.parts:
            violations.append(f"Orphan Python file outside recognized src/ package: {rel}")
            continue

        stem = p.stem
        if stem == "__init__":
            continue
        # Verify the module is imported somewhere in corpus
        # e.g. "import ...stem" or "from ... import stem" or "from ...stem import"
        pattern = rf"\b(import\s+([a-zA-Z0-9_.]+\.)?{re.escape(stem)}\b|from\s+([a-zA-Z0-9_.]+\.)?{re.escape(stem)}\b|{re.escape(stem)}\.)"
        if not re.search(pattern, corpus):
            violations.append(f"Unimported Python module: {rel}")

    return violations


def main() -> int:
    kt_violations = check_kotlin_orphans()
    py_violations = check_python_orphans()

    total_violations = kt_violations + py_violations
    if total_violations:
        print(f"[FAIL] Found {len(total_violations)} orphan code violation(s):")
        for v in total_violations:
            print(f"  - {v}")
        return 1

    print("[PASS] No orphan files detected. All Kotlin and Python code is properly housed and connected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
