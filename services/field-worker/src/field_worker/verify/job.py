"""Verification Queue Worker Job and Data Minimisation Enforcer (Tasks T2.058, T2.062 / FR2.058, FR2.061, FR2.062, TC2.150, TC2.151)."""

from datetime import UTC, datetime
from typing import Any

import structlog
from field_worker.verify.fallback import VerificationCallResult, VerificationPipeline

logger = structlog.get_logger(__name__)


class VerificationJob:
    """Processes verification jobs from SKIP LOCKED queue.

    Enforces:
    1. Data minimisation: only crop, class, code, and expected values (FR2.062 / TC2.151).
    2. Zero ERP mutation on mismatch: emits capture.mismatch, flags review (FR2.061 / TC2.150).
    3. Records verification_attempt outcome.
    """

    def __init__(self, pipeline: VerificationPipeline) -> None:
        self.pipeline = pipeline

    @staticmethod
    def prepare_sanitized_payload(
        crop_base64: str,
        object_class: str,
        decoded_code: str,
        expected_values: list[str],
        unauthorized_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """TC2.151 / FR2.062: Sanitizes payload to guarantee no user, device, or location identifiers are transmitted."""
        # Strips out any user_id, device_id, location_id, site_id, lat, lon
        return {
            "image_base64": crop_base64,
            "object_class": object_class,
            "decoded_code": decoded_code,
            "expected_values": expected_values,
        }

    def process_capture(
        self,
        capture_id: str,
        crop_base64: str,
        object_class: str,
        decoded_code: str,
        expected_values: list[str],
        has_budget: bool = True,
        strict_residency: bool = False,
    ) -> dict[str, Any]:
        # Prepare strictly minimized payload
        sanitized_payload = self.prepare_sanitized_payload(
            crop_base64=crop_base64,
            object_class=object_class,
            decoded_code=decoded_code,
            expected_values=expected_values,
        )

        result: VerificationCallResult = self.pipeline.execute(
            payload=sanitized_payload,
            has_budget=has_budget,
            strict_residency=strict_residency,
        )

        now_iso = datetime.now(UTC).isoformat()
        attempt_record = {
            "capture_id": capture_id,
            "model_name": result.model_used,
            "prompt_id": "field.capture.verify",
            "prompt_version": "v1",
            "verdict": result.verdict,
            "confidence": result.confidence,
            "reason": result.reason,
            "latency_ms": result.latency_ms,
            "tokens_used": result.tokens_used,
            "cost_usd": result.cost_usd,
            "created_at": now_iso,
        }

        # Event emission logic per FR2.061
        event_emitted = None
        if result.verdict == "verified":
            event_emitted = "capture.verified"
        elif result.verdict == "mismatch":
            # TC2.150: Flag review in console, NEVER touch ERP
            event_emitted = "capture.mismatch"
        elif result.verdict == "failed":
            event_emitted = "capture.failed"

        return {
            "capture_id": capture_id,
            "verify_status": result.verdict,
            "verify_reason": result.reason,
            "attempt": attempt_record,
            "event_emitted": event_emitted,
            "erp_touched": False,  # Strict guarantee: Nothing AI posts to the ERP (FR2.061)
        }
