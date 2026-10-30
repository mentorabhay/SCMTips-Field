"""Unit and property tests for WS2.9 Quality, Latency, Privacy, and Release (Tasks T2.065 - T2.073).

Covers:
- T2.065: End-to-end timing dashboard specification (FR2.063)
- T2.066: Latency campaign report and 5G p95 threshold <= 400ms (TC2.152 / FR2.063)
- T2.067: k6 load test configuration and threshold gates (TC2.153 / FR2.063)
- T2.068: Chaos campaign reconciliation proof (FR2.039, FR2.040)
- T2.069: Maestro E2E capture & post flow specification (FR2.052, FR2.055)
- T2.070: Privacy scan verification (TC2.131, TC2.161 / FR2.022, FR2.035)
- T2.071: Walking-quiet policy and data minimisation rules (TC2.110, TC2.156 / FR2.065, FR2.066)
- T2.072: STRIDE threat model and security review (FR2.053, FR2.059)
- T2.073: Release report completeness across all 73 tasks (FR2.001)
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.privacy_scan import (  # noqa: E402
    scan_audio_persistence,
    scan_log_redaction,
)


@pytest.mark.unit
def test_t2_065_latency_dashboard_json():
    """T2.065: Grafana latency dashboard exists with segment histograms and p95 alert."""
    dash_path = ROOT / "ops" / "dashboards" / "f1-capture.json"
    assert dash_path.exists()

    data = json.loads(dash_path.read_text(encoding="utf-8"))
    assert data["uid"] == "f1-capture-latency"
    assert len(data["panels"]) >= 4

    # Check 400ms threshold presence
    text = dash_path.read_text(encoding="utf-8")
    assert "400" in text
    assert "field_lens_tick_ms" in text


# test_t2_066_latency_campaign_report removed (C5): asserted a hand-written p95 "345 ms" in docs/perf/F1-latency.md; no measurement exists (TC2.152 unproven).

@pytest.mark.unit
def test_t2_067_k6_load_test_script():
    """T2.067 / TC2.153: k6 script specifies 50 rps for 10 min with p95 < 120ms threshold."""
    k6_path = ROOT / "tests" / "load" / "k6_capture_ingest.js"
    assert k6_path.exists()

    content = k6_path.read_text(encoding="utf-8")
    assert "rate: 50" in content
    assert 'duration: "10m"' in content
    assert 'http_req_duration: ["p(95)<120"]' in content
    assert "40 * 1024" in content  # 40 KB crop


# test_t2_068_chaos_campaign_report removed (C5): asserted hand-written "0 duplicates / 0 lost" text in docs/perf/F1-chaos.md; no chaos run exists.

@pytest.mark.unit
def test_t2_069_maestro_e2e_flow():
    """T2.069: Maestro YAML flow covers look, count 12, post, confirm, and erp.posted tick."""
    maestro_path = ROOT / "apps" / "field-android" / "maestro" / "capture_post.yaml"
    assert maestro_path.exists()

    docs = list(yaml.safe_load_all(maestro_path.read_text(encoding="utf-8")))
    content = docs[0]
    assert content["appId"] == "com.scmtips.field.app"

    text = maestro_path.read_text(encoding="utf-8")
    assert "count twelve" in text
    assert "post" in text
    assert "confirm" in text
    assert "POSTED" in text


@pytest.mark.unit
def test_t2_070_privacy_scan_passes():
    """T2.070 / TC2.131, TC2.161: Automated privacy scanner returns zero findings."""
    audio_findings = scan_audio_persistence()
    log_findings = scan_log_redaction()

    assert len(audio_findings) == 0, f"Audio files found: {audio_findings}"
    assert len(log_findings) == 0, f"Unredacted log leaks found: {log_findings}"


# T2.071 quiet-mode policy: moved to core-capture/src/test/kotlin/.../safety/QuietModePolicyTest.kt (C5).


@pytest.mark.unit
def test_t2_072_stride_threat_model():
    """T2.072: Security review covers STRIDE, contributor model ban, and dependency posture."""
    threat_path = ROOT / "docs" / "security" / "F1-threat-model.md"
    assert threat_path.exists()

    text = threat_path.read_text(encoding="utf-8")
    assert "STRIDE Assessment Matrix" in text
    assert "Spoofing" in text
    assert "Tampering" in text
    assert "Repudiation" in text
    assert "Information Disclosure" in text
    assert "Denial of Service" in text
    assert "Elevation of Privilege" in text
    assert "0 High, 0 Critical findings open" in text


# test_t2_073_release_report removed (C5): asserted a hand-written "ALL 73 TASKS VERIFIED" claim (rule 2.3: reports come from the ledger).
