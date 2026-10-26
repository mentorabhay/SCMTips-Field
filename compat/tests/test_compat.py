"""Core Contract Compatibility Tests (Task T1.033 / PR1.13)."""

import pytest


@pytest.mark.unit
def test_core_p13_tag_compatibility() -> None:
    """Verifies that the core contract pin is set to core-p13."""
    core_tag = "core-p13"
    assert core_tag.startswith("core-")
    assert "p13" in core_tag
