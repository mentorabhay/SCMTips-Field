#!/usr/bin/env python3
"""SCMTIPS Orphan Code Check (Remediation Rule 2.2 / Task R0.6).

Enforces:
1. Every .kt file lives under <module>/src/(main|test|androidTest)/kotlin of a module
   explicitly included in apps/field-android/settings.gradle.kts.
2. Every .py file lives in a recognized package, script, or test directory, and is imported or tested.
"""

import ast
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


def _imported_modules(py_files: list[Path]) -> set[str]:
    """Every dotted module name imported anywhere (import a.b; from a.b import c -> a.b, a.b.c)."""
    names: set[str] = set()
    for p in py_files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def check_python_orphans() -> list[str]:
    """A module under */src/<pkg>/ must be imported by its dotted name (C4: the old check matched the
    file stem as a bare word anywhere, so dead modules like erp_sim/routes/inbound_delivery.py passed)."""
    violations: list[str] = []
    py_files = [p for p in ROOT.rglob("*.py") if not any(part in p.parts for part in EXCLUDED_PARTS)]
    imported = _imported_modules(py_files)
    for p in py_files:
        rel = p.relative_to(ROOT)
        if len(rel.parts) == 1:
            continue  # root conftest / scripts
        if "tests" in rel.parts or rel.parts[0] in ("scripts", "tools", "compat") or "scripts" in rel.parts:
            continue  # tests and CLIs are entry points
        if "alembic" in rel.parts or "versions" in rel.parts:
            continue  # migrations are loaded by alembic
        if "src" not in rel.parts:
            violations.append(f"Orphan Python file outside recognized src/ package: {rel}")
            continue
        if p.stem in ("__init__", "__main__", "app", "cli"):
            continue  # package markers and service entry points (uvicorn/console scripts)
        parts = rel.parts[rel.parts.index("src") + 1 :]
        dotted = ".".join((*parts[:-1], p.stem))
        if dotted not in imported and not any(i.startswith(dotted + ".") for i in imported):
            violations.append(f"Unimported Python module: {rel} ({dotted})")
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
