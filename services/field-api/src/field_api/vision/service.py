"""One vision look (docs/design/M5_CONTRACT.md §2): the orchestrator of stages a-f and the look record.

a) instances: SAM 3.1 with the object noun as text prompt, within VISION_INSTANCES_DEADLINE_S;
b) label + damage reads: each instance cropped from the capture, crops batched VISION_CROPS_PER_CALL per Muse
   Spark 1.3 call (batches in parallel), within VISION_LABELS_DEADLINE_S;
c) a batch Muse did not answer goes to the Baseten Llama 3.2 Vision fallback, within VISION_FALLBACK_DEADLINE_S;
d) the deterministic check (vision.reconcile) against the delivery line and its test-case expectation;
e) the proposal and ``say`` (vision.say: a number-checked template);
f) no model answered (AI off, no key, budget or unconfirmed price refused, timeout, error): ``source: rules``,
   no instances, counts.seen null, ``say`` asks for a spoken count. Never an error to the app.

``source``: ``model`` when the instances and every label batch were answered, ``partial`` when the instances were but
some label batch was not (those instances are ``read: false``), ``rules`` otherwise. The look never stages or posts
anything; a receipt posted with ``look_id`` links it (tasks/api.py). On a count task the line's expected quantity is
the book quantity, so it is never used (blind count, FR3.029): counts.expected is null there.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from statistics import median
from typing import Any, Literal

import structlog
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from field_api.ai.budget import BudgetGuard
from field_api.assistant.model import (
    BASETEN_KEY_ENV,
    META_KEY_ENV,
    ChatModel,
    ModelError,
    ProviderConfig,
)
from field_api.auth.jwt import Principal
from field_api.crops import CropStoreError, crop_store
from field_api.db import principal_tx
from field_api.errors import FieldError
from field_api.vision import settings
from field_api.vision.image import Capture, ImageUnreadable, crops, open_capture
from field_api.vision.labels import ChatLabelReader
from field_api.vision.ports import CallContext, FoundInstance, LabelRead, LabelReader, VisionPorts
from field_api.vision.reconcile import Check, Expectation, Seen, reconcile
from field_api.vision.sam import Sam31Instances
from field_api.vision.say import say_for

logger = structlog.get_logger(__name__)

Case = Literal["grocery", "pharmacy", "generic"]
DEFAULT_OBJECT: dict[str, str] = {"grocery": "pack", "pharmacy": "box", "generic": "item"}
ERR_TASK = FieldError(status=404, code="FIELD-VIS-404-TASK", title="Task not found or out of scope")
ERR_CAPTURE = FieldError(status=404, code="FIELD-VIS-404-CAPTURE", title="Capture not found or out of scope")
ERR_LOOK = FieldError(status=404, code="FIELD-VIS-404-LOOK", title="Look not found or out of scope")
ERR_LINE = FieldError(status=422, code="FIELD-VIS-422-LINE", title="The line is not a line of this task")
ERR_SITE = FieldError(status=422, code="FIELD-VIS-422-SITE", title="The capture was taken at another site")


class LookIn(BaseModel):
    task_id: str
    line_id: str | None = None
    capture_id: str
    object: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z -]{0,39}$",
                               description="the noun to count (pack, box, carton); default from the case")
    case: Case = "generic"


def get_vision_ports() -> VisionPorts:
    """FastAPI dependency: SAM 3.1 and Muse Spark 1.3 on the Meta Model API, the Baseten fallback when configured.
    Tests override it with adapters over an httpx test transport (test code only)."""
    guard = BudgetGuard()
    readers: list[LabelReader] = []
    instances: Sam31Instances | None = None
    try:
        instances = Sam31Instances(settings.meta_base_url(), settings.instances_model(), guard)
    except ValueError as e:  # a refused model id: no instances, the look answers by rules
        logger.warning("vision_model_refused", error=str(e))
    try:
        readers.append(ChatLabelReader(ChatModel(ProviderConfig("meta", settings.meta_base_url(),
                                                                settings.labels_model(), META_KEY_ENV), guard)))
    except ValueError as e:
        logger.warning("vision_model_refused", error=str(e))
    bt_model, bt_url = settings.baseten_vision_model(), settings.baseten_base_url()
    if bt_model and bt_url:
        try:
            readers.append(ChatLabelReader(ChatModel(ProviderConfig("baseten", bt_url, bt_model, BASETEN_KEY_ENV),
                                                     guard), use_response_format=False))
        except ValueError as e:
            logger.warning("vision_model_refused", error=str(e))
    return VisionPorts(instances, tuple(readers))


# --------------------------------------------------------------------------- context
@dataclass(frozen=True)
class LookContext:
    site_id: str
    task_type: str
    line_id: str | None
    expectation: Expectation
    crop_uri: str | None


def _qty(v: Any) -> int | None:
    if v is None:
        return None
    d = Decimal(v)
    return int(d) if d == d.to_integral_value() else None


def _context(cur: Any, body: LookIn) -> LookContext:
    cur.execute("SELECT id, site_id, type FROM field.task WHERE id::text = %s", (body.task_id,))
    t = cur.fetchone()
    if not t:
        raise ERR_TASK
    site_id, task_type = str(t[1]), str(t[2])
    line_id = body.line_id
    if line_id:
        cur.execute("SELECT id, expected_qty FROM field.task_line WHERE id::text = %s AND task_id = %s",
                    (line_id, t[0]))
        line = cur.fetchone()
        if not line:
            raise ERR_LINE
    else:
        cur.execute("SELECT id, expected_qty FROM field.task_line WHERE task_id = %s AND status <> 'cancelled'"
                    " ORDER BY line_no LIMIT 2", (t[0],))
        rows = cur.fetchall()
        line = rows[0] if len(rows) == 1 else None
        line_id = str(line[0]) if line else None
    cur.execute("SELECT site_id FROM field.capture WHERE id::text = %s", (body.capture_id,))
    cap = cur.fetchone()
    if not cap:
        raise ERR_CAPTURE
    if str(cap[0]) != site_id:
        raise ERR_SITE
    cur.execute("SELECT crop_s3_uri, retention_until, is_legal_hold FROM field.capture_evidence"
                " WHERE capture_id::text = %s ORDER BY created_at DESC LIMIT 1", (body.capture_id,))
    ev = cur.fetchone()
    uri = str(ev[0]) if ev and (ev[1] >= datetime.now(UTC) or ev[2]) else None
    case_row = None
    if line_id:
        cur.execute("SELECT \"case\", object, expected_pieces_per_unit, expiry_window_days"
                    " FROM field.vision_case_line WHERE task_line_id::text = %s", (line_id,))
        case_row = cur.fetchone()
    case = body.case if body.case != "generic" or case_row is None else str(case_row[0])
    noun = (body.object or (str(case_row[1]) if case_row else DEFAULT_OBJECT[case])).strip().lower()
    expected = _qty(line[1]) if line is not None and task_type == "receive" else None  # never a book qty (FR3.029)
    exp = Expectation(case=case, object_noun=noun, expected_units=expected,
                      expected_pieces_per_unit=int(case_row[2]) if case_row and case_row[2] is not None else None,
                      window_days=int(case_row[3]) if case_row and case_row[3] is not None
                      else settings.expiry_window_days())
    return LookContext(site_id, task_type, line_id, exp, uri)


# --------------------------------------------------------------------------- stages
def order_instances(found: list[FoundInstance]) -> list[FoundInstance]:
    """Score filter, cap, then reading order (rows of about one box height, left to right): ``n`` is stable."""
    lo = settings.min_score()
    kept = [f for f in found if f.score is None or f.score >= lo]
    kept.sort(key=lambda f: -(f.score if f.score is not None else 1.0))
    kept = kept[:settings.max_instances()]
    if not kept:
        return []
    band = max(1.0, median(f.box[3] - f.box[1] for f in kept))
    return sorted(kept, key=lambda f: (int(((f.box[1] + f.box[3]) / 2) // band), f.box[0], f.box[1]))


def _batches(items: list[tuple[int, bytes]], size: int) -> list[list[tuple[int, bytes]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def read_labels(readers: tuple[LabelReader, ...], cap: Capture, inst: list[FoundInstance], exp: Expectation,
                ctx: CallContext, reasons: list[str]) -> tuple[dict[int, LabelRead], bool]:
    """Reads per instance number, and whether every batch was answered by some reader."""
    if not inst:
        return {}, True
    if not readers:
        reasons.append("labels:no_model")
        return {}, False
    numbered = crops(cap, [(n, f.box) for n, f in enumerate(inst, start=1)])
    start = time.monotonic()
    primary_end = start + settings.labels_deadline_s()
    fallback_s = settings.fallback_deadline_s()

    def one(batch: list[tuple[int, bytes]]) -> tuple[dict[int, LabelRead], bool, list[str]]:
        errs: list[str] = []
        for i, reader in enumerate(readers):
            now = time.monotonic()
            remaining = primary_end - now if i == 0 else min(fallback_s, primary_end + fallback_s - now)
            if remaining < 0.3:
                errs.append(f"labels:{reader.model}:AI_DEADLINE")
                continue
            try:
                got = reader.read(batch, case=exp.case, object_noun=exp.object_noun, timeout_s=remaining, ctx=ctx)
            except ModelError as e:
                errs.append(f"labels:{reader.model}:{e.code}")
                continue
            return got, True, errs
        return {}, False, errs

    groups = _batches(numbered, settings.crops_per_call())
    with ThreadPoolExecutor(max_workers=min(4, len(groups))) as pool:
        results = list(pool.map(one, groups))
    reads: dict[int, LabelRead] = {}
    answered = True
    for got, ok, errs in results:
        reads.update(got)
        answered = answered and ok
        for e in errs:
            if e not in reasons:
                reasons.append(e)
    return reads, answered


def _seen(n: int, r: LabelRead | None) -> Seen:
    r = r or LabelRead(read=False)
    return Seen(n, damaged=r.damaged, read=r.read, pieces_per_unit=r.pieces_per_unit, batch=r.batch, expiry=r.expiry)


def _instance_body(n: int, f: FoundInstance, r: LabelRead | None) -> dict[str, Any]:
    r = r or LabelRead(read=False)
    return {"n": n, "box": list(f.box), "polygon": f.polygon, "score": f.score, "damaged": r.damaged,
            "damage_note": r.damage_note,
            "label": {"read": r.read, "pieces_per_unit": r.pieces_per_unit, "batch": r.batch, "expiry": r.expiry}}


# --------------------------------------------------------------------------- the look
LOOK_COLS = ("id, task_id, line_id, capture_id, \"case\", object, source, image, instances, raw_labels, counts, pack,"
             " expiry, proposal, say, models, reasons, erp_document_id, created_at, cost_usd, latency_ms")


def look_body(row: tuple[Any, ...]) -> dict[str, Any]:
    """The response body (contract §2) from a vision_look row (LOOK_COLS order), with label.raw while kept."""
    (look_id, task_id, line_id, capture_id, case, obj, source, image, instances, raw, counts, pack, expiry, proposal,
     say, models, reasons, erp_doc, created_at, _cost, _latency) = row
    raw_map: dict[str, Any] = raw or {}
    inst = []
    for i in instances or []:
        label = {**i["label"], "raw": raw_map.get(str(i["n"]))}
        inst.append({**i, "label": label})
    return {"look_id": str(look_id), "source": source, "image": image, "instances": inst, "counts": counts,
            "pack": pack, "expiry": expiry, "proposal": proposal, "say": say, "models": models, "reasons": reasons,
            "task_id": str(task_id), "line_id": str(line_id) if line_id else None, "capture_id": str(capture_id),
            "case": case, "object": obj, "erp_document_id": str(erp_doc) if erp_doc else None,
            "created_at": created_at.isoformat()}


def _existing(cur: Any, key: str) -> dict[str, Any] | None:
    cur.execute(f"SELECT {LOOK_COLS} FROM field.vision_look WHERE idempotency_key = %s", (key,))  # noqa: S608
    row = cur.fetchone()
    return look_body(row) if row else None


def create_look(principal: Principal, body: LookIn, idempotency_key: str, ports: VisionPorts,
                today: Callable[[], date] = lambda: datetime.now(UTC).date()) -> dict[str, Any]:
    t0 = time.perf_counter()
    with principal_tx(principal) as cur:
        again = _existing(cur, idempotency_key)
        if again is not None:
            return again
        lc = _context(cur, body)
    reasons: list[str] = []
    ctx = CallContext(principal.tenant_id, idempotency_key)
    cap: Capture | None = None
    if lc.crop_uri is None:
        reasons.append("image:unavailable")
    else:
        try:
            cap = open_capture(crop_store().get(lc.crop_uri))
        except (CropStoreError, OSError):
            reasons.append("image:unavailable")
        except ImageUnreadable:
            reasons.append("image:unreadable")
    found: list[FoundInstance] | None = None
    if cap is not None:
        if ports.instances is None:
            reasons.append("instances:no_model")
        else:
            try:
                found = order_instances(ports.instances.find(cap.jpeg, cap.width, cap.height, lc.expectation.object_noun,
                                                             timeout_s=settings.instances_deadline_s(), ctx=ctx))
            except ModelError as e:
                reasons.append(f"instances:{ports.instances.model}:{e.code}")
    reads: dict[int, LabelRead] = {}
    answered = False
    if found is not None and cap is not None:
        reads, answered = read_labels(ports.readers, cap, found, lc.expectation, ctx, reasons)
    seen = None if found is None else [_seen(n, reads.get(n)) for n in range(1, len(found) + 1)]
    check: Check = reconcile(seen, lc.expectation, today())
    source = "rules" if found is None else ("model" if answered else "partial")
    instances = [] if found is None else [_instance_body(n, f, reads.get(n)) for n, f in enumerate(found, start=1)]
    raw = {str(n): r.raw for n, r in reads.items() if r.raw}
    models = [{"model": c.model, "purpose": c.purpose, "latency_ms": c.latency_ms, "cost_usd": float(c.cost_usd),
               "outcome": c.outcome} for c in ctx.calls]
    cost = sum((c.cost_usd for c in ctx.calls), Decimal(0))
    image = {"capture_id": body.capture_id, "width": cap.width if cap else None, "height": cap.height if cap else None}
    say = say_for(check, lc.expectation)
    latency = int((time.perf_counter() - t0) * 1000)
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            INSERT INTO field.vision_look (tenant_id, site_id, task_id, line_id, capture_id, "case", object, source,
                   idempotency_key, principal_id, device_id, image, instances, raw_labels, counts, pack, expiry,
                   proposal, say, models, reasons, cost_usd, latency_ms)
            VALUES (%s, %s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s)
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING {LOOK_COLS}
            """,  # noqa: S608 - fixed column list
            (principal.tenant_id, lc.site_id, body.task_id, lc.line_id, body.capture_id, lc.expectation.case,
             lc.expectation.object_noun, source, idempotency_key, principal.id, principal.device_id, Jsonb(image),
             Jsonb(instances), Jsonb(raw) if raw else None, Jsonb(check.counts), _jsonb(check.pack),
             _jsonb(check.expiry), Jsonb(check.proposal), say, Jsonb(models), Jsonb(reasons), cost, latency),
        )
        row = cur.fetchone()
        out = look_body(row) if row else _existing(cur, idempotency_key)
    if out is None:  # pragma: no cover - the conflicting row is visible in the same tenant
        raise ERR_LOOK
    logger.info("vision_look", look_id=out["look_id"], source=source, seen=check.counts["seen"],
                calls=len(models), latency_ms=latency)  # never the label text
    return out


def _jsonb(v: dict[str, Any] | None) -> Jsonb | None:
    return None if v is None else Jsonb(v)


def get_look(principal: Principal, look_id: str) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(f"SELECT {LOOK_COLS} FROM field.vision_look WHERE id::text = %s", (look_id,))  # noqa: S608
        row = cur.fetchone()
    if not row:
        raise ERR_LOOK
    return look_body(row)
