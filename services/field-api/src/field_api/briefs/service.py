"""``POST /v1/briefs/spoken``: a decision's template brief rewritten by Muse into a natural ~20 s spoken brief,
spoken only after the core's number check accepts it (M4 contract §4, F3; core handover 01 §F3 and 01a).

Order, each step ending in the template on failure (``source: "template"`` with the reasons):
1. both headers present (X-Core-Token, X-Device-Id), else no model call at all (``missing:...``);
2. one Muse call through the model router and the budget guard (AI off, no key, refused or prohibited model,
   over budget, error, cut-off answer, or no answer within BRIEF_DEADLINE_S: ``model:...``);
3. the local number check (``local:...``): a refused rewrite never costs a core call;
4. the core's check with the app's core token (``core:...``); when the core sends its own template_text, that is
   the template spoken.
The core token is forwarded once and never stored, logged or sent to the model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

from field_api.assistant.model import CallLog, ModelError, ModelRouter
from field_api.auth.jwt import Principal
from field_api.briefs import numbers
from field_api.briefs.core import CoreBriefCheck

logger = structlog.get_logger(__name__)

BRIEF_DEADLINE_S = 4.0
MAX_WORDS = 150
BRIEF_PROMPT = (
    "You turn a supply-chain decision brief into what an approver hears through smart glasses. Rewrite the brief "
    "as natural spoken English that takes about 20 seconds to say (about 50 words). Keep every number, unit, date, "
    "percentage, name and option exactly as written, with numbers in digits. Do not add any fact, number, name, "
    "opinion or recommendation that is not in the brief, and do not leave out an option. Plain sentences only: no "
    "lists, no markdown, no quotes. Reply with the spoken text and nothing else."
)


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
    errors: list[str] = []
    messages = [{"role": "system", "content": BRIEF_PROMPT}, {"role": "user", "content": b.template_text}]
    try:
        res = router.chat(messages, tools=None, deadline=time.monotonic() + BRIEF_DEADLINE_S,
                          tenant_id=principal.tenant_id, request_id=request_id, log=log, errors=errors,
                          purpose="brief")
    except ModelError as e:
        reasons = [f"model:{x}" for x in errors] or [f"model:{e.code}"]
        if not router.models:
            reasons = ["model:no_model_configured"]
        return _template(b, reasons)
    text = _clean(res.message.get("content"))
    if not text:
        return _template(b, ["model:empty_answer"])
    if len(text.split()) > MAX_WORDS:
        return _template(b, ["local:too_long"])
    local = numbers.check(text, b.template_text)
    if local:
        return _template(b, local)
    verdict = core.check(b.decision_id, text, core_token=token, device_id=device)
    if not verdict.accepted:
        return _template(b, verdict.reasons or ["core:refused"], verdict.template_text)
    return {"text": text, "source": "model", "reasons": []}
