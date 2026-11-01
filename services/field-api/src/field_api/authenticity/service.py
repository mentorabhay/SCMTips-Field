"""One C3 check (docs/design/M5_C3_CONTRACT.md section 4): signals, the verdict, the spoken answer, the record.

1. The site: ``site_id`` (in scope), else the capture's site, else the principal's only site (422 otherwise).
2. S1: the seal code verified locally (seal_code.verify) with the maker's public key from the OEM port.
3. S2 + S3: for a valid code only, the maker's registry in one call: the unit's history and the atomic first-check
   claim (``checker`` pseudonymous, oem.checker_ref; ``area`` coarse or none). Unknown unit, a different SKU, an
   unreachable or unconfigured maker each become a registry status, never an HTTP error.
4. The verdict (rules.decide): deterministic, final at once, never changed by step 5.
5. S4 (only with a photo): the visual seal check (seal.run_visual), two steps like M5-S01: the POST answers
   ``final: false`` with the verdict and " Checking the seal."; the check runs in the request's background task and
   sets ``tamper``, the visual reasons, ``say`` and ``say_next`` and ``final``. A check still unfinished at
   ``visual_due_at`` is ended by the next read (``visual:not_finished``). No model configured or the photo unreadable:
   final in one step with the reason.
Replays: the Idempotency-Key middleware answers a repeated POST; a concurrent one with the same key reads the row
that won (UNIQUE (tenant_id, idempotency_key)). Logs never carry the code, the checker id or the area.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from field_oem.ports.oem_port import OemError, OemPort, UnitCheck, UnitNotFound
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.authenticity import rules, seal_code
from field_api.authenticity.oem import checker_ref
from field_api.authenticity.seal import Visual, VisualPorts, models_of, run_visual
from field_api.crops import CropStoreError, crop_store
from field_api.db import principal_tx
from field_api.deps import require_site_scope
from field_api.errors import FieldError
from field_api.vision import settings
from field_api.vision.image import Capture, ImageUnreadable, open_capture
from field_api.vision.ports import CallContext

logger = structlog.get_logger(__name__)

ERR_SITE = FieldError(status=422, code="FIELD-AUT-422-SITE", title="Which site?",
                      detail="Give site_id (or a capture_id): more than one site is in scope.")
ERR_CAPTURE = FieldError(status=404, code="FIELD-AUT-404-CAPTURE", title="Capture not found or out of scope")
ERR_CHECK = FieldError(status=404, code="FIELD-AUT-404-CHECK", title="Check not found or out of scope")
CHECKING_SEAL = " Checking the seal."
SEAL_INTACT = "The seal looks intact."
SEAL_FAILED = "I couldn't check the seal."
VISUAL_GRACE_S = 15.0
COLS = ("id, site_id, principal_id, capture_id, code, verdict, rule, tamper, reasons, signals, say, say_next, final,"
        " models, created_at, visual_due_at")
_NAMES = tuple(c.strip() for c in COLS.split(","))
Defer = Callable[[Callable[[], None]], None]


class CheckIn(BaseModel):
    code: str = Field(min_length=1, max_length=seal_code.MAX_CODE_LEN, description="the QR text of the seal")
    capture_id: str | None = Field(default=None, description="optional photo of the seal (captures API)")
    site_id: str | None = Field(default=None, description="default: the capture's site, else your only site")
    area: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z .'-]{0,59}$",
                             description="coarse, city level at most (no digits); sent to the maker")


def _uuid(v: str | None, err: FieldError) -> str | None:
    if v is None:
        return None
    try:
        return str(uuid.UUID(v))
    except ValueError:
        raise err from None


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def view(row: dict[str, Any], claim_id: str | None) -> dict[str, Any]:
    """The response body of contract section 4.1 from a field.authenticity_check row."""
    cid = str(row["id"])
    return {"check_id": cid, "final": bool(row["final"]), "verdict": row["verdict"], "rule": row["rule"],
            "tamper": row["tamper"], "reasons": list(row["reasons"] or []), "signals": row["signals"],
            "say": row["say"], "say_next": row["say_next"], "models": list(row["models"] or []),
            "evidence_url": f"/v1/authenticity/checks/{cid}/evidence", "claim_id": claim_id,
            "site_id": str(row["site_id"]), "capture_id": str(row["capture_id"]) if row["capture_id"] else None,
            "created_at": _iso(row["created_at"]), "checked_by": row["principal_id"]}


def _claim_id(cur: Any, check_id: str) -> str | None:
    cur.execute("SELECT id FROM field.supplier_claim WHERE check_id = %s::uuid", (check_id,))
    r = cur.fetchone()
    return str(r[0]) if r else None


def _row(cur: Any) -> dict[str, Any] | None:
    r = cur.fetchone()
    return dict(zip(_NAMES, r, strict=True)) if r else None


_GIVE_UP = """
    UPDATE field.authenticity_check
       SET final = true, say_next = %(say_next)s,
           signals = jsonb_set(signals, '{visual,status}', '"failed"'::jsonb),
           reasons = CASE WHEN reasons @> jsonb_build_array(%(reason)s::text) THEN reasons
                          ELSE reasons || jsonb_build_array(%(reason)s::text) END,
           updated_at = NOW()
     WHERE id = %(id)s::uuid AND NOT final
