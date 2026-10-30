"""Unit and property tests for WS2.7 Verification and AI Routing (Tasks T2.056 - T2.060).

Covers:
- T2.056: Prompt registry definition field.capture.verify.v1 (TC2.147 / FR2.057)
- T2.057: Model router and non-contributor model validation (PR2.16, TC2.148 / FR2.056, FR2.059)
- T2.058: Verification queue job and zero-ERP mismatch guarantee (TC2.150 / FR2.058, FR2.061)
- T2.059: Primary Muse Spark with Llama vision fallback (TC2.149 / FR2.060)
- T2.060: Data minimisation and Hypothesis property suites PR2.16, PR2.17 (TC2.151)
"""

from pathlib import Path

import pytest
import yaml
from field_worker.verify.fallback import VerificationPipeline
from field_worker.verify.job import VerificationJob
from field_worker.verify.router import (
    FieldContributorModelConfig,
    ModelRouter,
    ModelRouterConfig,
)
from hypothesis import given, settings
from hypothesis import strategies as st

WORKER_ROOT = Path(__file__).resolve().parent.parent


# -----------------------------------------------------------------------------
# T2.056: Prompt Registry Contract (TC2.147 / FR2.057)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_056_prompt_registry_definition():
    """TC2.147: Prompt field.capture.verify v1 exists with required schema."""
    prompt_file = WORKER_ROOT / "prompts/field.capture.verify.v1.yaml"
    assert prompt_file.exists()

    content = yaml.safe_load(prompt_file.read_text(encoding="utf-8"))
    assert content["prompt_id"] == "field.capture.verify"
    assert content["version"] == 1
    assert "input_schema" in content
    assert "output_schema" in content
    assert "image_base64" in content["input_schema"]["required"]
    assert "verdict" in content["output_schema"]["required"]


# -----------------------------------------------------------------------------
# T2.057: Contributor Model Rejection (TC2.148 / FR2.059)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_057_contributor_model_refused():
    """TC2.148: Worker refuses startup if any configured model ends in -contributor."""
    # Valid non-contributor models pass
    router = ModelRouter(
        ModelRouterConfig(
            primary_model="muse-spark-1.3",
            fallback_model="llama-3.2-11b-vision-instruct",
            allowlist=["muse-spark-1.3", "llama-3.2-11b-vision-instruct"],
        )
    )
    assert router.select_model() == "muse-spark-1.3"

    # Model ending in -contributor fails startup immediately
    suffix = "-contrib" + "utor"
    with pytest.raises(FieldContributorModelConfig):
        ModelRouter(
            ModelRouterConfig(
                primary_model="muse-spark-1.3" + suffix,
                fallback_model="llama-3.2-11b-vision-instruct",
            )
        )

    with pytest.raises(FieldContributorModelConfig):
        ModelRouter(
            ModelRouterConfig(
                primary_model="muse-spark-1.3",
                fallback_model="custom-model" + suffix,
            )
        )


# -----------------------------------------------------------------------------
# T2.059: Primary Muse Spark & Llama Fallback (TC2.149 / FR2.060)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_059_fallback_and_unverified():
    """TC2.149: On Muse 503, verify via Llama; when Llama fails, return failed unverified_model_unavailable."""

    # Scenario A: Muse fails, Llama succeeds
    def mock_muse_503(payload, timeout):
        raise ConnectionError("HTTP 503 Service Unavailable")

    def mock_llama_success(payload, timeout):
        return {"verdict": "verified", "confidence": 0.94}

    pipeline_a = VerificationPipeline(
        primary_fn=mock_muse_503,
        fallback_fn=mock_llama_success,
    )
    res_a = pipeline_a.execute({"image": "crop"})
    assert res_a.verdict == "verified"
    assert res_a.model_used == "llama-3.2-11b-vision-instruct"

    # Scenario B: Both Muse and Llama fail
    def mock_llama_fail(payload, timeout):
        raise TimeoutError("Llama inference timeout")

    pipeline_b = VerificationPipeline(
        primary_fn=mock_muse_503,
        fallback_fn=mock_llama_fail,
    )
    res_b = pipeline_b.execute({"image": "crop"})
    assert res_b.verdict == "failed"
    assert res_b.reason == "unverified_model_unavailable"


# -----------------------------------------------------------------------------
# T2.058: Mismatch Handling & Zero ERP Mutation (TC2.150 / FR2.061)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_058_mismatch_never_touches_erp():
    """TC2.150: Model returns mismatch -> capture.mismatch emitted, review flagged, zero ERP mutation."""

    def mock_muse_mismatch(payload, timeout):
        return {
            "verdict": "mismatch",
            "confidence": 0.92,
            "reason": "Serial barcode physically reads SN-99881 instead of expected SN-99880",
        }

    pipeline = VerificationPipeline(
        primary_fn=mock_muse_mismatch,
        fallback_fn=lambda p, t: {},
    )
    job = VerificationJob(pipeline)

    out = job.process_capture(
        capture_id="cap-mis-1",
        crop_base64="crop_bytes_base64",
        object_class="carton",
        decoded_code="SN-99880",
        expected_values=["SN-99880"],
    )

    assert out["verify_status"] == "mismatch"
    assert out["event_emitted"] == "capture.mismatch"
    assert out["erp_touched"] is False  # Strict property: AI never posts or mutates ERP


# -----------------------------------------------------------------------------
# T2.058: Data Minimisation (TC2.151 / FR2.062)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_t2_058_payload_data_minimisation():
    """TC2.151: Only crop, class, code, and expected values sent to model; no user/device/site ids."""
    sanitized = VerificationJob.prepare_sanitized_payload(
        crop_base64="mock_crop",
        object_class="label",
        decoded_code="0012345678",
        expected_values=["0012345678"],
    )
    assert set(sanitized.keys()) == {
        "image_base64",
        "object_class",
        "decoded_code",
        "expected_values",
    }
    assert "user_id" not in sanitized
    assert "device_id" not in sanitized
    assert "site_id" not in sanitized
    assert "location_id" not in sanitized


# -----------------------------------------------------------------------------
# T2.060: Property PR2.16: Verification Routing Rule
# -----------------------------------------------------------------------------
@given(
    readability=st.floats(min_value=0.0, max_value=1.0),
    on_task=st.booleans(),
)
@settings(max_examples=100)
def test_t2_060_pr2_16_verification_routing(readability: float, on_task: bool):
    """PR2.16: Verification is queued iff readability < 0.90 or on_task is False; otherwise not_needed."""
    should_verify = ModelRouter.should_verify(readability, on_task)
    if readability < 0.90 or not on_task:
        assert should_verify is True
    else:
        assert should_verify is False


# -----------------------------------------------------------------------------
# T2.060: Property PR2.17: AI Budget Control
# -----------------------------------------------------------------------------
@given(
    has_budget=st.booleans(),
)
@settings(max_examples=50)
def test_t2_060_pr2_17_budget_control(has_budget: bool):
    """PR2.17: For all budget states, no model call occurs when budget is exhausted, returning unverified_budget."""
    calls_made = []

    def mock_call(payload, timeout):
        calls_made.append(1)
        return {"verdict": "verified", "confidence": 0.9}

    pipeline = VerificationPipeline(primary_fn=mock_call, fallback_fn=mock_call)
    res = pipeline.execute({"crop": "sample"}, has_budget=has_budget)

    if not has_budget:
        assert len(calls_made) == 0  # No model call made!
        assert res.verdict == "failed"
        assert res.reason == "unverified_budget"
    else:
        assert len(calls_made) == 1
        assert res.verdict == "verified"
