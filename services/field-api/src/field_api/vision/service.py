"""One vision look (docs/design/M5_CONTRACT.md §2): the orchestrator of stages a-f and the look record.

a) instances: SAM 3.1 with the object noun as text prompt, within VISION_INSTANCES_DEADLINE_S, in two layers (M5-V11,
   ``find_instances``): Muse Spark names the goods and estimates the count while SAM answers for the noun; an empty or
   disagreeing answer makes SAM try "package", "box" and the named nouns, and the answer nearest the estimate is kept;
b) label + damage reads: each instance cropped from the capture, crops batched VISION_CROPS_PER_CALL per Muse
   Spark 1.3 call (batches in parallel), within VISION_LABELS_DEADLINE_S;
c) a batch Muse did not answer goes to the Baseten Llama 3.2 Vision fallback, within VISION_FALLBACK_DEADLINE_S;
d) the deterministic check (vision.reconcile) against the delivery line and its test-case expectation;
e) the proposal and ``say`` (vision.say: a number-checked template);
f) no model answered (AI off, no key, budget or unconfirmed price refused, timeout, error): ``source: rules``,
   no instances, counts.seen null, ``say`` asks for a spoken count. Never an error to the app.

Photo size (M5-P01): the app sends a look photo of at most 1600 px on its long side (JPEG ~85, faces pixelated on
the phone on that full photo before upload, captures API 1 MB limit). SAM gets the photo as stored; each label crop
is cut from it and scaled to at most CROP_MAX_SIDE (768 px, vision.image).

Small instances (many items in one view, or a small camera photo): when labels were read but some came back unreadable
and the instances' median short side is under VISION_LABEL_MIN_INSTANCE_PX (200 pixels), ``reasons`` gets ``labels:close_look_needed`` and
``labels:small_image:<w>x<h>:instance_px=<n>``, and ``say`` ends by asking for a close look at a label.

Two steps (M5-S01): with instances and a label reader, POST answers as soon as SAM's instances are counted:
``final: false``, ``source: partial``, counts.expected/seen set, counts.damaged/good null, proposal receive/flag null,
instances with ``label.read: false``, and ``say`` "<count>. Reading the labels." (number-checked). The label read
(stages b-e) runs after the answer, in the route's background task (``finish_labels``), and writes the final look:
``final: true``, ``say`` as in one step, ``say_next`` = what to speak after the first answer. When no label batch is
answered (or anything fails) the look ends ``partial`` with the label-free check and ``say`` LABELS_FAILED_SAY. A
look whose read is still unfinished at ``labels_due_at`` (labels + fallback deadlines + 15 s; e.g. field-api
restarted) is ended the same way, reason ``labels:not_finished``, by the next read of it (GET, an idempotent POST
replay, a claim, the evidence page). Without instances or without a reader the look is final in one step.

``source``: ``model`` when the instances and every label batch were answered, ``partial`` when the instances were but
some label batch was not (those instances are ``read: false``) or while the labels are being read, ``rules``
otherwise. The look never stages or posts
anything; a receipt posted with ``look_id`` links it (tasks/api.py). On a count task the line's expected quantity is
the book quantity, so it is never used (blind count, FR3.029): counts.expected is null there.

Try looks (M5-W01, vision.try_look): the same engine (``run_look``: stages a-f, one or two steps) on a photo uploaded
from the console's "Try a look" page, with no task, line or capture (``LookTarget`` kind ``try``). A try look is never
returned by ``get_look`` (so no claim, evidence pack or posting can use it); it is read through vision.try_look.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from types import MappingProxyType
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
from field_api.vision.namer import ChatObjectNamer
from field_api.vision.ports import (
    CallContext,
    FoundInstance,
    LabelRead,
    LabelReader,
    Naming,
    ObjectNamer,
    VisionPorts,
)
from field_api.vision.reconcile import Check, Expectation, Seen, reconcile
from field_api.vision.sam import Sam31Instances
from field_api.vision.say import LABELS_FAILED_SAY, first_say, next_say, say_for

logger = structlog.get_logger(__name__)

Case = Literal["grocery", "pharmacy", "generic"]
DEFAULT_OBJECT: Mapping[str, str] = MappingProxyType({"grocery": "pack", "pharmacy": "box", "generic": "item"})
CLOSE_LOOK_SAY = " Some labels are too small to read: take a close look at one label."
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
    return vision_ports(BudgetGuard())


def vision_ports(guard: BudgetGuard) -> VisionPorts:
    """The production adapters over one budget guard (the try page passes a guard with the ``try`` scope)."""
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
    namer: ChatObjectNamer | None = None
    if settings.naming_enabled():  # M5-V11: layer 1 of the instances stage (Muse names the goods, estimates the count)
        try:
            namer = ChatObjectNamer(ChatModel(ProviderConfig("meta", settings.meta_base_url(),
                                                             settings.labels_model(), META_KEY_ENV), guard))
        except ValueError as e:
            logger.warning("vision_model_refused", error=str(e))
    return VisionPorts(instances, tuple(readers), namer)


# --------------------------------------------------------------------------- context
@dataclass(frozen=True)
class LookTarget:
    """What a look row points at: a task's capture (``task``, the M5 look) or an uploaded try photo (``try``, M5-W01:
    no task, line, capture or ERP document; the photo in the try photo store, kept until ``photo_expires_at``)."""
    kind: Literal["task", "try"]
    task_id: str | None
    capture_id: str | None
    photo_uri: str | None = None
    photo_sha256: str | None = None
    photo_expires_at: datetime | None = None


@dataclass(frozen=True)
class LookContext:
    site_id: str | None  # None for a try look (M5-W01)
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
             " expiry, proposal, say, models, reasons, erp_document_id, created_at, cost_usd, latency_ms, final,"
             " say_next")


def look_body(row: tuple[Any, ...]) -> dict[str, Any]:
    """The response body (contract §2) from a vision_look row (LOOK_COLS order), with label.raw while kept."""
    (look_id, task_id, line_id, capture_id, case, obj, source, image, instances, raw, counts, pack, expiry, proposal,
     say, models, reasons, erp_doc, created_at, _cost, _latency, final, say_next) = row
    raw_map: dict[str, Any] = raw or {}
    inst = []
    for i in instances or []:
        label = {**i["label"], "raw": raw_map.get(str(i["n"]))}
        inst.append({**i, "label": label})
    return {"look_id": str(look_id), "source": source, "image": image, "instances": inst, "counts": counts,
            "pack": pack, "expiry": expiry, "proposal": proposal, "say": say, "models": models, "reasons": reasons,
            "final": bool(final), "say_next": say_next,
            "task_id": str(task_id) if task_id else None, "line_id": str(line_id) if line_id else None,
            "capture_id": str(capture_id) if capture_id else None,
            "case": case, "object": obj, "erp_document_id": str(erp_doc) if erp_doc else None,
            "created_at": created_at.isoformat()}


# A label read still unfinished this long after its deadlines (labels + fallback) is given up on any read of the look:
# a field-api restart in the middle of a read never leaves the look waiting (M5-S01).
LABELS_GRACE_S = 15.0
_GIVE_UP = """
    UPDATE field.vision_look
       SET final = true, source = 'partial', say = %(say)s, say_next = %(say)s,
           counts = labels_fallback->'counts', pack = NULLIF(labels_fallback->'pack', 'null'::jsonb),
           expiry = NULLIF(labels_fallback->'expiry', 'null'::jsonb), proposal = labels_fallback->'proposal',
           reasons = CASE WHEN reasons @> jsonb_build_array(%(reason)s::text) THEN reasons
                          ELSE reasons || jsonb_build_array(%(reason)s::text) END
     WHERE id::text = %(id)s AND NOT final
