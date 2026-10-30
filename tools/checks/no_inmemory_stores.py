#!/usr/bin/env python3
"""No module-level mutable stores in API code (proposed rule 2.2.b, review §3.10).

Fails on any module-level assignment of a mutable container literal (``{}``, ``[]``,
``dict()``, ``list()``, ``set()``, ``defaultdict(...)``) in field-api route modules
and in packages imported by them. State must live in Postgres behind RLS. Read-only
constants are allowed when they are immutable (tuple, frozenset, MappingProxyType) or
annotated ``Final`` AND named in UPPER_CASE and never mutated (heuristic: not allowed
for dict/list, which are mutable regardless of annotation).

Allow-list: none. A test-only store belongs in tests/.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN = [ROOT / "services" / "field-api" / "src" / "field_api"]
MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter", "InProcessStore"}


def violations_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        func = value.func if isinstance(value, ast.Call) else None
        if isinstance(func, ast.Subscript):  # e.g. InProcessStore[dict[str, Any]]()
            func = func.value
        mutable = isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)) or (
            func is not None and (getattr(func, "id", None) or getattr(func, "attr", None)) in MUTABLE_CALLS
        )
        if not mutable:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if names == ["__all__"]:
            continue
        out.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: module-level mutable store {names}")
    return out


def main() -> int:
    found: list[str] = []
    for base in SCAN:
        for f in sorted(base.rglob("*.py")):
            found.extend(violations_in(f))
    if found:
        print(f"[FAIL] {len(found)} module-level mutable store(s) in API code (state must live in the DB):")
        for v in found:
            print("  -", v)
        return 1
    print("[PASS] no module-level mutable stores in field-api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
