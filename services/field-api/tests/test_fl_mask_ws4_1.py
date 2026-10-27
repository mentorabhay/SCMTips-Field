"""Unit test for functional location mask validator (Task T4.003 / FR4.008 / TC4.105)."""

import pytest
from field_api.sites.fl_mask import validate_fl_code


VALID_CODES = [
    ("IN01-TWR-0042", "tower_site", None, 1),
    ("IN01-TWR-0042-T01", "tower", "IN01-TWR-0042", 2),
    ("IN01-TWR-0042-T01-SA", "sector", "IN01-TWR-0042-T01", 3),
    ("IN01-TWR-0042-T01-SB", "sector", "IN01-TWR-0042-T01", 3),
    ("IN01-TWR-0042-T01-SC-L01", "level", "IN01-TWR-0042-T01-SC", 4),
    ("IN01-TWR-0042-T01-SD-L04-P01", "position", "IN01-TWR-0042-T01-SD-L04", 5),
    ("IN01-TWR-0042-T01-SA-L03-P02", "position", "IN01-TWR-0042-T01-SA-L03", 5),
    ("IN01-TWR-0042-SH", "shelter", "IN01-TWR-0042", 2),
    ("IN01-TWR-0042-SH-R01", "rack", "IN01-TWR-0042-SH", 3),
    ("IN01-TWR-0042-SH-R02-S03", "rack_slot", "IN01-TWR-0042-SH-R02", 4),
]

INVALID_CODES = [
    ("INVALID", "INVALID"),
    ("IN01-WAREHOUSE-001", "IN01-WAREHOUSE-001"),
    ("IN01-TWR-42", "IN01-TWR-42"),
    ("IN01-TWR-0042-XYZ", "XYZ"),
    ("IN01-TWR-0042-T1", "T1"),
    ("IN01-TWR-0042-T01-SE", "SE"),
    ("IN01-TWR-0042-T01-SA-LEVEL1", "LEVEL1"),
    ("IN01-TWR-0042-T01-SA-L01-POS1", "POS1"),
    ("IN01-TWR-0042-SH-RACK01", "RACK01"),
    ("IN01-TWR-0042-T01-SA-L01-P01-EXTRA", "EXTRA"),
]


@pytest.mark.unit
def test_tc4_105_fl_mask_validation_20_codes():
    """TC4.105 / FR4.008: Validate 20 codes (10 valid accepted, 10 invalid flagged with segment)."""
    assert len(VALID_CODES) == 10
    assert len(INVALID_CODES) == 10

    # 1. 10 valid codes accepted
    for code, expected_kind, expected_parent, expected_depth in VALID_CODES:
        res = validate_fl_code(code)
        assert res.is_valid, f"Expected {code} to be valid, got error: {res.error_reason}"
        assert res.kind == expected_kind, f"Expected kind {expected_kind} for {code}, got {res.kind}"
        assert res.parent_code == expected_parent, f"Expected parent {expected_parent} for {code}, got {res.parent_code}"
        assert res.depth == expected_depth, f"Expected depth {expected_depth} for {code}, got {res.depth}"
        assert res.error_segment is None

    # 2. 10 invalid codes rejected and flagged with offending segment
    for code, expected_bad_segment in INVALID_CODES:
        res = validate_fl_code(code)
        assert not res.is_valid, f"Expected {code} to be invalid"
        assert res.error_segment == expected_bad_segment, (
            f"Expected error segment '{expected_bad_segment}' for {code}, got '{res.error_segment}'"
        )
        assert res.error_reason is not None
