#!/usr/bin/env python3
"""SCMTIPS Trace Check — enforces rule 2.3 ("done means proven") for real.

Rewritten in C1 (review §3.2). The previous version checked only that evidence paths existed.

For each ledger ``docs/STATUS/phase<N>.yaml`` (must be a YAML list):
  L1  the ledger has exactly one entry per spec task (``docs/SPEC/phase<N>/tasks.json``)
  L2  every status is one of done | partial | stub | missing | deferred | unverified
For every ``done`` entry:
  D1  every evidence path exists, is a file of >= 64 bytes, and is not a placeholder
  D2  at least one listed test is a node id (``path::name``) that PASSED in the supplied junit XML
  D3  every FR the task references has >= 1 passing test that names the FR, or names a TC/PR
      id that the FR's spec text lists
  D4  every PR id in the task text has a passing generator-based test carrying the id in its
      name or docstring (Python ``@given``; Kotlin file importing ``io.kotest.property``)
  D5  every API id in the task text is present in the exported OpenAPI (field-api ∪ erp-sim)
      with the spec's method and path
  D6  every migration listed as evidence enables AND forces RLS and creates a policy for each
      table it creates. (Spec column matching is NOT implemented yet; reported as such.)
Global:
  G1  no report under docs/ claims completion unless it carries the SUPERSEDED banner or is
      generated from the ledger (marker ``<!-- generated-from-ledger -->``)

Junit sources: ``--junit <glob>`` (repeatable). Without junit evidence every done task fails D2:
completion can't be proven without a test run.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent.parent
VALID = {"done", "partial", "stub", "missing", "deferred", "unverified"}
# Accept "FR3.042" in prose and "fr3_042" in test names; "_" is a word char, so no \b.
_B = r"(?<![A-Za-z0-9])"
_E = r"(?![0-9])"
FR_RE = re.compile(_B + r"FR([1-9])[._]?(\d{3})" + _E, re.I)
TC_RE = re.compile(_B + r"TC([1-9])[._]?(\d{3})" + _E, re.I)
PR_RE = re.compile(_B + r"PR([1-9])[._]?(\d{2})" + _E, re.I)
API_RE = re.compile(_B + r"API([1-9])[._]?(\d{2})" + _E, re.I)
CLAIM_RE = re.compile(r"ALL PHASES REMEDIATED|100% complete|fully complete|PHASE COMPLETE", re.I)
PLACEHOLDER_RE = re.compile(r"\bPLACEHOLDER\b|NOT_IMPLEMENTED_PLACEHOLDER")


def ids(regex: re.Pattern[str], text: str, prefix: str) -> set[str]:
    return {f"{prefix}{a}.{b}" for a, b in regex.findall(text or "")}


@dataclass
class PassedTest:
    node: str  # canonical "path::name" (python) or "Class::name" (kotlin)
    ids: set[str] = field(default_factory=set)
    generator: bool = False


@dataclass
class Evidence:
    passed: dict[str, PassedTest]
    junit_files: list[str]


def _py_index(root: Path, rel: str) -> dict[str, tuple[str, bool]]:
    """Map test function name -> (name + docstring text, is @given) for one python file."""
    out: dict[str, tuple[str, bool]] = {}
    try:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            gen = any(
                (isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "given")
                for d in node.decorator_list
            )
            out[node.name] = (node.name + " " + (ast.get_docstring(node) or ""), gen)
    return out


def load_evidence(root: Path, junit_globs: list[str]) -> Evidence:
    files = sorted({f for g in junit_globs for f in glob.glob(str(root / g), recursive=True)})
    passed: dict[str, PassedTest] = {}
    py_cache: dict[str, dict[str, tuple[str, bool]]] = {}
    kt_files = {p.stem: p for p in root.glob("apps/field-android/**/src/test/kotlin/**/*.kt")}
    for f in files:
        for tc in ET.parse(f).getroot().iter("testcase"):
            if any(child.tag in ("failure", "error", "skipped") for child in tc):
                continue
            cls, name = tc.attrib.get("classname", ""), tc.attrib.get("name", "")
            base = name.split("[")[0]
            stem = cls.rsplit(".", 1)[-1]
            if stem in kt_files and kt_files[stem].suffix == ".kt":
                ktxt = kt_files[stem].read_text(encoding="utf-8")
                node = f"{kt_files[stem].relative_to(root).as_posix()}::{base}"
                pt = PassedTest(node, set(), "io.kotest.property" in ktxt)
                text = name
            else:
                rel = cls.replace(".", "/") + ".py"
                if not (root / rel).exists():
                    # classname may include a test class: a.b.test_mod.TestX
                    parts = cls.split(".")
                    rel = "/".join(parts[:-1]) + ".py"
                if rel not in py_cache:
                    py_cache[rel] = _py_index(root, rel) if (root / rel).exists() else {}
                text, gen = py_cache[rel].get(base, (base, False))
                node = f"{rel}::{base}"
                pt = PassedTest(node, set(), gen)
            pt.ids = ids(FR_RE, text, "FR") | ids(TC_RE, text, "TC") | ids(PR_RE, text, "PR")
            prev = passed.get(node)
            if prev:
                prev.ids |= pt.ids
                prev.generator = prev.generator or pt.generator
            else:
                passed[node] = pt
    return Evidence(passed, files)


def load_spec(root: Path, phase: int) -> dict[str, Any]:
    d = root / "docs" / "SPEC" / f"phase{phase}"
    tasks = json.loads((d / "tasks.json").read_text(encoding="utf-8"))
    frs = json.loads((d / "fs.json").read_text(encoding="utf-8"))["functional_requirements"]
    apis = json.loads((d / "ts.json").read_text(encoding="utf-8"))["apis"]
    fr_refs = {fr["id"]: ids(TC_RE, fr["description"], "TC") | ids(PR_RE, fr["description"], "PR") for fr in frs}
    return {"tasks": {t["id"]: t for t in tasks}, "fr_refs": fr_refs, "apis": {a["id"]: a for a in apis}}


def norm_path(p: str) -> str:
    p = p.split("?")[0].rstrip("/")
    p = re.sub(r"\(.*\)$", "", p)
    return re.sub(r"\{[^}]+\}", "{}", p)


def load_openapi_ops(root: Path) -> set[tuple[str, str]] | None:
    ops: set[tuple[str, str]] = set()
    for f in ("packages/field-contract/openapi.json", "packages/field-contract/erp-sim.openapi.json"):
        p = root / f
        if p.exists():
            doc = json.loads(p.read_text(encoding="utf-8"))
            for path, methods in doc.get("paths", {}).items():
                for m in methods:
                    ops.add((m.upper(), norm_path(path)))
    return ops or None


def check_migration(text: str) -> list[str]:
    errs = []
    for tbl in re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([\w.]+)", text, re.I):
        t = re.escape(tbl)
        if not re.search(rf"ALTER TABLE\s+{t}\s+ENABLE ROW LEVEL SECURITY", text, re.I):
            errs.append(f"{tbl}: RLS not enabled")
        if not re.search(rf"ALTER TABLE\s+{t}\s+FORCE ROW LEVEL SECURITY", text, re.I):
            errs.append(f"{tbl}: RLS not forced")
        if not re.search(rf"CREATE POLICY\s+\w+\s+ON\s+{t}\b", text, re.I):
            errs.append(f"{tbl}: no policy")
    return errs


def validate(root: Path, junit_globs: list[str]) -> tuple[list[str], dict[str, Any]]:
    violations: list[str] = []
    ev = load_evidence(root, junit_globs)
    ops = load_openapi_ops(root)
    stats: dict[str, Any] = {"junit_files": ev.junit_files, "passed_tests": len(ev.passed), "phases": {}}
    any_not_done = False
    for lf in sorted((root / "docs" / "STATUS").glob("phase*.yaml")):
        phase = int(re.findall(r"\d+", lf.stem)[0])
        data = yaml.safe_load(lf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            violations.append(f"{lf.name}: ledger must be a YAML list")
            continue
        spec = load_spec(root, phase)
        seen = [e.get("id") for e in data]
        missing = set(spec["tasks"]) - set(seen)
        extra = set(seen) - set(spec["tasks"])
        dup = {x for x in seen if seen.count(x) > 1}
        for m in sorted(missing):
            violations.append(f"L1 {m}: spec task missing from {lf.name}")
        for x in sorted(extra):
            violations.append(f"L1 {x}: not a spec task")
        for x in sorted(dup):
            violations.append(f"L1 {x}: duplicated in ledger")
        counts: dict[str, int] = {}
        for e in data:
            tid, st = e.get("id", "?"), e.get("status")
            counts[st] = counts.get(st, 0) + 1
            if st not in VALID:
                violations.append(f"L2 {tid}: invalid status {st!r}")
                continue
            if st != "done":
                any_not_done = True
                continue
            task = spec["tasks"].get(tid, {})
            text = " ".join(str(task.get(k, "")) for k in ("title", "description", "done_when"))
            # D1
            evid = e.get("evidence") or []
            if not evid:
                violations.append(f"D1 {tid}: done without evidence")
            for p in evid:
                fp = root / p
                if not fp.is_file():
                    violations.append(f"D1 {tid}: evidence is not an existing file: {p}")
                elif fp.stat().st_size < 64 or PLACEHOLDER_RE.search(fp.read_text(encoding="utf-8", errors="ignore")):
                    violations.append(f"D1 {tid}: evidence is trivial or placeholder: {p}")
            # D2
            tests = [t for t in (e.get("tests") or []) if "::" in t]
            passing = [ev.passed[t] for t in tests if t in ev.passed]
            if not passing:
                violations.append(f"D2 {tid}: no listed test node passed in junit ({len(e.get('tests') or [])} listed)")
            # D3
            all_ids: set[str] = set().union(*(p.ids for p in ev.passed.values())) if ev.passed else set()
            for fr in e.get("frs") or task.get("frs") or []:
                refs = {fr} | spec["fr_refs"].get(fr, set())
                if not (refs & all_ids):
                    violations.append(f"D3 {tid}: {fr} has no passing test (looked for {sorted(refs)})")
            # D4
            for pr in sorted(ids(PR_RE, text, "PR")):
                if not any(p.generator and pr in p.ids for p in ev.passed.values()):
                    violations.append(f"D4 {tid}: {pr} has no passing generator-based test")
            # D5
            for api in sorted(ids(API_RE, text, "API")):
                a = spec["apis"].get(api)
                if a is None:
                    violations.append(f"D5 {tid}: {api} not in spec ts.json (extraction gap)")
                elif ops is None:
                    violations.append(f"D5 {tid}: no exported OpenAPI to check {api}")
                elif (a["method"].upper(), norm_path(a["path"])) not in ops:
                    violations.append(f"D5 {tid}: {api} {a['method']} {a['path']} not in OpenAPI")
            # D6
            for p in evid:
                if "alembic/versions" in p and (root / p).is_file():
                    for err in check_migration((root / p).read_text(encoding="utf-8")):
                        violations.append(f"D6 {tid}: {p}: {err}")
        stats["phases"][phase] = counts
    # G1
    if any_not_done:
        for f in list(root.glob("docs/**/*.md")) + list(root.glob("docs/**/*.html")):
            s = f.read_text(encoding="utf-8", errors="ignore")
            if CLAIM_RE.search(s) and "SUPERSEDED" not in s and "generated-from-ledger" not in s:
                violations.append(f"G1 {f.relative_to(root).as_posix()}: claims completion while ledger has non-done tasks")
    return violations, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", action="append", default=[], help="glob(s) of junit XML, relative to repo root")
    ap.add_argument("--json-out", default="reports/trace.json")
    a = ap.parse_args(argv)
    violations, stats = validate(ROOT, a.junit or ["reports/junit*.xml", "apps/field-android/**/build/test-results/**/*.xml"])
    out = ROOT / a.json_out
    out.parent.mkdir(parents=True, exist_ok=True)
    by_kind: dict[str, int] = {}
    for v in violations:
        by_kind[v.split()[0]] = by_kind.get(v.split()[0], 0) + 1
    out.write_text(json.dumps({"violations": violations, "by_kind": by_kind, **stats}, indent=1), encoding="utf-8")
    print(f"junit files: {len(stats['junit_files'])}; passed tests indexed: {stats['passed_tests']}")
    for ph, c in sorted(stats["phases"].items()):
        print(f"phase {ph}: {c}")
    if violations:
        print(f"[FAIL] {len(violations)} trace violation(s): {by_kind}")
        for v in violations[:200]:
            print("  -", v)
        if len(violations) > 200:
            print(f"  ... {len(violations) - 200} more in {a.json_out}")
        return 1
    print("[PASS] every done task is proven (D6 spec-column check not implemented; see docstring)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
