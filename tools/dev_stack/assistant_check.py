"""`stack assistant-check`: ONE real Field Assistant model call through the budget guard (M3 contract §4).

    uv run python -m tools.dev_stack.assistant_check        # standalone; the dev stack's subcommand calls run()

Prints exactly one line:
    assistant-check: OK model=<id> latency_ms=<n> cost_usd=<x>
    assistant-check: BLOCKED <reason>
It never prints the key, the prompt or the answer. Settings come from the environment, filled from the git-ignored
.env.local for names that are not already set (values are never echoed): AI_CLOUD_ENABLED, MODEL_API_KEY,
AI_BUDGET_META_USD, AI_DAILY_CAP_USD, FIELD_DATABASE_URL (the guard's ledger), optionally the Baseten fallback.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
from field_api.ai.budget import BudgetGuard
from field_api.assistant.model import CallLog, ModelError, ModelRouter, build_router

ROOT = Path(__file__).resolve().parents[2]
ENV_LOCAL = ROOT / ".env.local"
PROBE = [{"role": "user", "content": "Reply with the single word OK."}]


def load_env_local(path: Path = ENV_LOCAL) -> list[str]:
    """Set names from .env.local that the environment does not have yet; returns the names set (never values)."""
    if not path.exists():
        return []
    set_names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")
            set_names.append(name)
    return set_names


def check(router: ModelRouter | None = None) -> str:
    """The one-line result. ``router`` is for tests (a router over a test double of the HTTP API)."""
    if os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() != "true":
        return "assistant-check: BLOCKED AI_CLOUD_DISABLED (set AI_CLOUD_ENABLED=true in .env.local)"
    try:
        r = router or build_router(BudgetGuard())
    except Exception as e:  # e.g. a refused model id
        return f"assistant-check: BLOCKED {type(e).__name__}"
    if not r.models:
        return "assistant-check: BLOCKED no model configured"
    log = CallLog()
    errors: list[str] = []
    t0 = time.perf_counter()
    try:
        res = r.chat(PROBE, tools=None, deadline=time.monotonic() + 6.0, tenant_id=None,
                     request_id="assistant-check", log=log, errors=errors)
    except ModelError:
        return "assistant-check: BLOCKED " + (", ".join(errors) or "no answer")
    except (httpx.HTTPError, OSError) as e:
        return f"assistant-check: BLOCKED {type(e).__name__}"
    latency = int((time.perf_counter() - t0) * 1000)
    return f"assistant-check: OK model={res.model} latency_ms={latency} cost_usd={res.cost_usd:.6f}"


def run(argv: list[str] | None = None) -> int:
    """Entry point for the dev stack's `assistant-check` subcommand: 0 when OK, 1 when BLOCKED."""
    load_env_local()
    line = check()
    print(line)
    return 0 if " OK " in line else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
