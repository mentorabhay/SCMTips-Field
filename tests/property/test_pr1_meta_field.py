"""Property test verifying docs/META_FIELD.md structure and D1.04 decision (TC1.169)."""

from pathlib import Path
import pytest

DOC_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "META_FIELD.md"


@pytest.mark.property
def test_meta_field_structure_and_decision():
    assert DOC_PATH.exists(), "docs/META_FIELD.md must exist"
    content = DOC_PATH.read_text(encoding="utf-8")

    # Table columns presence
    required_columns = [
        "Capability",
        "Call / API",
        "Device",
        "SDK / Firmware Version",
        "Status",
        "Evidence Path",
        "Notes",
    ]
    for col in required_columns:
        assert col in content, f"Missing required column: {col}"

    # Required status values
    assert "VERIFIED" in content
    assert "UNVERIFIED" in content
    assert "BLOCKED" in content

    # Decision D1.04
    assert "Decision D1.04" in content
    assert "Llama" in content
    assert "open-weights" in content.lower() or "open weights" in content.lower()

    # Hardware status assertions
    assert "Ray-Ban Display" in content
    assert "Mock Device Kit" in content
    assert "tools/spikes/wearables-android/" in content
