"""db_roles flags a superuser DSN default in production code and ignores tests and the admin CLI."""

from pathlib import Path

from tools.checks.db_roles import violations


def test_flags_superuser_default_in_src(tmp_path: Path) -> None:
    src = tmp_path / "services/field-worker/src/field_worker"
    src.mkdir(parents=True)
    (src / "bad.py").write_text('URL = "postgresql://postgres:x@127.0.0.1:5450/field"\n', encoding="utf-8")
    (src / "good.py").write_text('URL = "postgresql://field_worker:x@127.0.0.1:5450/field"\n', encoding="utf-8")
    tests = tmp_path / "services/field-worker/src/field_worker/tests"
    tests.mkdir()
    (tests / "t.py").write_text('URL = "postgresql://postgres:x@h/field"\n', encoding="utf-8")
    assert violations(tmp_path) == ["services/field-worker/src/field_worker/bad.py:1: superuser DSN default"]


def test_repository_is_clean() -> None:
    assert violations() == []
