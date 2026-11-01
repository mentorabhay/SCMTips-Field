"""One assistant turn: session, rules (or the model), tools, safe actions, the record.

Rules first (M4, owner's field test of 31 Oct 2026: every turn went to Muse first, timed out after 6 s and fell
back, so Start Work answered 6-7 s late). ``needs_model`` decides: every event other than an utterance or a photo
(session start and end, pause, resume, step done, scan, unknown code), an utterance while a dialog is open, and
every utterance the rules classify are answered by rules at once, with no model call. Only an utterance the rules
cannot classify, and "what is this" about a photo without a code, go to the model.

Model path: system prompt + a compact context (site mode, the open job, the open work) + the last turns + this
event, with the four read-only server tools. At most MAX_MODEL_CALLS calls within ASSISTANT_MODEL_DEADLINE_S
(default 3.5 s) for the whole AI part; any refusal (AI off, no key, budget), error or timeout falls back to rules
mode for this turn. A photo goes to the model as an image only for "what is this" without a code, to suggest a
name; the barcode stays the key.

Whatever path answered: ``say`` is clipped to two sentences, actions pass ``actions.sanitize`` (no confirm, only
the contract's types, only task ids visible at this site), and the turn is recorded.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog

from field_api.assistant import actions as safe_actions
from field_api.assistant import records, work
from field_api.assistant.model import (
    CallLog,
    ModelError,
    ModelRouter,
    model_deadline_s,
    spoken_reasoning_effort,
)
from field_api.assistant.photos import AssistantPhotoStore, decode_photo
from field_api.assistant.ports import AssistantPorts
from field_api.assistant.prompts import SYSTEM_PROMPT, clip_say
from field_api.assistant.rules import Reply, RulesEngine, intent, is_yes
from field_api.assistant.tools import AssistantTools, TurnContext, tool_specs
from field_api.auth.jwt import Principal
from field_api.deps import require_site_scope
from field_api.errors import FieldError

logger = structlog.get_logger(__name__)

MAX_MODEL_CALLS = 3
HISTORY_TURNS = 6
# Events the rules always answer (M4 rules first). "utterance" and "photo" are decided by needs_model.
RULES_EVENTS = frozenset({"session_start", "session_end", "pause", "resume", "step_done", "scan", "unknown_code"})

ERR_SITE_NOT_FOUND = FieldError(status=404, code="FIELD-AST-404-SITE", title="Site not found")
ERR_SESSION_NOT_FOUND = FieldError(status=404, code="FIELD-AST-404-SESSION", title="Assistant session not found")
ERR_SESSION_ENDED = FieldError(status=409, code="FIELD-AST-409-SESSION-ENDED",
                               title="This assistant session has ended. Start a new one.")
ERR_SESSION_SITE = FieldError(status=422, code="FIELD-AST-422-SESSION-SITE",
                              title="This assistant session belongs to another site")


@dataclass(frozen=True)
class TurnIn:
    session_id: str | None
    site_id: str
    event: str
    text: str | None
    code: str | None
    photo_jpeg_b64: str | None
    task_id: str | None
    line_id: str | None
    step: str | None
    look_id: str | None = None  # M5: the phone's last look, for "make a claim"


def _parse_json_object(content: str) -> dict[str, Any] | None:
    content = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, re.DOTALL)
    if fence:
        content = fence.group(1)
    try:
        v = json.loads(content)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    start, end = content.find("{"), content.rfind("}")
    if 0 <= start < end:
        try:
            v = json.loads(content[start:end + 1])
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


def _card_of(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {"title": str(v.get("title") or "")[:120], "body": str(v.get("body") or "")[:2000]}
    return {"title": "", "body": ""}


def needs_model(t: TurnIn, dialog: dict[str, Any] | None, has_photo: bool) -> bool:
    """True only for what the rules cannot answer: an unclassified utterance outside a dialog, or "what is this"
    (event photo, or the utterance) about a photo without a code. Everything else is rules first."""
    if t.event in RULES_EVENTS:
        return False
    if t.event == "photo":
        return has_photo and not t.code
    if dialog:
        return False
    name = intent(t.text)[0]
    if name == "what_is":
        return has_photo and not t.code
    return name == "unknown"


def _wants_vision(t: TurnIn) -> bool:
    return bool(t.photo_jpeg_b64) and not t.code and (t.event == "photo" or intent(t.text)[0] == "what_is")


def _context(tools: AssistantTools, t: TurnIn) -> dict[str, Any]:
    ctx = tools.ctx
    return {
        "site_mode": ctx.site_mode,
        "client_state": {"task_id": t.task_id, "line_id": t.line_id, "step": t.step},
        "open_job": tools.current_task(),
        "open_work": tools.list_work()[:10],
        "can_create_home_work": tools.can_create and ctx.site_mode == "sandbox",
    }


def _messages(tools: AssistantTools, t: TurnIn, history: list[dict[str, Any]], photo: bytes | None) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "Context (JSON): " + json.dumps(_context(tools, t), default=str)},
    ]
    for h in history:
        heard = " ".join(x for x in (f"[{h['event']}]", h.get("heard") or "", f"code {h['code']}" if h.get("code")
                                     else "") if x)
        msgs.append({"role": "user", "content": heard})
        if h.get("said"):
            msgs.append({"role": "assistant", "content": json.dumps({"say": h["said"]})})
    now = " ".join(x for x in (f"[{t.event}]", t.text or "", f"code {t.code}" if t.code else "") if x)
    if photo is not None:
        msgs.append({"role": "user", "content": [
            {"type": "text", "text": now + " (photo attached: suggest a name only; the barcode is the key)"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(photo).decode()}},
        ]})
    else:
        msgs.append({"role": "user", "content": now})
    return msgs


def run_model(router: ModelRouter, tools: AssistantTools, t: TurnIn, history: list[dict[str, Any]],
              photo: bytes | None, log: CallLog, errors: list[str], request_id: str | None) -> Reply:
    """The model's answer, or ModelError. Tool calls run server side; at most MAX_MODEL_CALLS calls."""
    deadline = time.monotonic() + model_deadline_s()
    msgs = _messages(tools, t, history, photo)
    specs = tool_specs()
    for _ in range(MAX_MODEL_CALLS):
        res = router.chat(msgs, tools=specs, deadline=deadline, tenant_id=tools.ctx.principal.tenant_id,
                          request_id=request_id, log=log, errors=errors, reasoning_effort=spoken_reasoning_effort())
        m = res.message
        calls = m.get("tool_calls") or []
        if calls:
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for c in calls if isinstance(calls, list) else []:
                call: dict[str, Any] = c if isinstance(c, dict) else {}
                fn = call.get("function")
                fn = fn if isinstance(fn, dict) else {}
                result = tools.run(str(fn.get("name") or ""), fn.get("arguments"))
                msgs.append({"role": "tool", "tool_call_id": str(call.get("id") or ""),
                             "content": json.dumps(result, default=str)})
            continue
        content = m.get("content")
        text = content if isinstance(content, str) else ""
        obj = _parse_json_object(text)
        if obj is None:
            if not text.strip():
                raise ModelError("AI_BAD_RESPONSE", "empty answer")
            return Reply(text, {"title": "", "body": ""})
        return Reply(str(obj.get("say") or ""), _card_of(obj.get("card")),
                     list(obj["actions"]) if isinstance(obj.get("actions"), list) else [])
    raise ModelError("AI_TOO_MANY_TOOL_CALLS")


