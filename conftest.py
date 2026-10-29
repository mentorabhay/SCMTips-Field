"""SCMTIPS Field - Root Pytest Configuration and Marker Safety Net (Remediation Rule 2.2 / R0.6).

Automatically assigns pytest markers by file path and test characteristics:
- Tests in property/ dirs or named *property* or containing @given -> property
- Tests in contract/ dirs or named *contract* -> contract
- Tests in compat/ dirs -> compat
- All other tests without a suite marker -> unit

Registers all known custom markers to avoid PytestUnknownMarkWarning.
"""

import pytest


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
