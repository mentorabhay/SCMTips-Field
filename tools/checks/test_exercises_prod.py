#!/usr/bin/env python3
"""Tests must exercise first-party production code (proposed rule 2.2.a, review §3.6–3.7).

A pytest file FAILS this check when any of these holds:
  E1  it imports no first-party package (field_api, field_worker, erp_sim, field_sap,
      sap_adapter, fake_core, compat, tools), does not use the database or the app
      (psycopg / fastapi TestClient), and does not test a committed artefact under docs/,
      packages/ or compat/;
  E2  it defines a class named ``Py*`` or ``*Reimpl`` (an in-test re-implementation);
  E3  it reads Kotlin/Java source text (``.kt``/``.kts``/``.java`` + ``read_text``): a string
      found in source proves nothing about behaviour; Kotlin is tested by Kotest/JUnit in Gradle.

Exemptions require an entry in docs/STATUS/test_exemptions.yaml with an owner-approved reason.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
FIRST_PARTY = {"field_api", "field_common", "field_worker", "erp_sim", "field_sap", "sap_adapter", "fake_core", "compat", "tools"}
SKIP_DIRS = {".venv", "node_modules", ".git", "build"}
SRC_READ_RE = re.compile(r"\.(kt|kts|java)\b")
# Tests whose subject is a committed artefact (spec doc, contract JSON/YAML, design tokens) are
# legitimate without importing production Python: the artefact *is* the deliverable.
ARTEFACT_RE = re.compile(r"[\"'/](docs|packages|compat)[/\"']")


def collect_test_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("test_*.py"):
        rel = p.relative_to(ROOT)
        if SKIP_DIRS & set(rel.parts):
            continue
        if rel.parts[:2] == ("tools", "checks") and "tests" not in rel.parts:
            continue  # gate scripts named test_*.py, not tests
        if "def test_" in p.read_text(encoding="utf-8"):
            out.append(p)
    return sorted(out)


def _without_code_fixtures(src: str, tree: ast.AST) -> str:
    """Blank out comments and string literals that are themselves Python source (gate-test fixtures)."""
    out = re.sub(r"(?m)^\s*#.*$", "", src)  # whole-line comments (notes saying where coverage moved)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "def test_" in node.value:
            seg = ast.get_source_segment(src, node)
            if seg:
                out = out.replace(seg, '""')
    return out


def problems(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    errs: list[str] = []
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef) and (node.name.startswith("Py") or node.name.endswith("Reimpl")):
            errs.append(f"E2 defines re-implementation class {node.name}")
    artefact_test = bool(ARTEFACT_RE.search(src))
    if not (imported & FIRST_PARTY) and not ({"psycopg", "fastapi"} & imported) and not artefact_test:
        errs.append("E1 imports no first-party module and touches neither the DB nor the app")
    code = _without_code_fixtures(src, tree)
    if "read_text" in code and SRC_READ_RE.search(code):
        errs.append("E3 asserts on Kotlin/Java source text")
    return errs


def main() -> int:
    ex_file = ROOT / "docs" / "STATUS" / "test_exemptions.yaml"
    exempt = {e["path"]: e for e in (yaml.safe_load(ex_file.read_text(encoding="utf-8")) or [])} if ex_file.exists() else {}
    bad: list[str] = []
    for f in collect_test_files():
        rel = f.relative_to(ROOT).as_posix()
        errs = problems(f)
        if errs and not (rel in exempt and exempt[rel].get("owner_approved")):
            bad.append(f"{rel}: " + "; ".join(errs))
    if bad:
        print(f"[FAIL] {len(bad)} test file(s) do not exercise production code:")
        for b in bad:
            print("  -", b)
        return 1
    print("[PASS] all test files exercise first-party production code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
