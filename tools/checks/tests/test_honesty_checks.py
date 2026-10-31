"""Unit and fixture tests for honesty checks (Task R0.6).

Verifies that no_fake_gates, orphans, test_collection, and conventions checks
correctly detect violations on known failing fixtures and pass on valid code.
"""

from pathlib import Path

import pytest

from tools.checks.conventions import validate_branch_name, validate_commit_message
from tools.checks.no_fake_gates import check_file as check_fake_gates_file


@pytest.mark.unit
def test_no_fake_gates_detects_violations(tmp_path: Path) -> None:
    # Passing clean file
    clean_file = tmp_path / "clean_job.py"
    clean_file.write_text("def run():\n    return 0\n", encoding="utf-8")
    assert check_fake_gates_file(clean_file) == []

    # Failing file 1: print('... clean')
    fake_semgrep = tmp_path / "fake_semgrep.py"
    fake_semgrep.write_text("print('Semgrep clean')\n", encoding="utf-8")
    violations = check_fake_gates_file(fake_semgrep)
    assert len(violations) > 0
    assert "Fake clean print pattern" in violations[0]

    # Failing file 2: echo [PASS] simulated execution
    fake_gradlew = tmp_path / "gradlew"
    fake_gradlew.write_text('#!/bin/bash\necho "[PASS] gradlew simulated execution"\n', encoding="utf-8")
    violations = check_fake_gates_file(fake_gradlew)
    assert len(violations) >= 2
    assert any("Simulated execution" in v for v in violations)

    # Failing file 3: unconditional exit 0 in wrapper
    fake_wrapper = tmp_path / "run.sh"
    fake_wrapper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    violations = check_fake_gates_file(fake_wrapper)
    assert len(violations) > 0
    assert any("hard-coded exit 0" in v for v in violations)

    # Failing file 4: a report builder that spells its results
    fake_report = tmp_path / "build_report.py"
    fake_report.write_text('rows = ["| **semgrep** | SAST | **PASS** |", "- trivy → PASS"]\n', encoding="utf-8")
    violations = check_fake_gates_file(fake_report)
    assert any("Hard-coded PASS claim" in v for v in violations)


@pytest.mark.unit
def test_conventions_validates_commits() -> None:
    # Valid commits
    valid, _ = validate_commit_message("feat(phase4-ws4.9): complete task (tasks T4.027-T4.028)")
    assert valid is True

    valid, _ = validate_commit_message("docs: establish remediation plan (tasks R0.1)")
    assert valid is True

    valid, _ = validate_commit_message("remediation(r0): make gates honest")
    assert valid is True

    # M3 slice IDs (owner amendment A-03): M3-<track S|A|P><two digits>, or M3-00
    valid, _ = validate_commit_message("feat(assistant): rules fallback (M3-A03)")
    assert valid is True
    valid, _ = validate_commit_message("feat(assistant): something (M3-X1)")
    assert valid is False

    # Invalid: no conventional prefix
    valid, msg = validate_commit_message("just fixed something T1.001")
    assert valid is False
    assert "conventional prefix" in msg

    # Invalid: missing task ID
    valid, msg = validate_commit_message("feat(android): add new screen")
    assert valid is False
    assert "task ID" in msg

    # Invalid: empty message
    valid, msg = validate_commit_message("")
    assert valid is False


@pytest.mark.unit
def test_conventions_validates_branches() -> None:
    assert validate_branch_name("main")[0] is True
    assert validate_branch_name("master")[0] is True
    assert validate_branch_name("feat/ws1.1-setup")[0] is True
    assert validate_branch_name("remediation/r0-honest-gates")[0] is True

    # Invalid branches
    assert validate_branch_name("")[0] is False
    assert validate_branch_name("random-branch-no-type")[0] is False
    assert validate_branch_name("feat/")[0] is False
    # owner amendment A-01: the M1 slice branch
    assert validate_branch_name("slice/m1-field-test")[0] is True
    assert validate_branch_name("slice/")[0] is False


@pytest.mark.unit
def test_conventions_checks_every_commit_not_only_the_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The old NUL-pair split parsed only the newest commit; an older bad commit must be reported."""
    import subprocess

    import tools.checks.conventions as conv

    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    for msg in ("bad message without prefix", "feat(x): good one (T1.001)\n\nbody line"):
        (tmp_path / "f").write_text(msg, encoding="utf-8")
        git("add", "f")
        git("commit", "-q", "-m", msg)
    monkeypatch.setattr(conv, "ROOT", tmp_path)
    violations = conv.check_git_history(max_commits=10)
    assert len(violations) == 1 and "bad message without prefix" in violations[0]
