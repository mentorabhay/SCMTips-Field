"""Property tests verifying Security & Privacy Baseline (TC1.165 / TC1.170)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.checks.deps import check_licenses, check_lockfiles  # noqa: E402

THREAT_MODEL_PATH = ROOT / "docs" / "security" / "THREAT_MODEL.md"
DATA_CLASS_PATH = ROOT / "docs" / "security" / "DATA_CLASSIFICATION.md"
DPIA_PATH = ROOT / "docs" / "privacy" / "DPIA_STARTER.md"
SECRETS_PATH = ROOT / "docs" / "security" / "SECRETS.md"
DEPS_POLICY_PATH = ROOT / "docs" / "security" / "DEPENDENCY_POLICY.md"


@pytest.mark.property
def test_security_documentation_and_stride_coverage():
    """TC1.170: Threat model, classification and DPIA completeness."""
    assert THREAT_MODEL_PATH.exists()
    threat_text = THREAT_MODEL_PATH.read_text(encoding="utf-8")
    for category in [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information Disclosure",
        "Denial of Service",
        "Elevation of Privilege",
    ]:
        assert category in threat_text, f"Missing STRIDE category: {category}"

    assert DATA_CLASS_PATH.exists()
    class_text = DATA_CLASS_PATH.read_text(encoding="utf-8")
    for tier in ["Public", "Internal", "Confidential", "Restricted-Personal"]:
        assert tier in class_text, f"Missing data classification tier: {tier}"

    # Verify all 12 tables are classified
    tables = [
        "field.site",
        "field.location",
        "field.material",
        "field.device",
        "field.task",
        "field.task_line",
        "field.capture",
        "field.erp_document",
        "field.posting_job",
        "field.outbox",
        "field.idempotency_record",
        "field.role_grant",
    ]
    for tbl in tables:
        assert tbl in class_text, f"Table {tbl} not classified in DATA_CLASSIFICATION.md"

    assert DPIA_PATH.exists()
    dpia_text = DPIA_PATH.read_text(encoding="utf-8")
    assert "DPDP Act 2023" in dpia_text
    assert "GDPR" in dpia_text
    assert "Bystander" in dpia_text
    assert "Retention" in dpia_text


@pytest.mark.property
def test_dependency_policy_and_checker():
    """TC1.165: Dependency policy enforcement."""
    assert DEPS_POLICY_PATH.exists()
    assert check_lockfiles() is True
    assert check_licenses() is True
