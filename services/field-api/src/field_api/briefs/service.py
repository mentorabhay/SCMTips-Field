"""``POST /v1/briefs/spoken``: a decision's template brief rewritten by Muse into a natural ~20 s spoken brief,
spoken only after the core's number check accepts it (M4 contract §4, F3; core handover 01 §F3 and 01a).

Order, each step ending in the template on failure (``source: "template"`` with the reasons):
1. both headers present (X-Core-Token, X-Device-Id), else no model call at all (``missing:...``);
2. one Muse call through the model router and the budget guard (AI off, no key, refused or prohibited model,
   over budget, error, cut-off answer, or no answer within BRIEF_DEADLINE_S: ``model:...``). The model sees the
   template with every figure replaced by a marker [F1], [F2], ... (``markers``) and writes only the words around
   them; field-api puts the template's own figures back. A model that writes figures itself is still checked;
3. the local checks (``local:...``): the number check (``numbers``) and the core's own acceptance rule ported
   (``core_rule``: the template's figures, digits, order and signs, their labels, no number in words, at most 70
   words). A refusal never costs a core call; when time is left before the deadline (RETRY_MIN_S), the model is
   asked once more with what was wrong (reasons of that try prefixed ``retry:``);
4. the core's check with the app's core token (``core:...``); when the core sends its own template_text, that is
   the template spoken.
The core token is forwarded once and never stored, logged or sent to the model.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any

import structlog

from field_api.assistant.model import CallLog, ModelError, ModelRouter, spoken_reasoning_effort
from field_api.auth.jwt import Principal
from field_api.briefs import core_rule, markers, numbers
from field_api.briefs.core import CoreBriefCheck

logger = structlog.get_logger(__name__)

BRIEF_DEADLINE_S = 4.0  # default; BRIEF_DEADLINE_S in the environment overrides it within 2..8 s


def brief_deadline_s() -> float:
    """Seconds the model may take for a spoken brief: env BRIEF_DEADLINE_S within 2..8, else 4.0."""
    try:
        v = float(os.getenv("BRIEF_DEADLINE_S", "").strip())
    except ValueError:
        return BRIEF_DEADLINE_S
    return max(2.0, min(8.0, v)) if math.isfinite(v) else BRIEF_DEADLINE_S
MAX_WORDS = 150
RETRY_MIN_S = 1.5  # a second try only when at least this much of the deadline is left
BRIEF_PROMPT = (
    "You turn a supply-chain decision brief into what an approver hears through smart glasses. Every figure of the "
    "brief (amounts, percentages, dates, week numbers, codes) has been replaced by a marker such as [F1]. Rewrite the "
    "brief as natural spoken English that takes about 20 seconds to say (about 50 words, never more than 65). Keep "
    "every marker exactly once, written exactly as it is, in the same order as in the brief, and keep next to each "
    "marker the words that say what it is (net, commits, fill rate, saves, week, deadline). Write no other number, "
    "in digits or in words, than the number words already in the brief. Do not add any fact, name, opinion or "
    "recommendation that is not in the brief, and do not leave out an option. Plain sentences only: no lists, no "
    "markdown, no quotes. Reply with the spoken text and nothing else."
)


def retry_prompt(masked: markers.Masked) -> str:
    """The second try's instruction: what the first answer broke, without the figures."""
    keep = ", ".join(masked.markers) if masked.figures else "no marker"
    return ("That rewrite cannot be spoken: it changed, moved, dropped or added a figure, or wrote a number in "
            f"words. Rewrite the brief again, keeping {keep} exactly once each, in this order, each next to the "
            "words that say what it is, with no other number, in at most 65 words. Reply with the spoken text only.")


@dataclass(frozen=True)
class BriefIn:
    decision_id: str
    template_text: str
    core_token: str | None
    device_id: str | None


def _clean(content: Any) -> str:
    text = content if isinstance(content, str) else ""
    text = text.strip().strip("`").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return " ".join(text.split())


def _template(b: BriefIn, reasons: list[str], core_template: str | None = None) -> dict[str, Any]:
    return {"text": core_template or b.template_text, "source": "template", "reasons": reasons}


def spoken_brief(principal: Principal, b: BriefIn, *, router: ModelRouter, core: CoreBriefCheck,
                 request_id: str | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    log = CallLog()
    out = _run(principal, b, router, core, request_id, log)
    logger.info("brief_spoken", decision_id=b.decision_id, source=out["source"], reasons=out["reasons"],
                model_calls=len(log.calls), latency_ms=int((time.perf_counter() - t0) * 1000))
    return out


def _run(principal: Principal, b: BriefIn, router: ModelRouter, core: CoreBriefCheck, request_id: str | None,
         log: CallLog) -> dict[str, Any]:
    token, device = (b.core_token or "").strip(), (b.device_id or "").strip()
    missing = [r for r, v in (("missing:x_core_token", token), ("missing:x_device_id", device)) if not v]
    if missing:
        return _template(b, missing)
    deadline = time.monotonic() + brief_deadline_s()
    masked = markers.mask(b.template_text)
    messages: list[dict[str, Any]] = [{"role": "system", "content": BRIEF_PROMPT},
                                      {"role": "user", "content": masked.text}]
    text, reasons, raw = _attempt(principal, b, masked, messages, router, deadline, request_id, log)
    if text is None and raw is not None:  # refused by a local check: one more try if the deadline allows it
        if deadline - time.monotonic() < RETRY_MIN_S:
            return _template(b, [*reasons, "retry:no_time"])
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": retry_prompt(masked)}]
        text, again, _raw = _attempt(principal, b, masked, messages, router, deadline, request_id, log)
        reasons = [*reasons, *(f"retry:{r}" for r in again)]
    if text is None:
        return _template(b, reasons)
    verdict = core.check(b.decision_id, text, core_token=token, device_id=device)
    if not verdict.accepted:
        return _template(b, verdict.reasons or ["core:refused"], verdict.template_text)
    return {"text": text, "source": "model", "reasons": []}


def _attempt(principal: Principal, b: BriefIn, masked: markers.Masked, messages: list[dict[str, Any]],
             router: ModelRouter, deadline: float, request_id: str | None,
             log: CallLog) -> tuple[str | None, list[str], str | None]:
    """One model call and the local checks: (the text to send to the core, or None; the reasons; the model's raw
    answer when a local check refused it, else None: only such a refusal is worth a second try)."""
    errors: list[str] = []
    try:
        res = router.chat(messages, tools=None, deadline=deadline, tenant_id=principal.tenant_id,
                          request_id=request_id, log=log, errors=errors, purpose="brief",
                          reasoning_effort=spoken_reasoning_effort())
    except ModelError as e:
        reasons = [f"model:{x}" for x in errors] or [f"model:{e.code}"]
        if not router.models:
            reasons = ["model:no_model_configured"]
        return None, reasons, None
    raw = _clean(res.message.get("content"))
    if not raw:
        return None, ["model:empty_answer"], None
    if len(raw.split()) > MAX_WORDS:
        return None, ["local:too_long"], None
    text, unknown = markers.unmask(raw, masked)
    local = unknown + numbers.check(text, b.template_text)
    local += [f"local:{p}" for p in core_rule.refusals(text, b.template_text, "spoken")]
    if local:
        return None, local, raw
    return text, [], None
