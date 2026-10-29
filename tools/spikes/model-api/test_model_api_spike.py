"""Unit tests for Meta Model API Spike Harness (Task T1.062 / TC1.151)."""

import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parent
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from harness import ModelApiHarness, run_and_save_all_spikes  # noqa: E402


@pytest.mark.unit
def test_harness_rejects_contributor_models() -> None:
    harness = ModelApiHarness()
    with pytest.raises(ValueError, match="forbidden substring '-contributor'"):
        harness.validate_model_id("muse-spark-1.3-contributor")

    with pytest.raises(ValueError, match="forbidden substring '-contributor'"):
        harness.validate_model_id("MUSE-CONTRIBUTOR-V1")


@pytest.mark.unit
def test_harness_allows_non_contributor_models() -> None:
    harness = ModelApiHarness()
    # Should not raise
    harness.validate_model_id("muse-spark-1.3")
    harness.validate_model_id("muse-wonder")


@pytest.mark.unit
def test_harness_executes_spike_and_computes_percentiles(tmp_path: Path) -> None:
    harness = ModelApiHarness()
    summary = harness.run_spike("muse-spark-1.3", {"prompt": "sample"}, num_calls=20)

    assert summary.total_calls == 20
    assert summary.status == "BLOCKED"
    assert summary.p50_latency_ms > 0
    assert summary.p95_latency_ms >= summary.p50_latency_ms

    out_file = tmp_path / "spike_results.json"
    data = run_and_save_all_spikes(out_file)
    assert out_file.exists()
    assert "muse-spark-1.3" in data["models"]
    assert "muse-wonder" in data["models"]
    assert "D1.04" in data["decision"]
