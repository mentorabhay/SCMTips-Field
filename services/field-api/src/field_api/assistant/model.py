"""Model client for the Field Assistant: OpenAI-compatible chat completions with tools, behind the budget guard.

Primary: Meta Model API (``https://api.meta.ai/v1``, model ``muse-spark-1.3`` (ASSISTANT_MODEL), key from env MODEL_API_KEY).
Fallback: Baseten (OpenAI-compatible; BASETEN_BASE_URL, BASETEN_MODEL_ID, key from env BASETEN_API_KEY), used
only when all three are set and the model has a price in config/ai_pricing.yaml.

Every call: AI_CLOUD_ENABLED must be true, the key must be present, then the budget guard reserves the worst
case (prompt estimate + max_tokens at list price), the call is made with a timeout of at most 6 s (an assistant
turn gives the model ASSISTANT_MODEL_DEADLINE_S, default 3.5 s, in all; the brief router 4 s), and the
reservation is settled with the provider's own usage counts (prompt, cached prompt, completion tokens). A call
whose outcome is unknown (transport error, timeout) is closed at the reserved worst case; an HTTP error answer
is closed at 0; a success without usage is closed at the reserved worst case.

Model ids: '-contributor' models are refused (spec T1.062), and so is any id containing "image": Muse Image is
prohibited in India (owner amendment A-04); the budget guard refuses such ids too, whatever the price file says.

Keys are read from the environment by NAME at call time and are never logged, stored or put in an error.
UNVERIFIED beyond access (docs/META_FIELD.md rows 19-20): access from India is verified, tool calls and images are not; CI
exercises this client against a test double of the HTTP API that lives in test code only.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
import structlog

from field_api.ai.budget import PROHIBITED_MODEL_WORDS, BudgetGuard, BudgetRefused

logger = structlog.get_logger(__name__)

META_BASE_URL = "https://api.meta.ai/v1"
# Owner choice, 31 Oct 2026 (amendment A-04): muse-spark-1.3, verified reachable from India (META_FIELD row 19).
META_MODEL = "muse-spark-1.3"
META_KEY_ENV = "MODEL_API_KEY"
BASETEN_KEY_ENV = "BASETEN_API_KEY"
CALL_TIMEOUT_S = 6.0
# Muse Spark reasons before it answers and the reasoning counts as output: on 31 Oct 2026 the owner's call from
# India (HTTP 200, muse-spark-1.2 and 1.3) spent 18 of 20 tokens on reasoning and returned no text. 1024 leaves
# room for a two-sentence answer; ASSISTANT_MAX_OUTPUT_TOKENS (64..4096) overrides it.
MAX_OUTPUT_TOKENS = 1024
MAX_OUTPUT_ENV = "ASSISTANT_MAX_OUTPUT_TOKENS"


def max_output_tokens() -> int:
    """The output cap per call: ASSISTANT_MAX_OUTPUT_TOKENS within 64..4096, else MAX_OUTPUT_TOKENS."""
    raw = os.getenv(MAX_OUTPUT_ENV, "").strip()
    if not raw.isdigit():
        return MAX_OUTPUT_TOKENS
    return max(64, min(4096, int(raw)))


# The whole model part of one assistant turn (owner's field test, 31 Oct 2026: 6 s timeouts made Start Work wait
# 6-7 s). ASSISTANT_MODEL_DEADLINE_S overrides it within 1.5..6 s.
MODEL_DEADLINE_S = 3.5
MODEL_DEADLINE_ENV = "ASSISTANT_MODEL_DEADLINE_S"


def model_deadline_s() -> float:
    """Seconds the model may take in one assistant turn: ASSISTANT_MODEL_DEADLINE_S within 1.5..6, else 3.5."""
    raw = os.getenv(MODEL_DEADLINE_ENV, "").strip()
    try:
        v = float(raw)
    except ValueError:
        return MODEL_DEADLINE_S
    if not math.isfinite(v):
        return MODEL_DEADLINE_S
    return max(1.5, min(CALL_TIMEOUT_S, v))


IMAGE_TOKEN_ESTIMATE = 1600  # reservation per image; settled by the provider's real count


class ModelError(Exception):
    """A model call did not produce an answer. ``code`` is safe to record (never contains a key)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def model_prohibited(model: str) -> bool:
    """True for a model id that must never be called (any id containing "image": Muse Image, A-04)."""
    low = model.lower()
    return any(w in low for w in PROHIBITED_MODEL_WORDS)


def validate_model_id(model: str) -> str:
    if "-contributor" in model.lower():
        raise ValueError(f"model id {model!r} is refused: '-contributor' models are not allowed (spec T1.062)")
    if model_prohibited(model):
        raise ValueError(f"model id {model!r} is refused: image models (Muse Image) are prohibited in India (A-04)")
    if not model.strip():
        raise ValueError("model id is empty")
    return model


