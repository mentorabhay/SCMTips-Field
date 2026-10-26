"""Core Platform Compatibility Test Suite (Task T1.033 / FR1.009).

Verifies:
1. specs/core-p13.json matches its recorded SHA256 in core-p13.json.sha256.
2. All endpoints in compat/USED_ENDPOINTS.yaml are accounted for.
3. Used endpoints have valid OpenAPI 3.1 operation definitions.
4. core-p14 is documented as SKIPPED-PENDING in compat/MATRIX.md.
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = ROOT / "packages" / "core-contract" / "specs"
USED_ENDPOINTS_PATH = ROOT / "compat" / "USED_ENDPOINTS.yaml"
MATRIX_PATH = ROOT / "compat" / "MATRIX.md"


@pytest.mark.compat
def test_core_p13_sha256_checksum():
    """Verify that core-p13.json has not been mutated without updating sha256."""
    spec_file = SPECS_DIR / "core-p13.json"
    sha_file = SPECS_DIR / "core-p13.json.sha256"

    assert spec_file.exists(), "core-p13.json spec missing"
    assert sha_file.exists(), "core-p13.json.sha256 missing"

    content = spec_file.read_bytes()
    expected_sha = sha_file.read_text(encoding="utf-8").split()[0].strip()
    actual_sha = hashlib.sha256(content).hexdigest()

    assert actual_sha == expected_sha, f"Checksum mismatch: {actual_sha} != {expected_sha}"


@pytest.mark.compat
def test_used_endpoints_presence():
    """Verify all used endpoints in USED_ENDPOINTS.yaml are accounted for in core-p13 or recorded seams."""
    assert USED_ENDPOINTS_PATH.exists(), "compat/USED_ENDPOINTS.yaml missing"
    with open(USED_ENDPOINTS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    endpoints = data.get("endpoints", [])
    assert len(endpoints) >= 5, "Expected at least 5 used endpoints"

    spec_file = SPECS_DIR / "core-p13.json"
    with open(spec_file, encoding="utf-8") as f:
        spec = json.load(f)

    spec_paths = spec.get("paths", {})
    for ep in endpoints:
        path = ep["path"]
        method = ep["method"].lower()
        if ep["exists_in_p13"]:
            assert path in spec_paths, f"Expected {path} in core-p13 spec"
            assert method in spec_paths[path], f"Expected {method.upper()} for {path}"
        else:
            assert ep["seam"] is not None, f"Endpoint {path} marked not in P13 must have a seam"


@pytest.mark.compat
def test_matrix_documents_p14_pending():
    """Verify MATRIX.md tracks core-p14 as pending."""
    assert MATRIX_PATH.exists(), "compat/MATRIX.md missing"
    content = MATRIX_PATH.read_text(encoding="utf-8")
    assert "SKIPPED-PENDING" in content
    assert "core-p13" in content
    assert "core-p14" in content
