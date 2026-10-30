"""Meta Model API access spike (T1.062 / FR1.055 / TC1.151).

Makes REAL calls to an OpenAI-compatible chat-completions endpoint (Meta's Llama API is one) and
records availability, HTTP status / error codes and measured latency p50/p95. Nothing is simulated:
with no API key the spike records status BLOCKED with reason "no credentials" and no numbers.

Budget (rule A-02): every call is reserved and settled through the server-side budget guard
(field_api.ai.budget: hard caps, AI_CLOUD_ENABLED, prices from config/ai_pricing.yaml); at most
MAX_CALLS per model per run and max_tokens is capped. Secrets are read from the environment by NAME
only and are never printed or written to the results file.

    AI_CLOUD_ENABLED=true uv run python -m tools.spikes.model_api_harness --model <model id listed on llama.developer.meta.com>

Model ids containing "-contributor" are refused (spec T1.062).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from field_api.ai.budget import BudgetGuard, BudgetRefused

MAX_CALLS = 20
MAX_TOKENS = 16
DEFAULT_BASE_URL = "https://api.llama.com/compat/v1"
KEY_ENV = "LLAMA_API_KEY"
RESULTS = Path(__file__).resolve().parent / "model-api" / "results.json"


@dataclass(frozen=True)
class CallResult:
    index: int
    status_code: int | None
    latency_ms: float | None
    error: str | None


@dataclass
class SpikeSummary:
    model_id: str
    status: str  # VERIFIED (≥1 success) | BLOCKED (refused, with evidence) | UNVERIFIED (not run)
    calls: list[CallResult] = field(default_factory=list)
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    reason: str = ""


def validate_model_id(model_id: str) -> None:
    if "-contributor" in model_id.lower():
        raise ValueError(f"model id {model_id!r} contains the forbidden substring '-contributor'")


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in (0, 100]) of measured values."""
    if not values:
        raise ValueError("no values")
    if not 0 < q <= 100:
        raise ValueError("q must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))  # ceil(n*q/100)
    return ordered[int(rank) - 1]


def run_spike(
    model_id: str, prompt: str, *, client: httpx.Client, api_key: str | None, calls: int, guard: BudgetGuard
) -> SpikeSummary:
    validate_model_id(model_id)
    if not 1 <= calls <= MAX_CALLS:
        raise ValueError(f"calls must be 1..{MAX_CALLS}")
    if not api_key:
        return SpikeSummary(model_id, "BLOCKED", reason=f"no credentials: {KEY_ENV} is not set")
    results: list[CallResult] = []
    body = {"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAX_TOKENS}
    est_input = len(prompt) // 3 + 16  # generous token estimate for the reservation
    for i in range(1, calls + 1):
        try:
            res = guard.reserve("llama", model_id, input_tokens=est_input, max_output_tokens=MAX_TOKENS,
                                purpose="spike T1.062")
        except BudgetRefused as e:
            results.append(CallResult(i, None, None, f"budget: {e.code}: {e}"))
            break
        t0 = time.perf_counter()
        try:
            r = client.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError as e:
            guard.fail(res, billed_usd=res.reserved_usd)  # unknown whether billed: count the worst case
            results.append(CallResult(i, None, None, f"{type(e).__name__}: {e}"))
            break
        ms = (time.perf_counter() - t0) * 1000
        usage = r.json().get("usage") if r.is_success else None
        if isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
            guard.settle(res, input_tokens=int(usage["prompt_tokens"]), output_tokens=int(usage["completion_tokens"]))
        else:
            guard.fail(res, billed_usd=res.reserved_usd if r.is_success else Decimal(0))
        err = None if r.is_success else f"HTTP {r.status_code}: {r.text[:200]}"
        results.append(CallResult(i, r.status_code, round(ms, 2), err))
        if r.status_code in (401, 403, 404):
            break  # refused: more calls add no evidence and may cost money
    ok = [c.latency_ms for c in results if c.error is None and c.latency_ms is not None]
    s = SpikeSummary(model_id, "VERIFIED" if ok else "BLOCKED", results)
    if ok:
        s.p50_latency_ms, s.p95_latency_ms = percentile(ok, 50), percentile(ok, 95)
    else:
        s.reason = results[-1].error or "no successful call"
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--prompt", default="Reply with the single word OK.")
    ap.add_argument("--calls", type=int, default=MAX_CALLS)
    ap.add_argument("--base-url", default=os.environ.get("LLAMA_API_BASE_URL", DEFAULT_BASE_URL))
    a = ap.parse_args(argv)
    if os.environ.get("AI_CLOUD_ENABLED", "false").lower() != "true":
        print("refusing to call a paid API: set AI_CLOUD_ENABLED=true in .env.local first")
        return 2
    key = os.environ.get(KEY_ENV)
    with httpx.Client(base_url=a.base_url, timeout=30) as client:
        out: dict[str, Any] = {
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "base_url": a.base_url,
            "models": {
                m: asdict(run_spike(m, a.prompt, client=client, api_key=key, calls=a.calls, guard=BudgetGuard()))
                for m in a.model
            },
        }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for m, s in out["models"].items():
        print(f"{m}: {s['status']} p50={s['p50_latency_ms']} p95={s['p95_latency_ms']} {s['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