@dataclass(frozen=True)
class ProviderConfig:
    provider: str  # budget-guard provider: 'meta' | 'baseten'
    base_url: str
    model: str
    key_env: str

    def __post_init__(self) -> None:
        validate_model_id(self.model)


@dataclass
class ChatResult:
    message: dict[str, Any]
    provider: str
    model: str
    cost_usd: Decimal
    latency_ms: int
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


@dataclass
class CallLog:
    """What one turn spent, including calls that failed (their billed worst case counts)."""

    cost_usd: Decimal = Decimal(0)
    calls: list[dict[str, Any]] = field(default_factory=list)


def meta_config() -> ProviderConfig:
    return ProviderConfig("meta", os.getenv("META_MODEL_API_BASE_URL", META_BASE_URL),
                          os.getenv("ASSISTANT_MODEL", META_MODEL), META_KEY_ENV)


def baseten_config() -> ProviderConfig | None:
    base, model = os.getenv("BASETEN_BASE_URL", "").strip(), os.getenv("BASETEN_MODEL_ID", "").strip()
    if not base or not model:
        return None
    return ProviderConfig("baseten", base, model, BASETEN_KEY_ENV)


def estimate_tokens(messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] | None) -> int:
    """Generous prompt-token estimate for the reservation (about 3 characters per token, images flat)."""
    images = 0
    text_chars = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    images += 1
                else:
                    text_chars += len(json.dumps(part))
        else:
            text_chars += len(json.dumps(content)) + len(json.dumps(m.get("tool_calls") or ""))
    text_chars += len(json.dumps(list(tools or [])))
    return text_chars // 3 + 32 + images * IMAGE_TOKEN_ESTIMATE


def _usage(body: dict[str, Any]) -> tuple[int, int, int] | None:
    u = body.get("usage")
    if not isinstance(u, dict):
        return None
    try:
        prompt, completion = int(u["prompt_tokens"]), int(u["completion_tokens"])
    except (KeyError, TypeError, ValueError):
        return None
    details = u.get("prompt_tokens_details")
    cached = 0
    if isinstance(details, dict) and details.get("cached_tokens") is not None:
        try:
            cached = int(details["cached_tokens"])
        except (TypeError, ValueError):
            cached = 0
    if prompt < 0 or completion < 0:
        return None
    return prompt, max(0, min(cached, prompt)), completion


