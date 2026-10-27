"""Property tests verifying Server Latency Harness and Baseline Report (TC1.157 / TC1.158)."""

from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.latency.report import generate_baseline_data

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
def test_latency_baseline_meets_brief_targets():
    """TC1.158: Latency baseline document and BRIEF target bounds."""
    assert DOC_PATH.exists()
    content = DOC_PATH.read_text(encoding="utf-8")

    # Required segments
    assert "Glasses -> Phone" in content
    assert "Barcode Detection" in content
    assert "field-api Processing" in content
    assert "Shutter-to-Ack" in content

    # Benchmark numbers
    assert "10 RPS" in content
    assert "50 RPS" in content
    assert "100 RPS" in content

    # Assert measured end to end adheres to 800ms limit
    data = generate_baseline_data()
    total_segment = [s for s in data["segments"] if "Shutter-to-Ack" in s.segment_name][0]
    assert total_segment.measured_p50_ms <= 600.0
    assert total_segment.measured_p95_ms <= 800.0
    assert total_segment.status == "PASS"
