"""M5 Gate 0 probe: the first real calls of the vision look's two models, on the owner's PC (META_FIELD rows 20, 23).

    uv run python tools/probes/m5_gate0.py --photo <path to a JPEG/PNG> [--prompt pack] [--case grocery]
                                           [--allow-unconfirmed-prices] [--only g0-1|g0-2] [--no-evidence]

G0-1  Muse Spark 1.3 image input: the photo as one crop through field-api's own label reader (chat completions,
      response_format json_schema): label readable, pieces per unit, batch, expiry, damage.
G0-2  SAM 3.1 instances for a text prompt (the object noun) through field-api's own adapter (Responses API, SSE).

Both go through the real budget guard (the dev stack's database, FIELD_DATABASE_URL from .env.local, caps
AI_BUDGET_META_USD / AI_DAILY_CAP_USD, AI_CLOUD_ENABLED=true). Both prices are placeholders (config/ai_pricing.yaml,
confirmed: false), so the guard refuses them unless --allow-unconfirmed-prices is given: that sets
AI_ALLOW_UNCONFIRMED_PRICES=true for this process only, and the cost recorded is the placeholder. MODEL_API_KEY is
read from .env.local by name (tools/dev_stack/assistant_check.load_env_local) and never printed or written.

Prints per probe: status, latency, token usage, the parsed answer, and the exact request and response SHAPES (keys
and value types; base64 images, label text and the key are never shown). Writes the same, redacted, to
docs/evidence/<date>-m5-gate0-<time>.txt for the owner to commit (label text is reduced to its length: no brand or
product names in the repository, contract §6).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence"
MAX_SIDE = 1600  # the photo is scaled to at most this side, JPEG, like a capture
# Keys whose string values are protocol words, not content: shown as they are (e.g. "input_image", "stop").
LITERAL_KEYS = frozenset({"type", "role", "model", "finish_reason", "object", "status", "stream", "include_confidence",
                          "name", "strict"})


def shape(v: Any, depth: int = 0) -> Any:
    """Keys and value types of a JSON value; lists show their distinct element shapes; strings show only a type and length
    (base64 data URLs, label text and anything else that could carry content or a secret)."""
    if depth > 8:
        return "..."
    if isinstance(v, dict):
        return {k: (x if k in LITERAL_KEYS and isinstance(x, str) and len(x) <= 64 else shape(x, depth + 1))
                for k, x in v.items()}
    if isinstance(v, list):  # the distinct element shapes (at most 4), and the count when there are more elements
        kinds: list[Any] = []
        for x in v:
            sx = shape(x, depth + 1)
            if sx not in kinds and len(kinds) < 4:
                kinds.append(sx)
        return kinds + ([f"... {len(v)} items"] if len(v) > len(kinds) else [])
    if isinstance(v, str):
        if v.startswith("data:"):
            return f"<data url, {len(v)} chars>"
        return f"<str {len(v)}>"
    if isinstance(v, bool) or v is None:
        return v
    return type(v).__name__


def sse_shape(text: str) -> dict[str, Any]:
    """Event types of a server-sent event stream, with the shape of the first event of each type."""
    out: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("data: ") and line[6:].strip() != "[DONE]":
            try:
                ev = json.loads(line[6:])
            except ValueError:
                continue
            t = str(ev.get("type")) if isinstance(ev, dict) else "?"
            out.setdefault(t, shape(ev))
    return out


@dataclass
class Exchange:
    path: str
    request_shape: Any
    status: int | None = None
    content_type: str = ""
    response_shape: Any = None
    usage: Any = None
    error: str | None = None
    sam_text_sample: str | None = None  # the first 240 characters of SAM's output text (box geometry only)


@dataclass
class RecordingTransport(httpx.BaseTransport):
    """Wraps a transport and keeps the shape of each request and answer (never a header value)."""

    inner: httpx.BaseTransport
    seen: list[Exchange] = field(default_factory=list)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content)
        except ValueError:
            body = None
        ex = Exchange(request.url.path, shape(body))
        self.seen.append(ex)
        try:
            resp = self.inner.handle_request(request)
        except httpx.HTTPError as e:
            ex.error = type(e).__name__
            raise
        resp.read()
        ex.status, ex.content_type = resp.status_code, resp.headers.get("content-type", "")
        if "text/event-stream" in ex.content_type:
            ex.response_shape = sse_shape(resp.text)
            if request.url.path.endswith("/responses"):
                deltas = []
                for line in resp.text.splitlines():
                    if line.startswith("data: ") and "output_text.delta" in line:
                        try:
                            deltas.append(str(json.loads(line[6:]).get("delta") or ""))
                        except ValueError:
                            continue
                ex.sam_text_sample = "".join(deltas)[:240]
            for line in resp.text.splitlines():
                if line.startswith("data: ") and '"usage"' in line:
                    try:
                        ev = json.loads(line[6:])
                    except ValueError:
                        continue
                    r = ev.get("response") if isinstance(ev, dict) else None
                    if isinstance(r, dict) and isinstance(r.get("usage"), dict):
                        ex.usage = r["usage"]
        else:
            try:
                data = resp.json()
            except ValueError:
                data = None
            ex.response_shape = shape(data)
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                ex.usage = data["usage"]
        return resp


def load_photo(path: Path) -> tuple[bytes, int, int]:
    from PIL import Image

    with Image.open(path) as src:
        img = src.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        f = MAX_SIDE / max(w, h)
        img = img.resize((int(w * f), int(h * f)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), img.size[0], img.size[1]


@dataclass
class ProbeResult:
    probe: str
    model: str
    status: str  # OK | BLOCKED | FAILED
    detail: str
    latency_ms: int
    answer: Any
    exchanges: list[Exchange]


def run_g0_1(jpeg: bytes, case: str, noun: str, transport: httpx.BaseTransport, guard: Any,
             timeout_s: float = 60.0) -> ProbeResult:
    from field_api.assistant.model import META_KEY_ENV, ChatModel, ModelError, ProviderConfig
    from field_api.vision import settings
    from field_api.vision.labels import ChatLabelReader
    from field_api.vision.ports import CallContext

    rec = RecordingTransport(transport)
    model = settings.labels_model()
    reader = ChatLabelReader(ChatModel(ProviderConfig("meta", settings.meta_base_url(), model, META_KEY_ENV), guard,
                                       rec))
    ctx = CallContext(None, "m5-gate0")
    t0 = time.perf_counter()
    try:
        reads = reader.read([(1, jpeg)], case=case, object_noun=noun, timeout_s=timeout_s, ctx=ctx)
    except ModelError as e:
        status = "BLOCKED" if not rec.seen else "FAILED"
        return ProbeResult("G0-1", model, status, e.code, int((time.perf_counter() - t0) * 1000), None, rec.seen)
    r = reads.get(1)
    answer = None if r is None else {"read": r.read, "pieces_per_unit": r.pieces_per_unit, "batch": r.batch,
                                     "expiry": r.expiry, "damaged": r.damaged,
                                     "label_text_chars": len(r.raw) if r.raw else 0}
    cost = sum(float(c.cost_usd) for c in ctx.calls)
    return ProbeResult("G0-1", model, "OK", f"cost_usd={cost:.6f}", int((time.perf_counter() - t0) * 1000), answer,
                       rec.seen)


def run_g0_2(jpeg: bytes, width: int, height: int, noun: str, transport: httpx.BaseTransport,
             guard: Any, timeout_s: float = 60.0) -> ProbeResult:
    from field_api.assistant.model import ModelError
    from field_api.vision import settings
    from field_api.vision.ports import CallContext
    from field_api.vision.sam import Sam31Instances

    rec = RecordingTransport(transport)
    model = settings.instances_model()
    sam = Sam31Instances(settings.meta_base_url(), model, guard, rec)
    ctx = CallContext(None, "m5-gate0")
    t0 = time.perf_counter()
    try:
        found = sam.find(jpeg, width, height, noun, timeout_s=timeout_s, ctx=ctx)
    except ModelError as e:
        status = "BLOCKED" if not rec.seen else "FAILED"
        return ProbeResult("G0-2", model, status, e.code, int((time.perf_counter() - t0) * 1000), None, rec.seen)
    cost = sum(float(c.cost_usd) for c in ctx.calls)
    answer = {"instances": len(found), "boxes": [list(f.box) for f in found[:5]],
              "scores": [f.score for f in found[:5]]}
    return ProbeResult("G0-2", model, "OK", f"cost_usd={cost:.6f}", int((time.perf_counter() - t0) * 1000), answer,
                       rec.seen)


def report(results: list[ProbeResult], photo: str, size: tuple[int, int]) -> str:
    lines = [f"M5 Gate 0 probe (tools/probes/m5_gate0.py), {datetime.now(UTC).isoformat(timespec='seconds')}",
             f"photo: {Path(photo).name}, sent as JPEG {size[0]}x{size[1]}; key: MODEL_API_KEY from .env.local "
             "(not recorded); base URL: " + os.getenv("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
             f"AI_ALLOW_UNCONFIRMED_PRICES={os.getenv('AI_ALLOW_UNCONFIRMED_PRICES', 'false')}", ""]
    for r in results:
        lines.append(f"{r.probe} {r.model}: {r.status} {r.detail} latency_ms={r.latency_ms}")
        lines.append(f"  answer: {json.dumps(r.answer)}")
        for ex in r.exchanges:
            lines.append(f"  POST {ex.path} -> HTTP {ex.status} {ex.content_type} {ex.error or ''}".rstrip())
            lines.append(f"  usage: {json.dumps(ex.usage)}")
            if ex.sam_text_sample is not None:
                lines.append(f"  SAM text (first 240 chars): {ex.sam_text_sample}")
            lines.append(f"  request shape: {json.dumps(ex.request_shape)}")
            lines.append(f"  response shape: {json.dumps(ex.response_shape)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None, guard: Any = None,
         evidence_dir: Path = EVIDENCE) -> int:
    ap = argparse.ArgumentParser(prog="m5_gate0")
    ap.add_argument("--photo", required=True, type=Path)
    ap.add_argument("--prompt", default="pack", help="the object noun for SAM and the label reader")
    ap.add_argument("--case", default="grocery", choices=("grocery", "pharmacy", "generic"))
    ap.add_argument("--only", choices=("g0-1", "g0-2"))
    ap.add_argument("--timeout", type=float, default=60.0,
                    help="seconds per model call (default 60: measures the real latency; the look's own deadlines are"
                         " the VISION_*_DEADLINE_S settings)")
    ap.add_argument("--allow-unconfirmed-prices", action="store_true",
                    help="AI_ALLOW_UNCONFIRMED_PRICES=true for this run only (the placeholder prices are recorded)")
    ap.add_argument("--no-evidence", action="store_true", help="print only, write no file")
    a = ap.parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.dev_stack.assistant_check import load_env_local

    load_env_local()  # names only; values never printed
    if a.allow_unconfirmed_prices:
        os.environ["AI_ALLOW_UNCONFIRMED_PRICES"] = "true"
    if guard is None:
        from field_api.ai.budget import BudgetGuard

        guard = BudgetGuard()
    jpeg, w, h = load_photo(a.photo)
    net = transport or httpx.HTTPTransport()
    results: list[ProbeResult] = []
    if a.only in (None, "g0-1"):
        results.append(run_g0_1(jpeg, a.case, a.prompt, net, guard, a.timeout))
    if a.only in (None, "g0-2"):
        results.append(run_g0_2(jpeg, w, h, a.prompt, net, guard, a.timeout))
    text = report(results, str(a.photo), (w, h))
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key and key in text:  # never: shapes carry no values; refuse to print or write if it ever did
        print("FAIL: the report would contain the key; nothing printed or written")
        return 2
    print(text, end="")
    if not a.no_evidence:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        out = evidence_dir / f"{datetime.now(UTC):%Y-%m-%d}-m5-gate0-{datetime.now(UTC):%H%M%S}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"evidence: {out} (redacted: no key, no image, label text as its length only)")
    for r in results:
        if r.status == "BLOCKED" and r.detail == "AI_PRICE_UNCONFIRMED":
            print("note: the price is a placeholder; rerun with --allow-unconfirmed-prices to make the call")
    return 0 if results and all(r.status == "OK" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
