"""Model Invocation, Fallback Pipeline, and Error Classification (Task T2.059 / FR2.060, TC2.149)."""

import time
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class VerificationCallResult:
    def __init__(
        self,
        verdict: str,  # verified, mismatch, failed
        confidence: float,
        reason: str | None = None,
        model_used: str = "",
        latency_ms: int = 0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self.verdict = verdict
        self.confidence = confidence
        self.reason = reason
        self.model_used = model_used
        self.latency_ms = latency_ms
        self.tokens_used = tokens_used
        self.cost_usd = cost_usd


class VerificationPipeline:
    """Executes model call with primary -> fallback sequence under budget and timeout constraints."""

    def __init__(
        self,
        primary_fn: Callable[..., dict[str, Any]],
        fallback_fn: Callable[..., dict[str, Any]],
        primary_model_name: str = "muse-spark-1.3",
        fallback_model_name: str = "llama-3.2-11b-vision-instruct",
        timeout_seconds: float = 8.0,
    ) -> None:
        self.primary_fn = primary_fn
        self.fallback_fn = fallback_fn
        self.primary_model_name = primary_model_name
        self.fallback_model_name = fallback_model_name
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        payload: dict[str, Any],
        has_budget: bool = True,
        strict_residency: bool = False,
    ) -> VerificationCallResult:
        # 1. Budget check (FR2.058 / PR2.17)
        if not has_budget:
            return VerificationCallResult(
                verdict="failed",
                confidence=0.0,
                reason="unverified_budget",
                model_used="none",
            )

        start_time = time.perf_counter()

        # 2. If strict residency or Muse fails -> try fallback
        if not strict_residency:
            try:
                res = self.primary_fn(payload, timeout=self.timeout_seconds)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                return VerificationCallResult(
                    verdict=res.get("verdict", "verified"),
                    confidence=float(res.get("confidence", 0.95)),
                    reason=res.get("reason"),
                    model_used=self.primary_model_name,
                    latency_ms=elapsed_ms,
                    tokens_used=res.get("tokens_used", 120),
                    cost_usd=res.get("cost_usd", 0.0012),
                )
            except Exception as e:
                logger.warning(
                    "Primary model call failed, attempting fallback",
                    error=str(e),
                    model=self.primary_model_name,
                )

        # 3. Fallback to self-hosted Llama vision (FR2.060 / TC2.149)
        try:
            res_fb = self.fallback_fn(payload, timeout=self.timeout_seconds)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return VerificationCallResult(
                verdict=res_fb.get("verdict", "verified"),
                confidence=float(res_fb.get("confidence", 0.90)),
                reason=res_fb.get("reason"),
                model_used=self.fallback_model_name,
                latency_ms=elapsed_ms,
                tokens_used=res_fb.get("tokens_used", 150),
                cost_usd=0.0,  # Self-hosted inference
            )
        except Exception as e_fb:
            logger.error("Fallback model call also failed", error=str(e_fb))
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return VerificationCallResult(
                verdict="failed",
                confidence=0.0,
                reason="unverified_model_unavailable",
                model_used="none",
                latency_ms=elapsed_ms,
            )
