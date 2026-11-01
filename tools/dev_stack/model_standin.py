"""Model stand-in for the dev stack: a local HTTP double of the two Meta Model API calls a vision look makes.

NOT the Meta Model API and never presented as it. Started only by `stack up --model-standin` (127.0.0.1,
FIELD_STACK_MODEL_PORT, default 8430); the stack then points field-api's META_MODEL_API_BASE_URL at it, gives field-api
a dev marker instead of MODEL_API_KEY and a zero-price pricing file (tools/dev_stack/model_standin_pricing.yaml), so
`stack smoke --m5-look` runs both test cases end to end without a key, a network route or spend. Production code
never imports this module; the request and answer shapes it serves are the UNVERIFIED ones of
field_api.vision.sam / field_api.vision.labels (META_FIELD rows 20, 23).

    POST /_standin/scene   {"boxes": [[x0, y0, x1, y1], ...], "width", "height", "labels": {"<n>": {...}}}
         the scene the next looks see: boxes in reading order (n = index + 1), label fields as the label schema
    GET  /_standin/requests -> {"responses": <n>, "chat": <n>, "models": [...]}  (counts, never a header)
    POST /v1/responses          SAM 3.1: server-sent events, text "<0f>" + box tokens of the scene (shuffled)
    POST /v1/chat/completions   with images: the label JSON for the numbered crops asked; without: a short JSON say
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Model stand-in (dev stack only, not the Meta Model API)")
SCENE: dict[str, Any] = {"boxes": [], "width": 0, "height": 0, "labels": {}}
SEEN: dict[str, Any] = {"responses": 0, "chat": 0, "models": []}
_N = re.compile(r"(\d+):$")


def box_text(boxes: list[list[int]], width: int, height: int, seed: int = 7) -> str:
    order = list(enumerate(boxes))
    random.Random(seed).shuffle(order)  # SAM's order is not reading order; the look numbers them itself
    recs = [f"{i}<|box;x1={b[0]};y1={b[1]};x2={b[2] - 1};y2={b[3] - 1};w={width};h={height};c=0.9|>"
            f"<|mask;x=0;y=0;data=1,1,~!|>" for i, b in order]
    return "<0f>" + ",".join(recs) if recs else ""


def label_items(content: list[dict[str, Any]], labels: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for part in content:
        m = _N.search(str(part.get("text") or "")) if part.get("type") == "text" else None
        if not m:
            continue
        n = int(m.group(1))
        truth = labels.get(str(n)) or {}
        items.append({"n": n, "label_readable": bool(truth.get("label_readable", bool(truth))),
                      "pieces_per_unit": truth.get("pieces_per_unit"), "batch": truth.get("batch"),
                      "expiry": truth.get("expiry"), "damaged": bool(truth.get("damaged", False)),
                      "damage_note": truth.get("damage_note"), "label_text": truth.get("label_text")})
    return items


@app.post("/_standin/scene")
async def set_scene(request: Request) -> dict[str, Any]:
    body = await request.json()
    SCENE.update({"boxes": [list(map(int, b)) for b in body.get("boxes") or []], "width": int(body["width"]),
                  "height": int(body["height"]), "labels": {str(k): v for k, v in (body.get("labels") or {}).items()}})
    return {"boxes": len(SCENE["boxes"])}


@app.get("/_standin/requests")
async def requests_seen() -> dict[str, Any]:
    return dict(SEEN)


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    body = await request.json()
    SEEN["responses"] += 1
    SEEN["models"].append(body.get("model"))
    text = box_text(SCENE["boxes"], SCENE["width"], SCENE["height"])
    events = [{"type": "response.created", "response": {"status": "in_progress"}}]
    events += [{"type": "response.output_text.delta", "delta": text[i:i + 80]} for i in range(0, len(text), 80)]
    events.append({"type": "response.completed",
                   "response": {"status": "completed", "usage": {"input_tokens": 0, "output_tokens": 0}}})
    data = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return Response(data, media_type="text/event-stream")


CLAIM_DRAFT_PROMPT_START = "You write the body of a short, polite claim message"


@app.post("/v1/chat/completions")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    SEEN["chat"] += 1
    SEEN["models"].append(body.get("model"))
    messages = body.get("messages") or [{}]
    content = messages[-1].get("content")
    system = str(messages[0].get("content") or "") if messages[0].get("role") == "system" else ""
    if isinstance(content, list) and any(p.get("type") == "image_url" for p in content):
        answer = json.dumps({"items": label_items(content, SCENE["labels"])})
    elif system.startswith(CLAIM_DRAFT_PROMPT_START) and isinstance(content, str):
        answer = content  # a claim draft (M5 claims): the facts as given, so field-api's number check passes
    else:
        answer = json.dumps({"say": "The model stand-in has no answer to that.", "card": {"title": "Stand-in"},
                             "actions": []})
    return JSONResponse({"id": "chatcmpl-standin", "object": "chat.completion", "model": body.get("model"),
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": answer}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                                   "prompt_tokens_details": {"cached_tokens": 0}}})
