"""HTTP surface of the stand-in core (dev double; M4 contract section 3). Not the SCMTIPS core.

Core paths (shapes from handover 01/01a, the ported ARO client api/Models.kt, and the core's reply TO_FIELD of
31 Oct, which states the real core's behaviour and wins over both where it speaks):
  POST /v1/auth/app/token                     e-mail + password, or pairing_code
  GET  /v1/core/jwks.json                     Ed25519 keys (the stand-in's and fake-core's legacy dev key)
  GET  /v1/core/devices/{device_id}/status?tenant_id=   unknown device or other tenant -> revoked
  POST /v1/wearable/sessions                  ARO pairing: one-time code -> device token (no auth)
  With Authorization: Bearer <wearable token> + X-Device-Id (the wearable-token guard):
  GET  /v1/wearable/next | GET /v1/wearable/sessions (an array) | DELETE /v1/wearable/sessions/{id}
  GET  /v1/briefs/{kind}/{subject_id}?format=spoken|card (kind decision | signal; decision.read)
  POST /v1/briefs/decision/{id}/check (decision.read)
  POST /v1/voice/challenges | POST /v1/voice/commands (Idempotency-Key)
  GET|POST /v1/auth/step-up | POST /v1/evidence/photos (multipart)
  POST /v1/inbound/feeds/{feed_id}            signed webhook feeds (X-SCMTIPS-Timestamp, X-SCMTIPS-Signature),
                                              body {"rows": [...]}; the same body within 10 minutes is 409 duplicate
                                              (by body hash; Idempotency-Key is ignored, as the core does)
Every state-changing route (each POST and DELETE above) answers 403 ``missing_requested_with`` without the header
``X-Requested-With: lr``, as the real core does (TO_FIELD section 3); GET routes do not need it.
Dev-only (no core equivalent; for tests, smoke and the console):
  POST /_standin/pairing-codes | POST /_standin/devices/{id}/revoke | POST /_standin/decisions/reset
  GET  /_standin/feeds/pushes | GET /_standin/feeds/state | GET /_standin/info

Errors are RFC 7807 problem documents with a ``code`` (the ARO client reads ``code``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from fake_core.standin.decisions import APPROVED, PENDING, REJECTED, check_brief, numbers_in, parse
from fake_core.standin.state import (
    CHALLENGE_TTL_S,
    DEFAULT_BACKUP_CODE,
    FEED_DUPLICATE_WINDOW,
    Challenge,
    FeedPush,
    StandInState,
    WearableSession,
)

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
DEVICE_MODEL_RE = re.compile(r"^[A-Z0-9_]{1,40}$")  # the core: free text label, ^[A-Z0-9_]+$, at most 40 (TO_FIELD §3)
DECISION_READ = "decision.read"
SPEAKING_WORDS_PER_S = 2.5
MAX_SKEW_S = 300
MAX_PHOTO_BYTES = 8 * 1024 * 1024
SIGNAL_ID = "5a3e05a0-0000-4000-8000-000000000001"


class ProblemError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        super().__init__(title)
        self.status, self.code, self.title, self.detail = status, code, title, detail


def problem_response(exc: ProblemError) -> JSONResponse:
    body = {"type": "about:blank", "title": exc.title, "status": exc.status, "detail": exc.detail, "code": exc.code}
    return JSONResponse(body, status_code=exc.status, media_type="application/problem+json")


class AppTokenIn(BaseModel):
    email: str | None = Field(None, max_length=254)
    password: str | None = Field(None, max_length=200)
    pairing_code: str | None = Field(None, max_length=32)
    device_id: str
    device_model: str
    display_capable: bool = False
    client: str | None = Field(None, max_length=64)


class PairIn(BaseModel):
    pairing_code: str = Field(min_length=8, max_length=8)
    device_id: str
    device_model: str = Field(min_length=1, max_length=64)
    display_capable: bool = False


def requested_with(x_requested_with: str | None = Header(None)) -> None:
    """The core's check on every state-changing route (TO_FIELD section 3): ``X-Requested-With: lr``."""
    if x_requested_with != "lr":
        raise ProblemError(403, "missing_requested_with", "Forbidden", "header X-Requested-With: lr is required")


class PairingCodeIn(BaseModel):
    email: str


