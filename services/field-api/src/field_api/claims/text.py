"""The claim text (M5 contract section 3): Muse drafts it from the template, the local number check guards it.

Order, each step ending in the template on failure (``source: "template"`` with the reasons):
1. one Muse call (purpose ``claim``) through the model router and the budget guard, within CLAIM_MODEL_DEADLINE_S
   (default 4 s, 1.5..6): AI off, no key, refused or prohibited model, over budget, error, cut-off or empty answer
   -> ``model:...``;
2. the local number check of the M4 briefs (``field_api.briefs.numbers``) against the template, which holds every
   number of the lines and nothing else: a draft that changes, adds or drops a number -> ``local:...``.
The model sees the template text only (no ids, no names, no photo). Nothing here posts, sends or stores.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any

from field_api.assistant.model import CallLog, ModelError, ModelRouter
from field_api.briefs import numbers
from field_api.claims.lines import ClaimLine

CLAIM_DEADLINE_S = 4.0
CLAIM_DEADLINE_ENV = "CLAIM_MODEL_DEADLINE_S"
CLAIM_MAX_TOKENS = 1024  # Muse Spark reasons first and the reasoning counts as output (assistant/model.py)
MAX_WORDS = 120
CLAIM_PROMPT = (
    "You write the body of a short, polite claim message from a goods-receiving team to a supplier about one "
    "delivery. Use only the facts given. Keep every number exactly as written, in digits, and say each of them. Do "
    "not add any number, date, price, name, brand, company or product name, and do not promise or demand anything "
    "that is not in the facts. One or two plain sentences, no greeting, no signature, no lists, no markdown, no "
    "quotes. Reply with the message text and nothing else."
)


def claim_deadline_s() -> float:
    raw = os.getenv(CLAIM_DEADLINE_ENV, "").strip()
    try:
        v = float(raw)
    except ValueError:
        return CLAIM_DEADLINE_S
    if not math.isfinite(v):
        return CLAIM_DEADLINE_S
    return max(1.5, min(6.0, v))


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _pieces(p: int) -> str:
    return f" ({p} {_plural(p, 'piece', 'pieces')})" if p else ""


def line_phrase(line: ClaimLine, *, ppu: int | None, window: int | None) -> str:
    u, p = line.units, line.pieces
    units = _plural(u, "unit", "units")
    if line.reason == "damaged":
        return f"{u} damaged {units}{_pieces(p)}"
    if line.reason == "expired":
        return f"{u} expired {units}{_pieces(p)}"
    if line.reason == "near_expiry":
        within = f" within {window} days" if window else " soon"
        return f"{u} {units} expiring{within}{_pieces(p)}"
    if line.reason == "short":
        return f"{u} {units} short{_pieces(p)}"
    packs = _plural(u, "pack holds", "packs hold")
    expected = f" than {ppu}" if ppu else ""
    return f"{u} {packs} fewer pieces{expected}: {p} {_plural(p, 'piece', 'pieces')} short"


def template_text(lines: list[ClaimLine], *, ppu: int | None = None, window: int | None = None) -> str:
    """The claim text without a model: every number of the lines, and nothing else."""
    phrases = [line_phrase(ln, ppu=ppu, window=window) for ln in lines]
    return "We claim for this delivery: " + "; ".join(phrases) + ". The photo and the posting record are attached."


def summary(lines: list[ClaimLine], *, ppu: int | None = None, window: int | None = None) -> str:
    """The lines as one spoken phrase ("2 damaged units (24 pieces); 1 unit short")."""
    return "; ".join(line_phrase(ln, ppu=ppu, window=window) for ln in lines)


@dataclass
class Draft:
    text: str
    source: str  # 'model' | 'template'
    reasons: list[str]
    model_calls: list[dict[str, Any]] = field(default_factory=list)


def _clean(content: Any) -> str:
    text = content if isinstance(content, str) else ""
    text = text.strip().strip("`").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return " ".join(text.split())


def _calls(log: CallLog, errors: list[str]) -> list[dict[str, Any]]:
    """The model calls of this draft in the evidence shape (model, purpose, latency, cost, outcome)."""
    out: list[dict[str, Any]] = []
    for c in log.calls:
        out.append({"model": str(c.get("model") or ""), "provider": str(c.get("provider") or ""),
                    "purpose": "claim", "latency_ms": int(c.get("latency_ms") or 0),
                    "cost_usd": str(c.get("cost_usd") or "0"), "outcome": str(c.get("error") or "ok")})
    if not out and errors:  # refused before any call (AI off, no key, budget): recorded, at no cost
        out.append({"model": "", "provider": "", "purpose": "claim", "latency_ms": 0, "cost_usd": "0",
                    "outcome": errors[0][:80]})
    return out


def draft_text(lines: list[ClaimLine], *, router: ModelRouter, tenant_id: str, request_id: str | None,
               ppu: int | None = None, window: int | None = None) -> Draft:
    template = template_text(lines, ppu=ppu, window=window)
    log = CallLog()
    errors: list[str] = []
    if not router.models:
        return Draft(template, "template", ["model:no_model_configured"])
    messages = [{"role": "system", "content": CLAIM_PROMPT}, {"role": "user", "content": template}]
    try:
        res = router.chat(messages, tools=None, deadline=time.monotonic() + claim_deadline_s(), tenant_id=tenant_id,
                          request_id=request_id, log=log, errors=errors, purpose="claim", max_tokens=CLAIM_MAX_TOKENS)
    except ModelError as e:
        reasons = [f"model:{x}" for x in errors] or [f"model:{e.code}"]
        return Draft(template, "template", reasons, _calls(log, errors or [e.code]))
    calls = _calls(log, errors)
    text = _clean(res.message.get("content"))
    if not text:
        return Draft(template, "template", ["model:empty_answer"], calls)
    if len(text.split()) > MAX_WORDS:
        return Draft(template, "template", ["local:too_long"], calls)
    local = numbers.check(text, template)
    if local:
        return Draft(template, "template", local, calls)
    return Draft(text, "model", [], calls)
