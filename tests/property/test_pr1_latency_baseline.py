"""Property tests verifying Server Latency Harness and Baseline Report (TC1.157 / TC1.158)."""

import json
import math
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.latency.report import generate_baseline_data  # noqa: E402

DOC_PATH = ROOT / "docs" / "LATENCY_BASELINE.md"
K6_PATH = ROOT / "tools" / "latency" / "k6" / "probe.js"


@pytest.mark.property
def test_latency_probe_k6_script_exists():
    """TC1.157: k6 probe script configuration."""
    assert K6_PATH.exists()
    content = K6_PATH.read_text(encoding="utf-8")
    assert "ten_rps" in content
    assert "fifty_rps" in content
    assert "hundred_rps" in content
    assert "/v1/diagnostics/probe" in content


@pytest.mark.property
def test_latency_baseline_reports_not_measured_without_raw_data(tmp_path):
    """TC1.158 (C0 rewrite): with no raw files, every segment is NOT MEASURED; nothing is invented.

    Replaces a test that asserted PASS on hard-coded sample arrays (review §3.14).
    """
    data = generate_baseline_data(raw_dir=tmp_path / "none")
    assert data["segments"], "segment list must not be empty"
    assert all(r.status == "NOT MEASURED" and r.p50_ms is None and r.p95_ms is None for r in data["segments"])


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(
    samples=st.lists(st.floats(min_value=0.0, max_value=5000.0, allow_nan=False), min_size=1, max_size=300),
)
def test_latency_baseline_percentiles_from_raw(tmp_path_factory, samples):
    """TC1.158: p50/p95 are nearest-rank over committed raw samples; PASS iff p95 <= BRIEF target."""
    raw = tmp_path_factory.mktemp("raw")
    (raw / "run.json").write_text(json.dumps({"source": "test", "segments": {"shutter_to_ack": samples}}))
    seg = next(r for r in generate_baseline_data(raw_dir=raw)["segments"] if r.key == "shutter_to_ack")
    s = sorted(samples)
    n = len(s)
    exp_p50 = round(s[math.ceil(0.5 * n) - 1], 2)
    exp_p95 = round(s[math.ceil(0.95 * n) - 1], 2)
    assert (seg.p50_ms, seg.p95_ms, seg.samples) == (exp_p50, exp_p95, n)
    assert seg.status == ("PASS" if exp_p95 <= 800.0 else "GAP")