class CheckIn(BaseModel):
    text: str = Field(max_length=4000)


class ChallengeIn(BaseModel):
    decision_id: str


class CommandIn(BaseModel):
    nonce: str = Field(min_length=1, max_length=200)
    transcript: str = Field(max_length=1000)


class StepUpIn(BaseModel):
    method: str
    code: str = Field(max_length=64)


def install(app: FastAPI, state: StandInState, legacy_jwks: Callable[[], list[dict[str, Any]]]) -> None:
    """Mount the stand-in core on ``app`` (fake-core) with its problem handler."""

    async def _problem(_request: Request, exc: Exception) -> Response:
        assert isinstance(exc, ProblemError)
        return problem_response(exc)

    app.add_exception_handler(ProblemError, _problem)
    app.include_router(build_router(state, legacy_jwks))


def build_router(state: StandInState, legacy_jwks: Callable[[], list[dict[str, Any]]]) -> APIRouter:  # noqa: C901
    r = APIRouter(tags=["Stand-in core (dev double)"])

    def now() -> datetime:
        return datetime.now(UTC)

    def jwks() -> dict[str, Any]:
        return {"keys": [state.key.jwk(), *legacy_jwks()]}

    def wearable(authorization: str | None = Header(None), x_device_id: str | None = Header(None)) -> WearableSession:
        """The wearable-token guard: the device token works only with the device id it was issued for."""
        token = (authorization or "").removeprefix("Bearer ").strip()
        s = state.sessions.get(token) if token else None
        if s is None or s.revoked:
            raise ProblemError(401, "unauthorized", "Unauthorized", "unknown or revoked device token")
        if s.expires_at < now():
            raise ProblemError(401, "token_expired", "Unauthorized", "device token expired")
        if x_device_id != s.device_id:
            raise ProblemError(401, "device_mismatch", "Unauthorized", "X-Device-Id does not match the token")
        dev = state.devices.get(s.device_id)
        if dev is None or dev.status != "active":
            raise ProblemError(401, "device_revoked", "Unauthorized", "device revoked")
        dev.last_seen_at = s.last_seen_at = now()
        return s

    # -- sign-in and identity ------------------------------------------------------------------------------
    @r.post("/v1/auth/app/token", dependencies=[Depends(requested_with)])
    def app_token(body: AppTokenIn) -> dict[str, Any]:
        if not DEVICE_ID_RE.match(body.device_id):
            raise ProblemError(422, "invalid_device_id", "Invalid device id", "8-64 chars [A-Za-z0-9._:-]")
        if not DEVICE_MODEL_RE.match(body.device_model):
            raise ProblemError(422, "invalid_device_model", "Invalid device model", "^[A-Z0-9_]+$, at most 40")
        t = now()
        if body.pairing_code:
            user = state.redeem_pairing_code(body.pairing_code, t)
            if user is None:
                raise ProblemError(401, "invalid_credentials", "Invalid credentials", "unknown or expired pairing code")
        else:
            if state.strict:
                raise ProblemError(403, "pairing_required", "Pairing required", "use a pairing code from the web")
            email = (body.email or "").strip().lower()
            if state.too_many_failures(email, t):
                raise ProblemError(429, "too_many_attempts", "Too many attempts", "wait 5 minutes")
            found = state.user_by_email(email)
            if found is None or not hmac.compare_digest((body.password or "").encode(), state.password.encode()):
                state.record_failure(email, t)
                raise ProblemError(401, "invalid_credentials", "Invalid credentials")
            user = found
        session = state.open_session(user, body.device_id, body.device_model, t, body.display_capable)
        ttl = state.token_minutes * 60
        token, claims = state.key.issue({
            "sub": user.id, "tenant_id": state.tenant_id, "roles": list(user.roles), "sites": ["*"],
            "device_id": body.device_id, "device_binding": state.devices[body.device_id].fingerprint,
            "permissions": list(user.permissions), "email": user.email,
        }, ttl)
        return {
            "access_token": token, "token_type": "Bearer", "expires_in": ttl, "claims": claims,
            "wearable": {"session_id": session.session_id, "token": session.token,
                         "expires_at": session.expires_at.isoformat(), "device_id": session.device_id},
            "user": {"id": user.id, "display_name": user.display_name, "email": user.email},
            "capabilities": {"approve_decisions": user.approve_decisions, "field_operator": user.field_operator},
        }

    @r.get("/v1/core/jwks.json")
    def core_jwks() -> dict[str, Any]:
        return jwks()

    @r.get("/v1/core/devices/{device_id}/status")
    def device_status(device_id: str, tenant_id: str = Query(...)) -> dict[str, Any]:
        return state.device_status(device_id, tenant_id)

    @r.post("/v1/wearable/sessions", status_code=201, dependencies=[Depends(requested_with)])
    def pair(body: PairIn) -> dict[str, Any]:
        if not DEVICE_ID_RE.match(body.device_id):
            raise ProblemError(422, "invalid_device_id", "Invalid device id")
        if not DEVICE_MODEL_RE.match(body.device_model):
            raise ProblemError(422, "invalid_device_model", "Invalid device model", "^[A-Z0-9_]+$, at most 40")
        user = state.redeem_pairing_code(body.pairing_code, now())
        if user is None:
            raise ProblemError(401, "invalid_code", "Invalid pairing code")
        s = state.open_session(user, body.device_id, body.device_model, now(), body.display_capable)
        return {"session_id": s.session_id, "token": s.token, "expires_at": s.expires_at.isoformat(),
                "device_id": s.device_id, "user_display_name": user.display_name}

    @r.get("/v1/wearable/sessions")
    def sessions(s: WearableSession = Depends(wearable)) -> list[dict[str, Any]]:
        """The core's shape (TO_FIELD section 3): an array; every field always present, revoked ones included."""
        mine = sorted((x for x in state.sessions.values() if x.user.id == s.user.id), key=lambda x: x.created_at)
        return [{"id": x.session_id, "device_id": x.device_id, "device_model": x.device_model,
                 "display_capable": x.display_capable, "current": x.session_id == s.session_id,
                 "created_at": x.created_at.isoformat(), "expires_at": x.expires_at.isoformat(),
                 "last_seen_at": x.last_seen_at.isoformat() if x.last_seen_at else None,
                 "revoked_at": x.revoked_at.isoformat() if x.revoked_at else None} for x in mine]

    @r.delete("/v1/wearable/sessions/{session_id}", status_code=204, dependencies=[Depends(requested_with)])
    def revoke_session(session_id: str, s: WearableSession = Depends(wearable)) -> Response:
        target = next((x for x in state.sessions.values() if x.session_id == session_id and x.user.id == s.user.id),
                      None)
        if target is None:
            raise ProblemError(404, "not_found", "Session not found")
        target.revoke(now())
        return Response(status_code=204)

    # -- decisions and briefs ------------------------------------------------------------------------------
    def approver(s: WearableSession) -> None:
        if "voice.approve" not in s.user.permissions:
            raise ProblemError(403, "forbidden", "Forbidden", "voice.approve is required")

    @r.get("/v1/wearable/next")
    def next_item(s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        if "voice.approve" not in s.user.permissions:
            return {"item": None}
        waiting = state.waiting()
        return {"item": waiting[0].next_item(len(waiting)) if waiting else None}

    def can_read_decisions(s: WearableSession) -> None:
        if DECISION_READ not in s.user.permissions:
            raise ProblemError(403, "forbidden", "Forbidden", f"{DECISION_READ} is required")

    @r.get("/v1/briefs/{kind}/{subject_id}")
    def brief(kind: str, subject_id: str, format: str = Query("spoken"),
              s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        """The core's brief document (TO_FIELD section 3): {kind, subject_id, format, text, template_text, source,
        facts{}, check{}, characters, words, seconds, simulated}. The stand-in serves templates only (source
        "template"); what facts{} and check{} hold inside is the stand-in's choice (the core gave only the keys)."""
        can_read_decisions(s)
        if format not in ("spoken", "card"):
            raise ProblemError(422, "invalid_format", "format is spoken or card")
        if kind == "decision":
            d = state.decision(subject_id)
            if d is None:
                raise ProblemError(404, "not_found", "Decision not found")
            text = d.spoken if format == "spoken" else d.card
            facts: dict[str, Any] = {"title": d.title, "status": d.status, "deadline_at": d.deadline_at.isoformat(),
                                     "band": {"label": d.band_label, "step_up": d.step_up},
                                     "options": [{"letter": o.letter, "option_id": o.option_id, "title": o.title,
                                                  "committed": o.committed} for o in d.options]}
            check_route = f"/v1/briefs/decision/{d.decision_id}/check"
        elif kind == "signal" and subject_id == SIGNAL_ID:
            text = ("Sample signal. New export curbs on rare-earth magnets take effect in 9 days; "
                    "RM-307 at PLANT-GOA is exposed.")
            facts = {"title": "SAMPLE: rare-earth magnet export curbs", "item_code": "RM-307",
                     "location_code": "PLANT-GOA"}
            check_route = ""
        else:
            raise ProblemError(404, "not_found", "Brief not found")
        words = len(text.split())
        return {"kind": kind, "subject_id": subject_id, "format": format, "text": text, "template_text": text,
                "source": "template", "facts": facts,
                "check": {"numbers": sorted(numbers_in(text)), "route": check_route},
                "characters": len(text), "words": words, "seconds": round(words / SPEAKING_WORDS_PER_S, 1),
                "simulated": True}

    @r.post("/v1/briefs/decision/{decision_id}/check", dependencies=[Depends(requested_with)])
    def check(decision_id: str, body: CheckIn, s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        can_read_decisions(s)
        d = state.decision(decision_id)
        if d is None:
            raise ProblemError(404, "not_found", "Decision not found")
        accepted, reasons = check_brief(body.text, d.spoken)
        return {"accepted": accepted, "reasons": reasons, "template_text": d.spoken}

    # -- voice ---------------------------------------------------------------------------------------------
    def challenge_body(c: Challenge, s: WearableSession) -> dict[str, Any]:
        d = state.decision(c.decision_id)
        assert d is not None
        return {"nonce": c.nonce, "expires_at": c.expires_at.isoformat(), "ttl_seconds": CHALLENGE_TTL_S,
                "turn": c.turn, "decision_id": d.decision_id, "status": d.status, "title": d.title, "brief": d.spoken,
                "options": d.challenge_options(), "step_up_fresh": s.step_up_fresh(now()), "step_up_waived": False,
                "confidence_floor": 0.6}

    @r.post("/v1/voice/challenges", status_code=201, dependencies=[Depends(requested_with)])
    def new_challenge(body: ChallengeIn, s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        approver(s)
        d = state.decision(body.decision_id)
        if d is None:
            raise ProblemError(404, "not_found", "Decision not found")
        if d.status != PENDING:
            raise ProblemError(409, "voice_not_actionable", "Conflict",
                               f"A {d.status} decision cannot be reviewed by voice; only one waiting for approval.")
        return challenge_body(state.new_challenge(s, d.decision_id, 1, None, now()), s)

    @r.post("/v1/voice/commands", dependencies=[Depends(requested_with)])
    def command(body: CommandIn, s: WearableSession = Depends(wearable),
                idempotency_key: str | None = Header(None)) -> dict[str, Any]:
        approver(s)
        if idempotency_key and (s.session_id, idempotency_key) in state.replies:
            return state.replies[(s.session_id, idempotency_key)]
        c = state.challenges.get(body.nonce)
        # the core's answers (lr_api.domain.voice.service.check_challenge): unknown or another session's 404,
        # used 409, expired 410
        if c is None or c.session_id != s.session_id:
            raise ProblemError(404, "voice_challenge_unknown", "Not Found", "Unknown voice challenge; start again.")
        if c.used:
            raise ProblemError(409, "voice_nonce_replayed", "Conflict", "This voice challenge was already used.")
        if c.expires_at <= now():
            raise ProblemError(410, "voice_challenge_expired", "Gone", "The voice challenge expired; start again.")
        c.used = True  # single use
        d = state.decision(c.decision_id)
        assert d is not None
        if d.status != PENDING:
            raise ProblemError(409, "voice_not_actionable", "Conflict",
                               f"A {d.status} decision cannot be reviewed by voice; only one waiting for approval.")
        out = _turn(state, s, c, body.transcript, now())
        if idempotency_key:
            state.replies[(s.session_id, idempotency_key)] = out
        return out

    # -- step-up -------------------------------------------------------------------------------------------
    def step_up_status(s: WearableSession) -> dict[str, Any]:
        fresh = s.step_up_fresh(now())
        return {"fresh": fresh, "method": s.step_up_method if fresh else None,
                "verified_at": s.step_up_at.isoformat() if fresh and s.step_up_at else None, "waived": False}

    @r.get("/v1/auth/step-up")
    def get_step_up(s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        return step_up_status(s)

    @r.post("/v1/auth/step-up", dependencies=[Depends(requested_with)])
    def post_step_up(body: StepUpIn, s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        if body.method not in ("totp", "backup_code"):
            raise ProblemError(422, "invalid_method", "Invalid step-up method")
        want = state.step_up_code if body.method == "totp" else DEFAULT_BACKUP_CODE
        if not hmac.compare_digest(body.code.strip().upper().encode(), want.upper().encode()):
            raise ProblemError(401, "invalid_code", "Invalid code")
        s.step_up_at, s.step_up_method = now(), body.method
        return step_up_status(s)

    # -- evidence ------------------------------------------------------------------------------------------
    @r.post("/v1/evidence/photos", status_code=201, dependencies=[Depends(requested_with)])
    async def photo(request: Request, s: WearableSession = Depends(wearable)) -> dict[str, Any]:
        form = await request.form()
        image = form.get("image")
        if image is None or isinstance(image, str):
            raise ProblemError(422, "image_required", "An image file is required")
        data = await image.read()
        ctype = image.content_type or ""
        if ctype not in ("image/jpeg", "image/png") or not data or len(data) > MAX_PHOTO_BYTES:
            raise ProblemError(422, "invalid_image", "Photo must be a JPEG or PNG of at most 8 MB")
        kind, subject, label = str(form.get("subject_kind") or ""), str(form.get("subject_id") or ""), str(
            form.get("label") or "")
        if kind not in ("recovery_plan", "action") or not subject or not 1 <= len(label) <= 120:
            raise ProblemError(422, "invalid_fields", "subject_kind, subject_id and label (1-120) are required")
        if str(form.get("consent") or "") != "true":
            raise ProblemError(422, "consent_required", "Consent is required")
        prompt = str(form.get("segment_prompt") or "")
        if len(prompt) > 80:
            raise ProblemError(422, "invalid_fields", "segment_prompt is at most 80 characters")
        rec = {"id": str(uuid.uuid4()), "subject_kind": kind, "subject_id": subject, "label": label,
               "faces_blurred": False, "mask": False, "created_at": now().isoformat()}
        # The stand-in keeps only metadata and a digest, never the image bytes.
        state.evidence.append({**rec, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                               "user_id": s.user.id})
        return rec

    # -- signed feeds --------------------------------------------------------------------------------------
    @r.post("/v1/inbound/feeds/{feed_id}", dependencies=[Depends(requested_with)])
    async def feed(feed_id: str, request: Request, x_scmtips_timestamp: str | None = Header(None),
                   x_scmtips_signature: str | None = Header(None),
                   idempotency_key: str | None = Header(None)) -> dict[str, Any]:
        entry = state.feeds.get(feed_id)
        if entry is None:
            raise ProblemError(404, "unknown_feed", "Feed not found")
        kind, secret = entry
        raw = await request.body()
        try:
            ts = int(x_scmtips_timestamp or "")
        except ValueError:
            raise ProblemError(401, "bad_timestamp", "Missing or invalid X-SCMTIPS-Timestamp") from None
        if abs(time.time() - ts) > MAX_SKEW_S:
            raise ProblemError(401, "stale_timestamp", "Timestamp outside 5 minutes")
        want = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest((x_scmtips_signature or "").encode(), want.encode()):
            raise ProblemError(401, "bad_signature", "Signature does not match")
        try:
            doc = json.loads(raw)
        except ValueError:
            raise ProblemError(422, "invalid_json", "Body is not JSON") from None
        if not isinstance(doc, dict) or "rows" not in doc:
            raise ProblemError(422, "invalid_body", "Body must be {\"rows\": [...]}")
        rows = doc["rows"]
        errors = validate_rows(kind, rows)
        if errors:
            raise ProblemError(422, "invalid_rows", "Rows rejected", "; ".join(errors[:10]))
        digest = hashlib.sha256(raw).hexdigest()
        t = now()
        # The core dedupes by body hash within 10 minutes and ignores Idempotency-Key (TO_FIELD section 4).
        dup = any(p.feed_id == feed_id and p.body_sha256 == digest and not p.duplicate
                  and t - datetime.fromisoformat(p.received_at) <= FEED_DUPLICATE_WINDOW for p in state.pushes)
        state.pushes.append(FeedPush(feed_id, kind, t.isoformat(), ts, digest, rows, dup, idempotency_key))
        if dup:
            raise ProblemError(409, "duplicate", "Duplicate push", "the same body was received within 10 minutes")
        for row in rows:  # upsert mode: only the rows sent change; an open-supply line is (kind, ref, item_code)
            if kind == "inventory":
                state.inventory[(row["item_code"].upper(), row["location_code"].upper())] = row
            else:
                state.open_supply[(row["kind"].upper(), row["ref"], row["item_code"].upper())] = row
        return {"accepted": True, "rows": len(rows), "duplicate": False}

    # -- dev-only helpers ----------------------------------------------------------------------------------
    @r.post("/_standin/pairing-codes", status_code=201)
    def pairing_code(body: PairingCodeIn) -> dict[str, Any]:
        if state.user_by_email(body.email) is None:
            raise ProblemError(404, "unknown_user", "No such demo user")
        code, exp = state.new_pairing_code(body.email.strip().lower(), now())
        return {"pairing_code": code, "expires_at": exp.isoformat()}

    @r.post("/_standin/devices/{device_id}/revoke")
    def dev_revoke(device_id: str) -> dict[str, Any]:
        if not state.revoke_device(device_id):
            raise ProblemError(404, "not_found", "Device not found")
        return {"device_id": device_id, "status": "revoked"}

    @r.post("/_standin/decisions/reset")
    def reset_decisions() -> dict[str, Any]:
        state.reset_decisions()
        return {"open": len(state.waiting())}

    @r.get("/_standin/feeds/pushes")
    def pushes(feed_id: str | None = None, since: str | None = None) -> dict[str, Any]:
        items = [p for p in state.pushes if (feed_id is None or p.feed_id == feed_id)
                 and (since is None or p.received_at >= since)]
        return {"items": [{"feed_id": p.feed_id, "kind": p.kind, "received_at": p.received_at,
                           "timestamp": p.timestamp, "body_sha256": p.body_sha256, "rows": p.rows,
                           "duplicate": p.duplicate, "idempotency_key": p.idempotency_key,
                           "signature": "verified"} for p in items]}

    @r.get("/_standin/feeds/state")
    def feed_state() -> dict[str, Any]:
        return {"inventory": list(state.inventory.values()), "open_supply": list(state.open_supply.values())}

    @r.get("/_standin/info")
    def info() -> dict[str, Any]:
        return {"what": "stand-in core (dev double of the SCMTIPS core contract), not the SCMTIPS core",
                "tenant_id": state.tenant_id, "kid": state.key.kid,
                "users": [{"email": u.email, "display_name": u.display_name, "capabilities": {
                    "approve_decisions": u.approve_decisions, "field_operator": u.field_operator}} for u in state.users],
                "feeds": {fid: kind for fid, (kind, _secret) in state.feeds.items()}}

    return r


INVENTORY_REQUIRED = ("item_code", "location_code", "as_of", "on_hand_qty")
SUPPLY_REQUIRED = ("kind", "ref", "item_code", "location_code", "qty", "due_date")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/#&+()-]{0,63}$")


def validate_rows(kind: str, rows: Any) -> list[str]:
    """The erp_extract table rules of the exchange contract (inventory / open_supply) the feeds apply."""
    if not isinstance(rows, list) or not rows:
        return ["rows must be a non-empty JSON array"]
    req = INVENTORY_REQUIRED if kind == "inventory" else SUPPLY_REQUIRED
    errs: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errs.append(f"row {i}: not an object")
            continue
        errs += [f"row {i}: {k} is required" for k in req if row.get(k) in (None, "")]
        for k in ("item_code", "location_code"):
            if row.get(k) is not None and not _CODE.match(str(row[k])):
                errs.append(f"row {i}: {k} is not a code")
        for k in ("as_of", "due_date"):
            if k in req and row.get(k) is not None and not _DATE.match(str(row[k])):
                errs.append(f"row {i}: {k} is not YYYY-MM-DD")
        for k in ("on_hand_qty", "qty", "allocated_qty", "in_transit_qty"):
            v = row.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int | float) or v < 0):
                errs.append(f"row {i}: {k} must be a number >= 0")
    return errs


def _say_options(state: StandInState, decision_id: str) -> str:
    d = state.decision(decision_id)
    assert d is not None
    return " or ".join(o.letter for o in d.options)


def _turn(state: StandInState, s: WearableSession, c: Challenge, transcript: str, t: datetime) -> dict[str, Any]:  # noqa: C901
    """One voice turn. Approve and reject are read back and run only on a later "confirm" (the confirm turn)."""
    d = state.decision(c.decision_id)
    assert d is not None
    p = parse(transcript)
    pending = c.pending
    step_up_needed = d.step_up and not s.step_up_fresh(t)

    def reply(outcome: str, say: str, nxt_pending: dict[str, Any] | None, more: bool = True,
              **extra: Any) -> dict[str, Any]:
        nxt = state.new_challenge(s, d.decision_id, c.turn + 1, nxt_pending, t) if more else None
        return {"outcome": outcome, "say": say, "pending": nxt_pending,
                "step_up_required": bool(nxt_pending and nxt_pending.get("intent") == "approve") and step_up_needed,
                "next": {"nonce": nxt.nonce, "expires_at": nxt.expires_at.isoformat(), "turn": nxt.turn} if nxt else None,
                "decision": {"id": d.decision_id, "status": d.status, "version": d.version},
                "approval_id": None, "parsed": p.wire(), **extra}

    if p.intent == "approve":
        opt = d.option(p.letter or "")
        if opt is None:
            return reply("clarify", f"There is no option {p.letter}. Say approve option {_say_options(state, d.decision_id)}.",
                         pending)
        say = f"You chose option {opt.letter}, {opt.title}, {opt.committed}. Say confirm to approve, or cancel."
        # the core's PendingOut: intent, option_id, letter, reason, review_at, readback
        want: dict[str, Any] = {"intent": "approve", "option_id": opt.option_id, "letter": opt.letter, "reason": None,
                                "review_at": None, "readback": say}
        return reply("readback", say, want)
    if p.intent == "reject":
        say = "You are rejecting this decision. Say confirm to reject, or cancel."
        return reply("readback", say, {"intent": "reject", "option_id": None, "letter": None, "reason": p.reason,
                                       "review_at": None, "readback": say})
    if p.intent == "confirm":
        if not pending:
            return reply("clarify", f"Nothing to confirm yet. Say approve option {_say_options(state, d.decision_id)}, "
                                    "or reject.", None)
        if step_up_needed and pending["intent"] == "approve":
            return reply("readback", "This approval needs your phone verification first. Enter the code on your phone,"
                                     " then say confirm.", pending)
        d.version += 1
        approval_id = str(uuid.uuid4())
        if pending["intent"] == "approve":
            d.status, d.chosen = APPROVED, str(pending["letter"])
            opt = d.option(d.chosen)
            say = f"Approved: option {d.chosen}, {opt.title if opt else ''}. The recovery is on its way."
        else:
            d.status = REJECTED
            say = "Rejected. The decision goes back to the planners."
        d.approvals.append({"approval_id": approval_id, "user_id": s.user.id, "intent": pending["intent"],
                            "option": pending.get("letter"), "reason": pending.get("reason"), "at": t.isoformat()})
        out = reply("executed", say, None, more=False)
        out["approval_id"] = approval_id
        return out
    if p.intent == "cancel":
        return reply("cancelled", "Cancelled. Nothing was changed.", None)  # the core issues the next turn
    if p.intent == "repeat":
        return reply("repeat", d.spoken, pending)
    if p.intent == "details":
        opts = [d.option(p.letter)] if p.letter and d.option(p.letter) else list(d.options)
        say = " ".join(f"Option {o.letter}: {o.details}" for o in opts if o)
        return reply("details", say, pending)
    return reply("clarify", f"Sorry, I did not get that. Say approve option {_say_options(state, d.decision_id)}, "
                            "reject, or repeat.", pending)
