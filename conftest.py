"""SCMTIPS Field - Root Pytest Configuration and Marker Safety Net (Remediation Rule 2.2 / R0.6).

Automatically assigns pytest markers by file path and test characteristics:
- Tests in property/ dirs or named *property* or containing @given -> property
- Tests in contract/ dirs or named *contract* -> contract
- Tests in compat/ dirs -> compat
- All other tests without a suite marker -> unit

Registers all known custom markers to avoid PytestUnknownMarkWarning.
"""

import os
import secrets

import pytest

# Signing keys have no built-in defaults (A-02). Tests get fresh random ones per run unless the
# environment already provides them.
for _name in ("FIELD_JWT_SECRET", "FIELD_CURSOR_HMAC_SECRET", "FIELD_P13F_WEBHOOK_SECRET", "FIELD_EVIDENCE_SECRET"):
    os.environ.setdefault(_name, secrets.token_hex(32))

# Same database roles locally as in CI (.github/workflows/ci.yml): the app and the tests that use
# FIELD_DATABASE_URL connect as the NOBYPASSRLS application role, so RLS really applies. Without this a
# local run fell back to the superuser in 15 test files and in 8 modules and hid RLS bugs that CI found.
os.environ.setdefault("FIELD_DATABASE_URL", "postgresql://field_app:devpassword@127.0.0.1:5450/field")
os.environ.setdefault("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
os.environ.setdefault("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: Unit tests (FR / basic logic / isolation)")
    config.addinivalue_line("markers", "property: Property tests (Hypothesis invariants)")
    config.addinivalue_line("markers", "contract: Contract verification tests")
    config.addinivalue_line("markers", "compat: Compatibility and core contract tests")
    config.addinivalue_line("markers", "security: Security tests (RLS, token, boundary)")
    config.addinivalue_line("markers", "chaos: Chaos engineering tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        # Check current item markers
        existing_marker_names = {mark.name for mark in item.iter_markers()}

        # If item already has a suite marker, don't overwrite
        has_suite_marker = bool(existing_marker_names & {"unit", "property", "contract", "compat"})

        path_str = str(item.fspath).replace("\\", "/").lower()
        node_id_lower = item.nodeid.lower()

        # Deduce marker by path / naming convention
        if "/compat/" in path_str:
            item.add_marker(pytest.mark.compat)
        elif "/contract" in path_str or "contract" in node_id_lower:
            item.add_marker(pytest.mark.contract)
        elif "/property" in path_str or "pr1_" in node_id_lower or "pr2_" in node_id_lower or "pr3_" in node_id_lower or "pr4_" in node_id_lower or "property" in node_id_lower:
            item.add_marker(pytest.mark.property)
        elif not has_suite_marker:
            # Default safety net: every unassigned test belongs to unit suite
            item.add_marker(pytest.mark.unit)


# --- Test harness: behave like a real client and send an Idempotency-Key on every POST -------------
# The API requires Idempotency-Key on POST (FIELD-IDEM-400-MISSING-KEY). Tests that do not set one get a
# fresh key per request, exactly as the phone/console clients do. A test that needs to exercise the
# missing-key path sets the header "X-Test-Omit-Idempotency-Key: 1".
def _install_idempotency_key_default() -> None:
    import uuid as _uuid

    from starlette.testclient import TestClient

    original = TestClient.request
    if getattr(original, "_scmtips_idem_default", False):
        return

    def request(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(method).upper() == "POST":
            headers = dict(kwargs.get("headers") or {})
            lower = {k.lower() for k in headers}
            if "x-test-omit-idempotency-key" in lower:
                headers = {k: v for k, v in headers.items() if k.lower() != "x-test-omit-idempotency-key"}
            elif "idempotency-key" not in lower:
                headers["Idempotency-Key"] = str(_uuid.uuid4())
            kwargs["headers"] = headers
        return original(self, method, url, *args, **kwargs)

    request._scmtips_idem_default = True  # type: ignore[attr-defined]
    TestClient.request = request  # type: ignore[method-assign]


_install_idempotency_key_default()
