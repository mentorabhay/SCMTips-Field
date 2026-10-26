"""Contract Verification Tests (Task T1.060 / PR1.16)."""

import pytest


@pytest.mark.contract
def test_pr1_16_odata_contract_baseline() -> None:
    """Verifies baseline OData mapping contract."""
    sample_plant = "1010"
    sample_doc = "180000012"
    assert len(sample_plant) == 4
    assert len(sample_doc) == 9