"""


def _settle_overdue(cur: Any, check_id: str) -> None:
    cur.execute("SELECT id FROM field.authenticity_check WHERE id = %s::uuid AND NOT final AND visual_due_at < NOW()",
                (check_id,))
    if cur.fetchone():
        cur.execute(_GIVE_UP, {"say_next": SEAL_FAILED, "reason": "visual:not_finished", "id": check_id})
        logger.info("authenticity_visual_given_up", check_id=check_id)


def read_row(cur: Any, check_id: str) -> dict[str, Any] | None:
    _settle_overdue(cur, check_id)
    cur.execute(f"SELECT {COLS} FROM field.authenticity_check WHERE id = %s::uuid", (check_id,))
    return _row(cur)


def get_check(principal: Principal, check_id: str) -> dict[str, Any]:
    cid = _uuid(check_id, ERR_CHECK)
    assert cid is not None
    with principal_tx(principal) as cur:
        row = read_row(cur, cid)
        if row is None:
            raise ERR_CHECK
        return view(row, _claim_id(cur, cid))


def _existing(cur: Any, key: str) -> dict[str, Any] | None:
    cur.execute("SELECT id FROM field.authenticity_check WHERE idempotency_key = %s", (key,))
    r = cur.fetchone()
    if r is None:
        return None
    row = read_row(cur, str(r[0]))
    return view(row, _claim_id(cur, str(r[0]))) if row else None


@dataclass(frozen=True)
class Place:
    site_id: str
    crop_uri: str | None


def _place(cur: Any, principal: Principal, body: CheckIn) -> Place:
    site = _uuid(body.site_id, ERR_SITE)
    capture = _uuid(body.capture_id, ERR_CAPTURE)
    uri: str | None = None
    if capture:
        cur.execute("SELECT site_id FROM field.capture WHERE id = %s::uuid", (capture,))
        c = cur.fetchone()
        if not c:
            raise ERR_CAPTURE
        if site and str(c[0]) != site:
            raise ERR_CAPTURE
        site = str(c[0])
        cur.execute("SELECT crop_s3_uri, retention_until, is_legal_hold FROM field.capture_evidence"
                    " WHERE capture_id = %s::uuid ORDER BY created_at DESC LIMIT 1", (capture,))
        ev = cur.fetchone()
        uri = str(ev[0]) if ev and (ev[1] >= datetime.now(UTC) or ev[2]) else None
    if site is None:
        own = [s for s in principal.site_ids if s != "*"]
        if len(own) != 1 or "*" in principal.site_ids:
            raise ERR_SITE
        site = own[0]
    require_site_scope(site, principal)
    cur.execute("SELECT 1 FROM field.site WHERE id = %s::uuid", (site,))
    if cur.fetchone() is None:
        raise ERR_SITE
    return Place(site, uri)


def registry_signal(status: str, uc: UnitCheck | None) -> dict[str, Any]:
    events = [{"type": e.type, "at": e.at.isoformat(), "area": e.area} for e in (uc.unit.events if uc else ())]
    h = rules.history_dates([(e.type, e.at) for e in uc.unit.events] if uc else [])
    return {"status": status, "sku": uc.unit.sku if uc else None, "events": events,
            "activated_at": h["activated"].isoformat() if h["activated"] else None,
            "returned_at": h["returned"].isoformat() if h["returned"] else None,
            "refurbished_at": h["refurbished"].isoformat() if h["refurbished"] else None}


def gather(code: str, port: OemPort, tenant_id: str, principal_id: str, area: str | None,
           today: date) -> tuple[seal_code.CodeResult, dict[str, Any], dict[str, Any], rules.Inputs]:
    """S1-S3 and the rule inputs: (code result, registry signal, first-check signal, inputs)."""
    cr = seal_code.verify(code, port)
    if cr.status != "valid" or cr.oem is None or cr.serial is None:
        return (cr, registry_signal("not_asked", None),
                {"status": "not_recorded", "first_checked_at": None, "area": None}, rules.Inputs(cr.status, today=today))
    uc: UnitCheck | None = None
    try:
        uc = port.check_unit(cr.oem, cr.serial, checker_ref(tenant_id, principal_id), area)
        reg = "found" if uc.unit.sku == cr.sku else "sku_mismatch"
    except UnitNotFound:
        reg = "unknown_unit"
    except OemError:
        reg = "unavailable"
    if uc is None:
        return (cr, registry_signal(reg, None), {"status": "not_recorded", "first_checked_at": None, "area": None},
                rules.Inputs(cr.status, registry=reg, today=today))
    fc = uc.first_check
    fstatus = "first" if fc.first else "same_checker" if fc.same_checker else "other_checker"
    # the first checker's area is theirs: another checker learns when, never where
    first = {"status": fstatus, "first_checked_at": fc.at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
             "area": fc.area if fc.same_checker else None}
    inputs = rules.Inputs(cr.status, registry=reg, events=tuple((e.type, e.at) for e in uc.unit.events),
                          first_check=fstatus, first_checked_at=fc.at, today=today)
    return cr, registry_signal(reg, uc), first, inputs


def _visual_pending(capture_id: str | None) -> dict[str, Any]:
    return {"status": "pending", "capture_id": capture_id, "seal_found": None, "box": None, "score": None,
            "signs": [], "image": None}


def _visual_none() -> dict[str, Any]:
    return {"status": "none", "capture_id": None, "seal_found": None, "box": None, "score": None, "signs": [],
            "image": None}


def final_say(verdict: rules.Verdict, visual: Visual | None) -> tuple[str, str | None]:
    """(say, say_next) once the visual check is over (or there is none)."""
    if visual is None:
        return verdict.say, None
    tamper = rules.tamper_of(visual.status, visual.seal_found, visual.signs)
    if tamper:
        sentence = rules.visual_sentence(visual.signs)
        return f"{verdict.say} {sentence}", sentence
    if visual.status == "done" and tamper is False:
        return verdict.say, SEAL_INTACT
    return verdict.say, SEAL_FAILED


def _load(uri: str | None) -> tuple[Capture | None, str | None]:
    if uri is None:
        return None, "visual:image_unavailable"
    try:
        return open_capture(crop_store().get(uri)), None
    except (CropStoreError, OSError):
        return None, "visual:image_unavailable"
    except ImageUnreadable:
        return None, "visual:image_unreadable"


@dataclass(frozen=True)
class VisualStage:
    principal: Principal
    check_id: str
    verdict: rules.Verdict
    cap: Capture
    capture_id: str
    ports: VisualPorts
    ctx: CallContext
    t0: float


def finish_visual(stage: VisualStage) -> None:
    """The visual seal check after the first answer; writes only a check still unfinished."""
    try:
        visual = run_visual(stage.cap, stage.ports, stage.ctx)
        tamper = rules.tamper_of(visual.status, visual.seal_found, visual.signs)
        say, say_next = final_say(stage.verdict, visual)
        models = models_of(stage.ctx)
        cost = sum((c.cost_usd for c in stage.ctx.calls), Decimal(0))
        latency = int((time.perf_counter() - stage.t0) * 1000)
        with principal_tx(stage.principal) as cur:
            cur.execute(
                """
                UPDATE field.authenticity_check
                   SET tamper = %s, signals = jsonb_set(signals, '{visual}', %s), reasons = reasons || %s, say = %s,
                       say_next = %s, models = %s, cost_usd = %s, latency_ms = %s, final = true, updated_at = NOW()
                 WHERE id = %s::uuid AND NOT final
                """,
                (tamper, Jsonb(visual.signal(stage.capture_id, stage.cap)), Jsonb(visual.reasons), say, say_next,
                 Jsonb(models), cost, latency, stage.check_id),
            )
            written = cur.rowcount == 1
        logger.info("authenticity_visual", check_id=stage.check_id, status=visual.status, tamper=tamper,
                    written=written, calls=len(models), latency_ms=latency)
    except Exception:  # the check must end in a definite state whatever failed
        logger.exception("authenticity_visual_failed", check_id=stage.check_id)
        with principal_tx(stage.principal) as cur:
            cur.execute(_GIVE_UP, {"say_next": SEAL_FAILED, "reason": "visual:error", "id": stage.check_id})


def visual_due_s() -> float:
    return 2 * settings.instances_deadline_s() + settings.labels_deadline_s() + VISUAL_GRACE_S


def create_check(principal: Principal, body: CheckIn, key: str, port: OemPort, vports: VisualPorts,
                 defer: Defer | None = None, today: Callable[[], date] = lambda: datetime.now(UTC).date()
                 ) -> dict[str, Any]:
    t0 = time.perf_counter()
    with principal_tx(principal) as cur:
        again = _existing(cur, key)
        if again is not None:
            return again
        place = _place(cur, principal, body)
    cr, registry, first, inputs = gather(body.code, port, principal.tenant_id, principal.id, body.area, today())
    verdict = rules.decide(inputs)
    reasons = list(verdict.reasons)
    capture_id = _uuid(body.capture_id, ERR_CAPTURE)
    cap: Capture | None = None
    visual_signal = _visual_none()
    pending = False
    say, say_next = verdict.say, None
    if capture_id:
        cap, why = _load(place.crop_uri)
        if cap is None or vports.inspector is None:
            reason = why or "visual:no_model"
            reasons.append(reason)
            visual_signal = {**_visual_none(), "status": "failed", "capture_id": capture_id}
            say, say_next = verdict.say, SEAL_FAILED
        else:
            pending = True
            visual_signal = _visual_pending(capture_id)
            say = verdict.say + CHECKING_SEAL
    signals = {"code": cr.signal(), "registry": registry, "first_check": first, "visual": visual_signal}
    due = datetime.now(UTC) + timedelta(seconds=visual_due_s()) if pending else None
    latency = int((time.perf_counter() - t0) * 1000)
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            INSERT INTO field.authenticity_check (tenant_id, site_id, idempotency_key, principal_id, device_id,
                   capture_id, code, oem, serial, sku, verdict, rule, tamper, reasons, signals, say, say_next, final,
                   visual_due_at, models, latency_ms)
            VALUES (%s, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s,
                    '[]'::jsonb, %s)
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING {COLS}
            """,
            (principal.tenant_id, place.site_id, key, principal.id, principal.device_id, capture_id, body.code.strip(),
             cr.oem, cr.serial, cr.sku, verdict.verdict, verdict.rule, Jsonb(reasons), Jsonb(signals), say, say_next,
             not pending, due, latency),
        )
        row = _row(cur)
        if row is None:  # a concurrent POST with this key won: answer with its record
            out = _existing(cur, key)
            if out is None:  # pragma: no cover - the conflicting row is visible in the same tenant
                raise ERR_CHECK
            return out
        out = view(row, None)
    logger.info("authenticity_check", check_id=out["check_id"], verdict=verdict.verdict, rule=verdict.rule,
                code_status=cr.status, registry=registry["status"], first_check=first["status"], pending=pending)
    if pending and cap is not None and capture_id:
        stage = VisualStage(principal, out["check_id"], verdict, cap, capture_id, vports,
                            CallContext(principal.tenant_id, key), t0)
        if defer is None:
            finish_visual(stage)
            return get_check(principal, out["check_id"])
        defer(lambda: finish_visual(stage))
    return out
