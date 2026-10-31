"""Fixture tests for the C1 gates: each check must FAIL on a known-bad input (rule R0.6)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml

from tools.checks import no_inmemory_stores, test_exercises_prod, trace

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- no_inmemory_stores
@pytest.mark.parametrize(
    "src,bad",
    [
        ("STORE: dict[str, int] = {}\n", True),
        ("ITEMS = []\n", True),
        ("from x import InProcessStore\nS = InProcessStore[dict]()\n", True),
        ("from collections import defaultdict\nD = defaultdict(list)\n", True),
        ("ALLOWED = frozenset({'a'})\n", False),
        ("PAIRS = (('O', '0'),)\n", False),
        ("__all__ = ['x']\n", False),
        ("def f():\n    local = {}\n    return local\n", False),
    ],
)
def test_no_inmemory_stores_flags_module_level_mutables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, src: str, bad: bool
) -> None:
    monkeypatch.setattr(no_inmemory_stores, "ROOT", tmp_path)
    f = tmp_path / "mod.py"
    f.write_text(src)
    assert bool(no_inmemory_stores.violations_in(f)) is bad


# ---------------------------------------------------------------- test_exercises_prod
@pytest.mark.parametrize(
    "src,expect",
    [
        ("def test_a():\n    assert 1 + 1 == 2\n", "E1"),
        ("from field_api.serials import x\nclass PyGate: ...\ndef test_a():\n    pass\n", "E2"),
        (
            "from pathlib import Path\nfrom field_api import x\n"
            "def test_a():\n    assert 'K' in Path('A.kt').read_text()\n",
            "E3",
        ),
        ("from field_api.serials import normalise\ndef test_a():\n    assert normalise('O1')\n", None),
        ("import json\ndef test_a():\n    json.loads(open('docs/x.json').read())\n", None),
    ],
)
def test_exercises_prod_classifies(tmp_path: Path, src: str, expect: str | None) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(src)
    errs = test_exercises_prod.problems(f)
    if expect is None:
        assert errs == []
    else:
        assert any(e.startswith(expect) for e in errs), errs


# ---------------------------------------------------------------- trace
def _repo(tmp_path: Path, status: str, tests: list[str], with_junit: bool, migration_rls: bool = True) -> Path:
    root = tmp_path / "repo"
    spec = root / "docs" / "SPEC" / "phase9"
    spec.mkdir(parents=True)
    (spec / "tasks.json").write_text(json.dumps([
        {"id": "T9.001", "title": "Build widget", "description": "Implements API9.01 and table widget",
         "done_when": "PR9.01 holds; TC9.101 passes", "frs": ["FR9.001"], "deliverable": "src/widget.py"}
    ]))
    (spec / "fs.json").write_text(json.dumps({"functional_requirements": [
        {"id": "FR9.001", "description": "The system shall widget. Must TC9.101 PR9.01"}]}))
    (spec / "ts.json").write_text(json.dumps({"apis": [{"id": "API9.01", "method": "POST", "path": "/v1/widgets"}]}))
    contract = root / "packages" / "field-contract"
    contract.mkdir(parents=True)
    (contract / "openapi.json").write_text(json.dumps({"paths": {"/v1/widgets": {"post": {}}}}))
    (root / "src").mkdir()
    (root / "src" / "widget.py").write_text("def widget() -> int:\n    return 42  # real implementation body\n" * 3)
    mig = root / "alembic" / "versions"
    mig.mkdir(parents=True)
    rls = (
        "ALTER TABLE field.widget ENABLE ROW LEVEL SECURITY;\nALTER TABLE field.widget FORCE ROW LEVEL SECURITY;\n"
        "CREATE POLICY tenant_isolation ON field.widget USING (true);\n"
        if migration_rls else ""
    )
    (mig / "w.py").write_text("CREATE TABLE IF NOT EXISTS field.widget (id uuid);\n" + rls + "-- padding " * 10)
    tdir = root / "tests"
    tdir.mkdir()
    (tdir / "test_widget.py").write_text(textwrap.dedent('''
        from hypothesis import given, strategies as st
        @given(st.integers())
        def test_pr9_01_widget(x):
            """PR9.01 / TC9.101 / FR9.001"""
    '''))
    st_dir = root / "docs" / "STATUS"
    st_dir.mkdir(parents=True)
    (st_dir / "phase9.yaml").write_text(yaml.safe_dump([
        {"id": "T9.001", "status": status, "evidence": ["src/widget.py", "alembic/versions/w.py"],
         "tests": tests, "frs": ["FR9.001"]}
    ]))
    if with_junit:
        (root / "reports").mkdir()
        (root / "reports" / "junit.xml").write_text(
            '<testsuites><testsuite><testcase classname="tests.test_widget" name="test_pr9_01_widget"/>'
            "</testsuite></testsuites>"
        )
    return root


def test_trace_passes_on_fully_proven_task(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert violations == []


def test_trace_fails_without_junit_evidence(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=False)
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    kinds = {v.split()[0] for v in violations}
    assert {"D2", "D3", "D4"} <= kinds


def test_trace_rejects_file_only_test_refs(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py"], with_junit=True)
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert any(v.startswith("D2 T9.001") for v in violations)


def test_trace_requires_forced_rls(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True, migration_rls=False)
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert any(v.startswith("D6") and "not forced" in v for v in violations)


def test_trace_requires_api_in_openapi(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    (root / "packages" / "field-contract" / "openapi.json").write_text(json.dumps({"paths": {}}))
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert any(v.startswith("D5") for v in violations)


def test_trace_flags_missing_and_non_list_ledgers(tmp_path: Path) -> None:
    root = _repo(tmp_path, "partial", [], with_junit=False)
    (root / "docs" / "STATUS" / "phase9.yaml").write_text("tasks: []\n")
    violations, _ = trace.validate(root, [])
    assert any("must be a YAML list" in v for v in violations)


def test_trace_flags_stale_completion_claims(tmp_path: Path) -> None:
    root = _repo(tmp_path, "partial", [], with_junit=False)
    (root / "docs" / "report.md").write_text("# Phase 9\nALL PHASES REMEDIATED\n")
    violations, _ = trace.validate(root, [])
    assert any(v.startswith("G1") for v in violations)


# ---------------------------------------------------------------- trace: M3 ledger (owner amendment A-03)
def _m3(root: Path, entries: list[dict[str, object]]) -> None:
    (root / "docs" / "STATUS" / "m3.yaml").write_text(yaml.safe_dump(entries))


def test_trace_m3_partial_entries_pass_and_are_counted(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    _m3(root, [{"id": "M3-S01", "status": "partial", "evidence": [], "tests": [], "frs": []}])
    violations, stats = trace.validate(root, ["reports/junit*.xml"])
    assert violations == []
    assert stats["m3"] == {"partial": 1}


def test_trace_m3_done_needs_evidence_tests_and_device_proof(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    _m3(root, [{"id": "M3-A01", "status": "done", "evidence": ["src/missing.py"], "tests": ["tests/x.py::test_y"],
                "frs": ["FR9.001"]}])
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    kinds = {v.split()[0] for v in violations if "M3-A01" in v}
    assert {"D1", "D2", "M1"} <= kinds
    assert not any(v.startswith("D3 M3-A01") for v in violations)  # FR9.001 has a passing test


def test_trace_m3_done_with_device_proof_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    (root / "docs" / "STATUS" / "device-log.txt").write_text("receive posted on Gen 2, document 4900000106 " * 3)
    _m3(root, [{"id": "M3-P01", "status": "done", "evidence": ["src/widget.py"],
                "tests": ["tests/test_widget.py::test_pr9_01_widget"], "frs": [],
                "device_proof": "docs/STATUS/device-log.txt"}])
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert violations == []


def test_trace_m3_rejects_foreign_ids_and_duplicates(tmp_path: Path) -> None:
    root = _repo(tmp_path, "partial", [], with_junit=False)
    _m3(root, [{"id": "T9.001", "status": "partial"}, {"id": "M3-S01", "status": "partial"},
               {"id": "M3-S01", "status": "partial"}])
    violations, _ = trace.validate(root, [])
    assert any(v.startswith("L1 T9.001") and "not an M3 id" in v for v in violations)
    assert any(v.startswith("L1 M3-S01") and "duplicated" in v for v in violations)


def test_trace_m3_partial_counts_as_not_done_for_completion_claims(tmp_path: Path) -> None:
    root = _repo(tmp_path, "done", ["tests/test_widget.py::test_pr9_01_widget"], with_junit=True)
    _m3(root, [{"id": "M3-S01", "status": "partial"}])
    (root / "docs" / "report.md").write_text("# M3\nALL PHASES REMEDIATED\n")
    violations, _ = trace.validate(root, ["reports/junit*.xml"])
    assert any(v.startswith("G1") for v in violations)
