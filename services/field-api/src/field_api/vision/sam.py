"""SAM 3.1 instances on the Meta Model API (stage a of the look), behind the budget guard.

Request shape, from Meta's docs read on 2026-11-01 (https://dev.meta.ai/docs/media-segmentation; model list
https://dev.meta.ai/docs/models: ``sam-3.1``, "Responses API, Files API", output "Boxes and masks"):

    POST {META_MODEL_API_BASE_URL}/responses      Authorization: Bearer <MODEL_API_KEY>, Accept: text/event-stream
    {"model": "sam-3.1", "stream": true, "metadata": {"include_confidence": "true"},
     "input": [{"type": "message", "role": "user", "content": [
         {"type": "input_text", "text": "<object noun>"},
         {"type": "input_image", "image_url": "data:image/jpeg;base64,..."}]}]}

Answer: server-sent events; the text arrives as ``response.output_text.delta`` events. The text is one line per
frame, ``<Nf>`` then records ``<id><|box;x1=..;y1=..;x2=..;y2=..;w=<W>;h=<H>[;c=<conf>]|><|mask;...|>`` separated by
commas (Meta's parser package meta-sam-parser on PyPI, author Meta Platforms, Inc.: corners and w/h are source
pixels, x2/y2 inclusive, ``c`` only with metadata include_confidence). The mask is not decoded here (polygon null):
the look needs boxes. A non-streamed JSON answer (``output[].content[].text``) is accepted too.

Billing: per image ($2.50 per 1,000 images on https://dev.meta.ai/docs/pricing-rate-limits), so the guard reserves
one image at config/ai_pricing.yaml's per_image_usd (a placeholder marked confirmed: false until the owner checks
the console: refused unless AI_ALLOW_UNCONFIRMED_PRICES=true). Every part of this is UNVERIFIED (META_FIELD row 23):
the build sandbox has no key and no route to api.meta.ai; the owner's Gate 0 probe (tools/probes/m5_gate0.py) is
the first real call.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from decimal import Decimal
from typing import Any

import httpx
import structlog

from field_api.ai.budget import BudgetGuard, BudgetRefused, Reservation
from field_api.assistant.model import CALL_TIMEOUT_S, META_KEY_ENV, ModelError, validate_model_id
from field_api.vision.ports import CallContext, FoundInstance, ModelCall

logger = structlog.get_logger(__name__)

_BOX = re.compile(r"<\|box;([^|>]*)\|>")


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def sam_request(model: str, prompt: str, jpeg: bytes) -> dict[str, Any]:
    """The request body (see the module docstring)."""
    return {"model": model, "stream": True, "metadata": {"include_confidence": "true"},
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url(jpeg)}]}]}


def _fields(token: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in token.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_boxes(text: str, width: int, height: int) -> list[FoundInstance]:
    """Boxes of every ``<|box;...|>`` token in ``text`` (all frames), scaled to the capture's pixels when the token's
    w/h differ from it, clipped to the image, half-open. Tokens with missing or bad corners are skipped."""
    found: list[FoundInstance] = []
    for m in _BOX.finditer(text):
        f = _fields(m.group(1))
        try:
            x1, y1, x2, y2 = (float(f[k]) for k in ("x1", "y1", "x2", "y2"))
            fw, fh = float(f.get("w") or width), float(f.get("h") or height)
        except (KeyError, ValueError):
            continue
        if fw <= 0 or fh <= 0:
            continue
        sx, sy = width / fw, height / fh
        x0, y0 = max(0, int(x1 * sx)), max(0, int(y1 * sy))
        xe, ye = min(width, int((x2 + 1) * sx)), min(height, int((y2 + 1) * sy))
        if xe <= x0 or ye <= y0:
            continue
        score: float | None = None
        if "c" in f:
            try:
                c = float(f["c"])
                score = c if 0.0 <= c <= 1.0 else None
            except ValueError:
                score = None
        found.append(FoundInstance((x0, y0, xe, ye), score))
    return found


def _text_and_usage(r: httpx.Response) -> tuple[str, dict[str, Any] | None]:
    """The output text and usage of a Responses answer, streamed (SSE) or one JSON object."""
    ctype = r.headers.get("content-type", "")
    if "text/event-stream" not in ctype:
        body = r.json()
        if not isinstance(body, dict):
            raise ValueError("answer is not an object")
        return _output_text(body), body.get("usage") if isinstance(body.get("usage"), dict) else None
    deltas: list[str] = []
    final: dict[str, Any] | None = None
    for line in r.text.splitlines():
        if not line.startswith("data: "):
            continue
        data = line.removeprefix("data: ").strip()
        if data == "[DONE]":
            break
        ev = json.loads(data)
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "response.output_text.delta" and isinstance(ev.get("delta"), str):
            deltas.append(ev["delta"])
        elif ev.get("type") in ("response.completed", "response.incomplete") and isinstance(ev.get("response"), dict):
            final = ev["response"]
        elif ev.get("type") in ("response.failed", "error"):
            raise ValueError("the stream reported a failure")
    text = "".join(deltas) or (_output_text(final) if final else "")
    usage = final.get("usage") if final and isinstance(final.get("usage"), dict) else None
    return text, usage


def _output_text(body: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "output_text" and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "".join(parts)


def _tokens(usage: dict[str, Any] | None) -> tuple[int, int]:
    if not usage:
        return 0, 0
    try:
        return max(0, int(usage.get("input_tokens") or 0)), max(0, int(usage.get("output_tokens") or 0))
    except (TypeError, ValueError):
        return 0, 0


class Sam31Instances:
    """InstanceFinder over the Meta Model API. ``transport`` is for tests (an httpx test transport)."""

    def __init__(self, base_url: str, model: str, guard: BudgetGuard | None = None,
                 transport: httpx.BaseTransport | None = None, key_env: str = META_KEY_ENV) -> None:
        self.base_url = base_url
        self._model = validate_model_id(model)
        self.guard = guard or BudgetGuard()
        self._transport = transport
        self.key_env = key_env

    @property
    def model(self) -> str:
        return self._model

    def find(self, image_jpeg: bytes, width: int, height: int, prompt: str, *, timeout_s: float,
             ctx: CallContext) -> list[FoundInstance]:
        def record(outcome: str, latency: int = 0, cost: Decimal = Decimal(0)) -> None:
            ctx.calls.append(ModelCall(self._model, "instances", latency, cost, outcome))

        if os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() != "true":
            record("AI_CLOUD_DISABLED")
            raise ModelError("AI_CLOUD_DISABLED")
        key = os.environ.get(self.key_env, "").strip()
        if not key:
            record("AI_NO_KEY")
            raise ModelError("AI_NO_KEY", f"{self.key_env} is not set")
        try:
            res = self.guard.reserve("meta", self._model, input_tokens=0, max_output_tokens=1, purpose="vision",
                                     tenant_id=ctx.tenant_id, request_id=ctx.request_id, images=1)
        except BudgetRefused as e:
            record(e.code)
            raise ModelError(e.code, str(e)) from None
        timeout = min(max(timeout_s, 0.1), CALL_TIMEOUT_S)
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=self.base_url, timeout=timeout, transport=self._transport) as client:
                r = client.post("/responses", json=sam_request(self._model, prompt, image_jpeg),
                                headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"})
        except httpx.TimeoutException:
            self._failed(res, res.reserved_usd, "AI_TIMEOUT", ctx, t0)
            raise ModelError("AI_TIMEOUT") from None
        except httpx.HTTPError as e:
            self._failed(res, res.reserved_usd, "AI_TRANSPORT", ctx, t0)
            raise ModelError("AI_TRANSPORT", type(e).__name__) from None
        if not r.is_success:
            self._failed(res, Decimal(0), f"AI_HTTP_{r.status_code}", ctx, t0)
            raise ModelError(f"AI_HTTP_{r.status_code}")
        try:
            text, usage = _text_and_usage(r)
        except (ValueError, json.JSONDecodeError):
            self._failed(res, res.reserved_usd, "AI_BAD_RESPONSE", ctx, t0)
            raise ModelError("AI_BAD_RESPONSE", "the answer could not be read") from None
        tin, tout = _tokens(usage)
        cost = self.guard.settle(res, input_tokens=tin, output_tokens=tout)
        latency = int((time.perf_counter() - t0) * 1000)
        found = parse_boxes(text, width, height)
        if not found and "<|box" not in text and text.strip() and not re.search(r"<\d+f>", text):
            record("AI_BAD_RESPONSE", latency, cost)
            raise ModelError("AI_BAD_RESPONSE", "no box tokens in the answer")
        record("ok", latency, cost)
        return found

    def _failed(self, res: Reservation, billed: Decimal, code: str, ctx: CallContext, t0: float) -> None:
        self.guard.fail(res, billed_usd=billed)
        logger.warning("vision_model_call_failed", model=self._model, purpose="instances", code=code)
        ctx.calls.append(ModelCall(self._model, "instances", int((time.perf_counter() - t0) * 1000), billed, code))