class ChatModel:
    """One OpenAI-compatible provider. ``transport`` is for tests (an httpx transport double); production uses
    the default network transport."""

    def __init__(self, cfg: ProviderConfig, guard: BudgetGuard | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self.guard = guard or BudgetGuard()
        self._transport = transport

    @property
    def provider(self) -> str:
        return self.cfg.provider

    def has_key(self) -> bool:
        return bool(os.environ.get(self.cfg.key_env, "").strip())

    def chat(self, messages: Sequence[dict[str, Any]], *, tools: Sequence[dict[str, Any]] | None = None,
             timeout_s: float = CALL_TIMEOUT_S, max_tokens: int | None = None, purpose: str = "assistant",
             tenant_id: str | None = None, request_id: str | None = None, log: CallLog | None = None,
             response_format: dict[str, Any] | None = None, images: int = 0,
             timeout_cap_s: float = CALL_TIMEOUT_S) -> ChatResult:
        """One call. ``response_format`` (M5 vision look: a JSON schema answer) and ``images`` (the number of input
        images, so the budget guard applies its image-input rules) are sent only when given; without them the
        request and the reservation are exactly the M3/M4 ones. ``timeout_cap_s`` lets the vision look allow image
        calls longer than the assistant's 6 s cap (owner's Gate 0 from India, 1 Nov 2026: SAM 3.1 took about 5 s and a
        Muse image read more than 7.7 s); the assistant and the brief router keep the default."""
        if os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() != "true":
            raise ModelError("AI_CLOUD_DISABLED")
        key = os.environ.get(self.cfg.key_env, "").strip()
        if not key:
            raise ModelError("AI_NO_KEY", f"{self.cfg.key_env} is not set")
        timeout = min(max(timeout_s, 0.1), timeout_cap_s)
        if max_tokens is None:
            max_tokens = max_output_tokens()
        body: dict[str, Any] = {"model": self.cfg.model, "messages": list(messages), "max_tokens": max_tokens,
                                "temperature": 0.2}
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        if response_format is not None:
            body["response_format"] = response_format
        try:
            if images > 0:  # the guard reserves the images itself (its tokens_per_image), not the flat estimate
                est = max(0, estimate_tokens(messages, tools) - images * IMAGE_TOKEN_ESTIMATE)
                res = self.guard.reserve(self.cfg.provider, self.cfg.model, input_tokens=est,
                                         max_output_tokens=max_tokens, purpose=purpose, tenant_id=tenant_id,
                                         request_id=request_id, images=images)
            else:
                res = self.guard.reserve(self.cfg.provider, self.cfg.model,
                                         input_tokens=estimate_tokens(messages, tools), max_output_tokens=max_tokens,
                                         purpose=purpose, tenant_id=tenant_id, request_id=request_id)
        except BudgetRefused as e:
            raise ModelError(e.code, str(e)) from None
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=self.cfg.base_url, timeout=timeout, transport=self._transport) as client:
                r = client.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.TimeoutException:
            self._close_failed(res.reserved_usd, res, log, "AI_TIMEOUT")
            raise ModelError("AI_TIMEOUT") from None
        except httpx.HTTPError as e:
            self._close_failed(res.reserved_usd, res, log, "AI_TRANSPORT")
            raise ModelError("AI_TRANSPORT", type(e).__name__) from None
        latency = int((time.perf_counter() - t0) * 1000)
        if not r.is_success:
            self._close_failed(Decimal(0), res, log, f"AI_HTTP_{r.status_code}")
            raise ModelError(f"AI_HTTP_{r.status_code}")
        try:
            data = r.json()
        except ValueError:
            data = None
        usage = _usage(data) if isinstance(data, dict) else None
        if usage is None:
            self._close_failed(res.reserved_usd, res, log, "AI_NO_USAGE")
            raise ModelError("AI_BAD_RESPONSE", "no usage in the answer")
        prompt, cached, completion = usage
        cost = self.guard.settle(res, input_tokens=prompt, output_tokens=completion, cached_input_tokens=cached)
        if log is not None:
            log.cost_usd += cost
            log.calls.append({"provider": self.cfg.provider, "model": self.cfg.model, "latency_ms": latency,
                              "prompt_tokens": prompt, "cached_tokens": cached, "completion_tokens": completion,
                              "cost_usd": str(cost)})
        assert isinstance(data, dict)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError("AI_BAD_RESPONSE", "no choices[0].message") from None
        if not isinstance(message, dict):
            raise ModelError("AI_BAD_RESPONSE", "message is not an object")
        finish = data["choices"][0].get("finish_reason") if isinstance(data["choices"][0], dict) else None
        if finish == "length" and not message.get("content") and not message.get("tool_calls"):
            # Billed (settled above), but nothing to say: the cap was spent on reasoning. The turn falls back.
            logger.warning("assistant_model_truncated", provider=self.cfg.provider, model=self.cfg.model,
                           completion_tokens=completion, max_tokens=max_tokens)
            raise ModelError("AI_TRUNCATED", f"no answer within {max_tokens} output tokens")
        return ChatResult(message, self.cfg.provider, self.cfg.model, cost, latency, prompt, cached, completion)

    def _close_failed(self, billed: Decimal, res: Any, log: CallLog | None, code: str) -> None:
        self.guard.fail(res, billed_usd=billed)
        logger.warning("assistant_model_call_failed", provider=self.cfg.provider, model=self.cfg.model, code=code)
        if log is not None:
            log.cost_usd += billed
            log.calls.append({"provider": self.cfg.provider, "model": self.cfg.model, "error": code,
                              "cost_usd": str(billed)})


class ModelRouter:
    """Primary then fallback. A provider that refuses or fails before answering hands over to the next one."""

    def __init__(self, models: Sequence[ChatModel]) -> None:
        self.models = list(models)

    def chat(self, messages: Sequence[dict[str, Any]], *, tools: Sequence[dict[str, Any]] | None, deadline: float,
             tenant_id: str | None, request_id: str | None, log: CallLog, errors: list[str],
             purpose: str = "assistant", max_tokens: int | None = None) -> ChatResult:
        for m in self.models:
            remaining = deadline - time.monotonic()
            if remaining < 0.3:
                errors.append("AI_DEADLINE")
                break
            try:
                return m.chat(messages, tools=tools, timeout_s=remaining, max_tokens=max_tokens, purpose=purpose,
                              tenant_id=tenant_id, request_id=request_id, log=log)
            except ModelError as e:
                errors.append(f"{m.provider}:{e.code}")
        raise ModelError("AI_UNAVAILABLE", ", ".join(errors) or "no provider configured")


def build_router(guard: BudgetGuard | None = None, transport: httpx.BaseTransport | None = None) -> ModelRouter:
    """Meta first; Baseten only when its URL and model id are configured."""
    g = guard or BudgetGuard()
    models: list[ChatModel] = []
    for make in (meta_config, baseten_config):
        try:
            cfg = make()
        except ValueError as e:  # a refused model id: that provider is skipped, the turn falls back to rules
            logger.warning("assistant_model_refused", error=str(e))
            continue
        if cfg is not None:
            models.append(ChatModel(cfg, g, transport))
    return ModelRouter(models)


def get_router() -> ModelRouter:
    """FastAPI dependency (tests override it with a router over the recorded-response double)."""
    return build_router()