"""


_OVERDUE_BY = MappingProxyType({
    "idempotency_key": "SELECT id FROM field.vision_look WHERE idempotency_key = %s AND NOT final AND labels_due_at < NOW()",
    "id::text": "SELECT id FROM field.vision_look WHERE id::text = %s AND NOT final AND labels_due_at < NOW()",
})


def _settle_overdue(cur: Any, where: str, value: str) -> None:
    """Ends a look whose label read is past its due time (reason labels:not_finished): read paths call this first."""
    cur.execute(_OVERDUE_BY[where], (value,))
    row = cur.fetchone()
    if row:
        cur.execute(_GIVE_UP, {"say": LABELS_FAILED_SAY, "reason": "labels:not_finished", "id": str(row[0])})
        logger.info("vision_look_labels_given_up", look_id=str(row[0]))


def _existing(cur: Any, key: str) -> dict[str, Any] | None:
    _settle_overdue(cur, "idempotency_key", key)
    cur.execute(f"SELECT {LOOK_COLS} FROM field.vision_look WHERE idempotency_key = %s", (key,))  # noqa: S608
    row = cur.fetchone()
    return look_body(row) if row else None


@dataclass
class Outcome:
    """The columns a look's stages b-e produce (stage a's instances given)."""
    source: str
    instances: list[dict[str, Any]]
    raw: dict[str, str]
    check: Check
    say: str
    models: list[dict[str, Any]]
    cost: Decimal


def _outcome(cap: Capture | None, found: list[FoundInstance] | None, reads: dict[int, LabelRead], answered: bool,
             lc: LookContext, ctx: CallContext, reasons: list[str], today: date) -> Outcome:
    """Stages d-e from the instances and the label reads: the check, source, ``say`` (number-checked)."""
    close_look = False
    if found and cap is not None and reads:
        unread = sum(1 for n in range(1, len(found) + 1) if not (reads.get(n) or LabelRead(False)).read)
        px = int(median(min(f.box[2] - f.box[0], f.box[3] - f.box[1]) for f in found))
        if unread and px < settings.label_min_instance_px():
            close_look = True
            reasons += ["labels:close_look_needed", f"labels:small_image:{cap.width}x{cap.height}:instance_px={px}"]
    seen = None if found is None else [_seen(n, reads.get(n)) for n in range(1, len(found) + 1)]
    check: Check = reconcile(seen, lc.expectation, today)
    source = "rules" if found is None else ("model" if answered else "partial")
    instances = [] if found is None else [_instance_body(n, f, reads.get(n)) for n, f in enumerate(found, start=1)]
    raw = {str(n): r.raw for n, r in reads.items() if r.raw}
    models = [{"model": c.model, "purpose": c.purpose, "latency_ms": c.latency_ms, "cost_usd": float(c.cost_usd),
               "outcome": c.outcome} for c in ctx.calls]
    cost = sum((c.cost_usd for c in ctx.calls), Decimal(0))
    say = say_for(check, lc.expectation) + (CLOSE_LOOK_SAY if close_look else "")
    return Outcome(source, instances, raw, check, say, models, cost)


@dataclass(frozen=True)
class LabelStage:
    """What the label read needs after the first answer of a two-step look (M5-S01)."""
    principal: Principal
    look_id: str
    first_say: str
    cap: Capture
    found: list[FoundInstance]
    lc: LookContext
    ctx: CallContext
    reasons: list[str]
    readers: tuple[LabelReader, ...]
    t0: float
    today: date


def finish_labels(stage: LabelStage) -> None:
    """Stages b-e of a two-step look, after its first answer: reads the labels within the deadlines and writes the
    final look (``final`` true, ``say_next``). If no batch was answered, or anything fails, the look ends ``partial``
    with the label-free check of its first answer and says LABELS_FAILED_SAY. Only a look still unfinished is
    written: one already given up (past its due time) stays as it is."""
    try:
        reads, answered = read_labels(stage.readers, stage.cap, stage.found, stage.lc.expectation, stage.ctx,
                                      stage.reasons)
        out = _outcome(stage.cap, stage.found, reads, answered, stage.lc, stage.ctx, stage.reasons, stage.today)
        say = LABELS_FAILED_SAY if not answered and not reads else out.say
        latency = int((time.perf_counter() - stage.t0) * 1000)
        with principal_tx(stage.principal) as cur:
            cur.execute(
                """
                UPDATE field.vision_look
                   SET source = %s, instances = %s, raw_labels = %s, counts = %s, pack = %s, expiry = %s,
                       proposal = %s, say = %s, say_next = %s, models = %s, reasons = %s, cost_usd = %s,
                       latency_ms = %s, final = true
                 WHERE id::text = %s AND NOT final
                """,
                (out.source, Jsonb(out.instances), Jsonb(out.raw) if out.raw else None, Jsonb(out.check.counts),
                 _jsonb(out.check.pack), _jsonb(out.check.expiry), Jsonb(out.check.proposal), say,
                 next_say(say, stage.first_say), Jsonb(out.models), Jsonb(stage.reasons), out.cost, latency,
                 stage.look_id),
            )
            written = cur.rowcount == 1
        logger.info("vision_look_labels", look_id=stage.look_id, source=out.source, written=written,
                    calls=len(out.models), latency_ms=latency)  # never the label text
    except Exception:  # the look must end in a definite state whatever failed
        logger.exception("vision_look_labels_failed", look_id=stage.look_id)
        with principal_tx(stage.principal) as cur:
            cur.execute(_GIVE_UP, {"say": LABELS_FAILED_SAY, "reason": "labels:error", "id": stage.look_id})


Defer = Callable[[Callable[[], None]], None]


def create_look(principal: Principal, body: LookIn, idempotency_key: str, ports: VisionPorts,
                today: Callable[[], date] = lambda: datetime.now(UTC).date(), defer: Defer | None = None
                ) -> dict[str, Any]:
    """The look. When there are instances and a label reader, it is two-step (M5-S01): the first answer is written and
    returned at once (``final`` false, source ``partial``, the count only, ``say`` "<count>. Reading the labels.")
    and the label read is handed to ``defer`` (the route's background task). Without ``defer`` the label read runs
    before returning and the final look is returned. Otherwise (no photo, no instances, no reader) it is final in
    one step, as before."""
    t0 = time.perf_counter()
    with principal_tx(principal) as cur:
        again = _existing(cur, idempotency_key)
        if again is not None:
            return again
        lc = _context(cur, body)
    reasons: list[str] = []
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
    return run_look(principal, LookTarget("task", body.task_id, body.capture_id), lc, cap, reasons, idempotency_key,
                    ports, today, defer, t0)


# SAM 3.1 answers only for words it knows the goods by (M5-V11). Hosted 1 Nov: "pack" found 0 of 8 packs where "box"
# found them; hosted 3-4 Nov on the owner's real biscuit packs: "pack" and "box" found 0 of 5 on three photos while
# "package" found 5 of 5 on each and 8 of 8 on the try page's SAMPLE photo (docs/evidence/runs/
# 2026-11-04-look-two-layer-probe.md). So the instances stage has two layers:
#   1. at once: SAM on the case's noun, and (with a namer) Muse naming the goods and estimating their count;
#   2. when the first answer is empty or its count disagrees with the estimate: SAM on the generic words
#      (SAM_GENERIC; started as soon as the first answer is empty), then on the nouns Muse named, all in parallel.
# The answer kept is the one closest to the estimate (without one: the most instances, then the higher mean score).
# The spoken unit stays the case's noun; everything happens inside the instances deadline.
SAM_GENERIC: tuple[str, ...] = ("package", "box")
MAX_RETRY_WORDS = 3
MIN_RETRY_S = 1.0


def sam_prompts(noun: str) -> list[str]:
    """The case's noun, then the generic words layer 2 tries (no repeats)."""
    first = noun.strip().lower()
    return [first] + [w for w in SAM_GENERIC if w != first]


def estimate_agrees(seen: int, estimate: int | None) -> bool:
    """True without an estimate; else within max(1, 10 %) of it (Muse's estimate is a check, not a count)."""
    return estimate is None or abs(seen - estimate) <= max(1, round(estimate * 0.1))


def _mean_score(found: list[FoundInstance]) -> float:
    return sum(f.score if f.score is not None else 0.5 for f in found) / len(found) if found else 0.0


def choose_answer(answers: list[tuple[str, list[FoundInstance]]], estimate: int | None
                  ) -> tuple[str, list[FoundInstance]] | None:
    """The word and instances to keep, in the order tried on ties; None when every answer is empty."""
    ranked = [(i, w, a) for i, (w, a) in enumerate(answers) if a]
    if not ranked:
        return None
    if estimate is None:
        _, w, a = min(ranked, key=lambda t: (-len(t[2]), -_mean_score(t[2]), t[0]))
    else:
        _, w, a = min(ranked, key=lambda t: (abs(len(t[2]) - estimate), -_mean_score(t[2]), t[0]))
    return w, a


def find_instances(port: Any, cap: Capture, noun: str, deadline_s: float, ctx: CallContext,
                   reasons: list[str], namer: ObjectNamer | None = None) -> list[FoundInstance]:
    """SAM 3.1 instances in two layers (see SAM_GENERIC). A model error on the case's noun propagates as before (the
    look answers by rules). Reasons: ``instances:named:<noun>~<estimate>`` or ``instances:naming:<code>``,
    ``instances:retry:<w1>,<w2>`` (layer 2), ``instances:retry:<word>:<code>``, ``instances:retry:no_time``,
    ``instances:prompt:<word>`` (the kept answer's word, when not the noun) and ``instances:estimate:<seen>/<est>``
    (the kept answer still disagrees with the estimate)."""
    t0 = time.perf_counter()
    words = sam_prompts(noun)
    tried: list[tuple[str, list[FoundInstance]]] = []

    def left() -> float:
        return deadline_s - (time.perf_counter() - t0)

    def sam(word: str) -> list[FoundInstance]:
        return port.find(cap.jpeg, cap.width, cap.height, word, timeout_s=max(0.1, left()), ctx=ctx)

    def collect(futures: list[tuple[str, Any]]) -> None:
        for w, f in futures:
            try:
                tried.append((w, f.result()))
            except ModelError as e:
                reasons.append(f"instances:retry:{w}:{e.code}")

    with ThreadPoolExecutor(max_workers=2 + 2 * MAX_RETRY_WORDS) as pool:
        naming_f = pool.submit(namer.name, cap.jpeg, timeout_s=min(deadline_s, settings.naming_deadline_s()),
                               ctx=ctx) if namer is not None else None
        first_f = pool.submit(sam, words[0])
        try:
            first = first_f.result()
        except ModelError:
            if naming_f is not None:  # its call is recorded either way; the look answers by rules
                naming_f.exception()
            raise
        tried.append((words[0], first))
        generic = words[1:1 + MAX_RETRY_WORDS]
        layer2: list[tuple[str, Any]] = []
        if not first and generic and left() >= MIN_RETRY_S:  # empty: layer 2 starts without waiting for the namer
            reasons.append("instances:retry:" + ",".join(generic))
            layer2 = [(w, pool.submit(sam, w)) for w in generic]
        naming: Naming | None = None
        if naming_f is not None:
            try:
                naming = naming_f.result()
                reasons.append(f"instances:named:{naming.nouns[0]}~"
                               f"{naming.estimate if naming.estimate is not None else '?'}")
            except ModelError as e:
                reasons.append(f"instances:naming:{e.code}")
        estimate = naming.estimate if naming is not None else None
        if first and not estimate_agrees(len(first), estimate) and not layer2 and generic and left() >= MIN_RETRY_S:
            reasons.append("instances:retry:" + ",".join(generic))  # found, but not what Muse sees
            layer2 = [(w, pool.submit(sam, w)) for w in generic]
        collect(layer2)
        best = choose_answer(tried, estimate)
        named = [w for w in (naming.nouns if naming is not None else ()) if w not in {t[0] for t in tried}]
        if named and (best is None or not estimate_agrees(len(best[1]), estimate)):
            if left() >= MIN_RETRY_S:
                named = named[:MAX_RETRY_WORDS]
                reasons.append("instances:retry:" + ",".join(named))
                collect([(w, pool.submit(sam, w)) for w in named])
                best = choose_answer(tried, estimate)
            else:
                reasons.append("instances:retry:no_time")
        elif not first and not layer2 and len(words) > 1:
            reasons.append("instances:retry:no_time")
    if best is None:
        return []
    word, found = best
    if word != words[0]:
        reasons.append(f"instances:prompt:{word}")
    if not estimate_agrees(len(found), estimate):
        reasons.append(f"instances:estimate:{len(found)}/{estimate}")
    return found

def run_look(principal: Principal, target: LookTarget, lc: LookContext, cap: Capture | None, reasons: list[str],
             idempotency_key: str, ports: VisionPorts, today: Callable[[], date], defer: Defer | None, t0: float,
             image_extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Stages a-f on a photo already opened (or None: rules), for a task look or a try look (M5-W01). ``image_extra``
    adds keys to the body's ``image`` (a try look: ``faces_blurred``)."""
    ctx = CallContext(principal.tenant_id, idempotency_key)
    found: list[FoundInstance] | None = None
    if cap is not None:
        if ports.instances is None:
            reasons.append("instances:no_model")
        else:
            try:
                found = order_instances(find_instances(ports.instances, cap, lc.expectation.object_noun,
                                                       settings.instances_deadline_s(), ctx, reasons, ports.namer))
            except ModelError as e:
                reasons.append(f"instances:{ports.instances.model}:{e.code}")
    day = today()
    image = {"capture_id": target.capture_id, "width": cap.width if cap else None,
             "height": cap.height if cap else None, **(image_extra or {})}
    if found and cap is not None and ports.readers:
        return _first_answer(principal, target, idempotency_key, lc, cap, found, ctx, reasons, ports, image, day, t0,
                             defer)
    reads: dict[int, LabelRead] = {}
    answered = False
    if found is not None and cap is not None:
        reads, answered = read_labels(ports.readers, cap, found, lc.expectation, ctx, reasons)
    out = _outcome(cap, found, reads, answered, lc, ctx, reasons, day)
    latency = int((time.perf_counter() - t0) * 1000)
    row = _insert(principal, target, idempotency_key, lc, out.source, image, out.instances, out.raw, out.check.counts,
                  out.check.pack, out.check.expiry, out.check.proposal, out.say, out.models, reasons, out.cost,
                  latency, final=True, due=None, fallback=None)
    row.pop("_replayed", None)
    logger.info("vision_look", look_id=row["look_id"], source=out.source, seen=out.check.counts["seen"],
                calls=len(out.models), latency_ms=latency, final=True)  # never the label text
    return row


def _first_answer(principal: Principal, target: LookTarget, key: str, lc: LookContext, cap: Capture,
                  found: list[FoundInstance], ctx: CallContext, reasons: list[str], ports: VisionPorts,
                  image: dict[str, Any], day: date, t0: float, defer: Defer | None) -> dict[str, Any]:
    """Writes the first answer of a two-step look and starts (or runs) its label read."""
    blank = reconcile([_seen(n, None) for n in range(1, len(found) + 1)], lc.expectation, day)  # every label unread
    counts = {"expected": blank.counts["expected"], "seen": len(found), "damaged": None, "good": None}
    proposal: dict[str, Any] = {"receive": None, "flag": None, "reasons": []}  # nothing proposed before the labels
    say = first_say(len(found), blank.counts["expected"], lc.expectation)
    instances = [_instance_body(n, f, None) for n, f in enumerate(found, start=1)]
    models = [{"model": c.model, "purpose": c.purpose, "latency_ms": c.latency_ms, "cost_usd": float(c.cost_usd),
               "outcome": c.outcome} for c in ctx.calls]
    cost = sum((c.cost_usd for c in ctx.calls), Decimal(0))
    due = datetime.now(UTC) + timedelta(seconds=settings.labels_deadline_s() + settings.fallback_deadline_s()
                                        + LABELS_GRACE_S)
    fallback = {"counts": blank.counts, "pack": blank.pack, "expiry": blank.expiry, "proposal": blank.proposal}
    latency = int((time.perf_counter() - t0) * 1000)
    row = _insert(principal, target, key, lc, "partial", image, instances, {}, counts, None, None, proposal, say, models,
                  list(reasons), cost, latency, final=False, due=due, fallback=fallback)
    logger.info("vision_look", look_id=row["look_id"], source="partial", seen=len(found), calls=len(models),
                latency_ms=latency, final=False)
    if row["final"] or row.get("_replayed"):  # a concurrent create with this key won: its own read is running
        row.pop("_replayed", None)
        return row
    stage = LabelStage(principal, row["look_id"], say, cap, found, lc, ctx, reasons, ports.readers, t0, day)
    if defer is None:
        finish_labels(stage)
        return _read_look(principal, row["look_id"], target.kind)
    defer(lambda: finish_labels(stage))
    return row


def _insert(principal: Principal, target: LookTarget, key: str, lc: LookContext, source: str, image: dict[str, Any],
            instances: list[dict[str, Any]], raw: dict[str, str], counts: dict[str, Any], pack: dict[str, Any] | None,
            expiry: dict[str, Any] | None, proposal: dict[str, Any], say: str, models: list[dict[str, Any]],
            reasons: list[str], cost: Decimal, latency: int, *, final: bool, due: datetime | None,
            fallback: dict[str, Any] | None) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            INSERT INTO field.vision_look (tenant_id, site_id, task_id, line_id, capture_id, "case", object, source,
                   idempotency_key, principal_id, device_id, image, instances, raw_labels, counts, pack, expiry,
                   proposal, say, models, reasons, cost_usd, latency_ms, final, labels_due_at, labels_fallback,
                   kind, photo_uri, photo_sha256, photo_expires_at)
            VALUES (%s, %s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING {LOOK_COLS}
            """,  # noqa: S608 - fixed column list
            (principal.tenant_id, lc.site_id, target.task_id, lc.line_id, target.capture_id, lc.expectation.case,
             lc.expectation.object_noun, source, key, principal.id, principal.device_id, Jsonb(image),
             Jsonb(instances), Jsonb(raw) if raw else None, Jsonb(counts), _jsonb(pack), _jsonb(expiry),
             Jsonb(proposal), say, Jsonb(models), Jsonb(reasons), cost, latency, final, due, _jsonb(fallback),
             target.kind, target.photo_uri, target.photo_sha256, target.photo_expires_at),
        )
        row = cur.fetchone()
        if row:
            return look_body(row)
        out = _existing(cur, key)
    if out is None:  # pragma: no cover - the conflicting row is visible in the same tenant
        raise ERR_LOOK
    return {**out, "_replayed": True}


def _jsonb(v: dict[str, Any] | None) -> Jsonb | None:
    return None if v is None else Jsonb(v)


def get_look(principal: Principal, look_id: str) -> dict[str, Any]:
    """The look as it is now; a label read past its due time is given up first (``final`` true, partial). A try look
    (M5-W01) is not found here: no claim, evidence pack or receipt can use one."""
    return _read_look(principal, look_id, "task")


def _read_look(principal: Principal, look_id: str, kind: str) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        _settle_overdue(cur, "id::text", look_id)
        cur.execute(f"SELECT {LOOK_COLS} FROM field.vision_look WHERE id::text = %s AND kind = %s",  # noqa: S608
                    (look_id, kind))
        row = cur.fetchone()
    if not row:
        raise ERR_LOOK
    return look_body(row)