def ai_enabled() -> bool:
    return os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() == "true"


def run_turn(principal: Principal, t: TurnIn, *, idempotency_key: str, ports: AssistantPorts,
             router: ModelRouter, request_id: str | None = None,
             photo_store: AssistantPhotoStore | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    require_site_scope(t.site_id, principal)
    mode = work.site_mode(principal, t.site_id)
    if mode is None:
        raise ERR_SITE_NOT_FOUND
    photo = decode_photo(t.photo_jpeg_b64) if t.photo_jpeg_b64 else None

    if t.session_id:
        session = records.load_session(principal, t.session_id)
        if session is None or session["principal_id"] != principal.id:
            raise ERR_SESSION_NOT_FOUND
        if session["ended_at"] is not None:
            raise ERR_SESSION_ENDED
        if session["site_id"] != t.site_id:
            raise ERR_SESSION_SITE
    else:
        sid = records.create_session(principal, t.site_id, mode if mode in ("production", "sandbox") else "production")
        session = {"id": sid, "site_id": t.site_id, "principal_id": principal.id, "dialog": None, "ended_at": None}

    photo_ref = (photo_store or AssistantPhotoStore()).put(principal.tenant_id, photo) if photo is not None else None
    dialog = session.get("dialog") if isinstance(session.get("dialog"), dict) else None
    explicit_yes = t.event == "utterance" and is_yes(t.text) and bool(dialog)
    ctx = TurnContext(principal=principal, site_id=t.site_id, session_id=session["id"], site_mode=mode,
                      ports=ports, idempotency_key=idempotency_key, task_id=t.task_id, dialog=dialog,
                      explicit_yes=explicit_yes, look_id=t.look_id)
    tools = AssistantTools(ctx)
    history = records.recent_turns(principal, session["id"], HISTORY_TURNS)

    log = CallLog()
    errors: list[str] = []
    ai = "rules"
    path = "rules"
    reply: Reply | None = None
    if needs_model(t, dialog, photo is not None):
        path = "model"
        try:
            if not ai_enabled():
                raise ModelError("AI_CLOUD_DISABLED")
            reply = run_model(router, tools, t, history, photo if _wants_vision(t) else None, log, errors,
                              request_id)
            ai = "model"
            reply.task_id = t.task_id
        except ModelError as e:
            if e.code not in ("AI_UNAVAILABLE",):
                errors.append(e.code)
            logger.info("assistant_rules_fallback", reasons=errors)
            path = "fallback"
    if reply is None:
        last_said = next((h["said"] for h in reversed(history) if h.get("said")), None)
        reply = RulesEngine(tools, last_said).answer(t.event, t.text, t.code, photo is not None)

    proposed = list(reply.actions)
    visible = work.visible_task_ids(principal, t.site_id, safe_actions.task_ids(proposed))
    acts = safe_actions.sanitize(proposed, visible)
    say = clip_say(reply.say) or "Sorry, say that again?"
    task_id = reply.task_id or t.task_id or next((a["task_id"] for a in acts if "task_id" in a), None)
    if task_id and not work.visible_task_ids(principal, t.site_id, [task_id]):
        task_id = None
    tool_calls = list(tools.calls)
    if ai == "rules" and errors:
        tool_calls.append({"name": "fallback", "reasons": errors[:6]})
    if log.calls:
        tool_calls.append({"name": "model_calls", "calls": log.calls})
    cost: Decimal = log.cost_usd
    latency = int((time.perf_counter() - t0) * 1000)
    logger.info("assistant_turn", turn_event=t.event, path=path, ai=ai, latency_ms=latency, model_calls=len(log.calls))
    records.record_turn(principal, session, event=t.event, heard=t.text, said=say, actions=acts,
                        tool_calls=tool_calls, code=t.code, photo_ref=photo_ref, ai=ai, cost_usd=cost,
                        latency_ms=latency, task_id=task_id, dialog=reply.dialog,
                        end=t.event == "session_end")
    return {"session_id": session["id"], "say": say, "card": reply.card, "actions": acts, "ai": ai,
            "cost_usd": float(round(cost, 6))}
