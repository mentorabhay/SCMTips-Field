"""In-process state of the stand-in core (dev double): demo users, devices, wearable sessions, challenges, feeds.

Configuration (environment, names only; dev values):
- FAKE_CORE_TENANT_ID: the tenant of every demo user (the dev stack passes the field demo tenant).
- FAKE_CORE_DEMO_PASSWORD: the demo users' password; default DEFAULT_DEMO_PASSWORD (printed by `stack up`).
- FAKE_CORE_STEP_UP_CODE: the phone step-up code (TOTP stand-in), default DEFAULT_STEP_UP_CODE.
- FAKE_CORE_STRICT_SIGN_IN=1: e-mail + password answers 403 pairing_required (the core's strict sign-in).
- FAKE_CORE_TOKEN_MINUTES: core token lifetime, default 60 (the core's LR_CORE_TOKEN_MINUTES).
- FAKE_CORE_INVENTORY_FEED_ID / FAKE_CORE_SUPPLY_FEED_ID: feed ids, default standin-inventory / standin-open-supply.
- FIELD_CORE_INVENTORY_FEED_SECRET / FIELD_CORE_SUPPLY_FEED_SECRET: the feeds' HMAC secrets (the real core shows
  each once when the feed is made; here both sides read the same .env.local).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fake_core.standin.decisions import Decision, sample_decisions
from fake_core.standin.keys import CoreKey

DEFAULT_TENANT_ID = "5a3e7e00-0000-4000-8000-000000000001"
DEFAULT_DEMO_PASSWORD = "field-demo-2026"
DEFAULT_STEP_UP_CODE = "246810"
DEFAULT_BACKUP_CODE = "SMPL-0001"
INVENTORY_FEED_DEFAULT = "standin-inventory"
SUPPLY_FEED_DEFAULT = "standin-open-supply"
WEARABLE_TTL = timedelta(hours=12)
STEP_UP_FRESH = timedelta(minutes=5)
CHALLENGE_TTL_S = 120
PAIRING_TTL = timedelta(minutes=10)
MAX_FAILED_SIGN_INS = 5
FAILED_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class DemoUser:
    id: str
    email: str
    display_name: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    approve_decisions: bool
    field_operator: bool


DEMO_USERS = (
    DemoUser("5a3e0a00-0000-4000-8000-000000000001", "approver@demo.scmtips.test",
             "SAMPLE Approver", ("field.supervisor",), ("voice.approve", "decisions.read", "evidence.upload"),
             approve_decisions=True, field_operator=False),
    DemoUser("5a3e0a00-0000-4000-8000-000000000002", "operator@demo.scmtips.test", "SAMPLE Operator",
             ("field.operator",), ("field.operate", "evidence.upload"), approve_decisions=False, field_operator=True),
)


@dataclass
class Device:
    device_id: str
    tenant_id: str
    user_id: str
    model: str
    status: str = "active"
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def fingerprint(self) -> str:
        return "fp_" + hashlib.sha256(f"{self.tenant_id}:{self.device_id}".encode()).hexdigest()[:16]


@dataclass
class WearableSession:
    session_id: str
    token: str
    user: DemoUser
    tenant_id: str
    device_id: str
    device_model: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False
    step_up_at: datetime | None = None
    step_up_method: str | None = None

    def step_up_fresh(self, now: datetime) -> bool:
        return self.step_up_at is not None and now - self.step_up_at <= STEP_UP_FRESH


@dataclass
class Challenge:
    nonce: str
    session_id: str
    decision_id: str
    turn: int
    expires_at: datetime
    pending: dict[str, Any] | None = None
    used: bool = False


@dataclass
class FeedPush:
    feed_id: str
    kind: str  # inventory | open_supply
    received_at: str
    timestamp: int
    body_sha256: str
    rows: list[dict[str, Any]]
    duplicate: bool
    idempotency_key: str | None


@dataclass
class StandInState:
    tenant_id: str
    password: str
    step_up_code: str
    strict: bool
    token_minutes: int
    feeds: dict[str, tuple[str, str]]  # feed_id -> (kind, secret)
    key: CoreKey = field(default_factory=CoreKey)
    users: tuple[DemoUser, ...] = DEMO_USERS
    devices: dict[str, Device] = field(default_factory=dict)
    sessions: dict[str, WearableSession] = field(default_factory=dict)  # by token
    pairing_codes: dict[str, tuple[str, datetime]] = field(default_factory=dict)  # code -> (email, expires)
    failed: dict[str, list[datetime]] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=sample_decisions)
    challenges: dict[str, Challenge] = field(default_factory=dict)
    replies: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)  # (session, Idempotency-Key)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    pushes: list[FeedPush] = field(default_factory=list)
    inventory: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)  # upsert view
    open_supply: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> StandInState:
        feeds: dict[str, tuple[str, str]] = {}
        for kind, id_var, default_id, secret_var in (
            ("inventory", "FAKE_CORE_INVENTORY_FEED_ID", INVENTORY_FEED_DEFAULT, "FIELD_CORE_INVENTORY_FEED_SECRET"),
            ("open_supply", "FAKE_CORE_SUPPLY_FEED_ID", SUPPLY_FEED_DEFAULT, "FIELD_CORE_SUPPLY_FEED_SECRET"),
        ):
            # Without a configured secret the feed still exists with a random one: every push is refused.
            feeds[os.getenv(id_var) or default_id] = (kind, os.getenv(secret_var) or secrets.token_hex(32))
        return cls(
            tenant_id=os.getenv("FAKE_CORE_TENANT_ID") or DEFAULT_TENANT_ID,
            password=os.getenv("FAKE_CORE_DEMO_PASSWORD") or DEFAULT_DEMO_PASSWORD,
            step_up_code=os.getenv("FAKE_CORE_STEP_UP_CODE") or DEFAULT_STEP_UP_CODE,
            strict=os.getenv("FAKE_CORE_STRICT_SIGN_IN", "") in ("1", "true", "yes"),
            token_minutes=int(os.getenv("FAKE_CORE_TOKEN_MINUTES") or "60"),
            feeds=feeds,
        )

    # -- users and sign-in ---------------------------------------------------------------------------------
    def user_by_email(self, email: str) -> DemoUser | None:
        return next((u for u in self.users if u.email == email.strip().lower()), None)

    def too_many_failures(self, email: str, now: datetime) -> bool:
        recent = [t for t in self.failed.get(email, []) if now - t <= FAILED_WINDOW]
        self.failed[email] = recent
        return len(recent) >= MAX_FAILED_SIGN_INS

    def record_failure(self, email: str, now: datetime) -> None:
        self.failed.setdefault(email, []).append(now)

    def new_pairing_code(self, email: str, now: datetime) -> tuple[str, datetime]:
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        self.pairing_codes[code] = (email, now + PAIRING_TTL)
        return code, now + PAIRING_TTL

    def redeem_pairing_code(self, code: str, now: datetime) -> DemoUser | None:
        entry = self.pairing_codes.pop(code.strip().upper(), None)
        if entry is None or entry[1] < now:
            return None
        return self.user_by_email(entry[0])

    def open_session(self, user: DemoUser, device_id: str, device_model: str, now: datetime) -> WearableSession:
        dev = self.devices.get(device_id)
        if dev is None or dev.tenant_id != self.tenant_id:
            dev = Device(device_id, self.tenant_id, user.id, device_model)
            self.devices[device_id] = dev
        dev.last_seen_at = now
        s = WearableSession(str(uuid.uuid4()), "scmw_" + secrets.token_urlsafe(32), user, self.tenant_id, device_id,
                            device_model, now, now + WEARABLE_TTL)
        self.sessions[s.token] = s
        return s

    def device_status(self, device_id: str, tenant_id: str) -> dict[str, Any]:
        dev = self.devices.get(device_id)
        if dev is None or dev.tenant_id != tenant_id or dev.status != "active":
            return {"device_id": device_id, "status": "revoked", "fingerprint": None, "last_seen_at": None}
        return {"device_id": device_id, "status": "active", "fingerprint": dev.fingerprint,
                "last_seen_at": dev.last_seen_at.isoformat()}

    def revoke_device(self, device_id: str) -> bool:
        dev = self.devices.get(device_id)
        if dev is None:
            return False
        dev.status = "revoked"
        for s in self.sessions.values():
            if s.device_id == device_id:
                s.revoked = True
        return True

    # -- decisions -----------------------------------------------------------------------------------------
    def decision(self, decision_id: str) -> Decision | None:
        return next((d for d in self.decisions if d.decision_id == decision_id), None)

    def waiting(self) -> list[Decision]:
        return sorted((d for d in self.decisions if d.status == "open"), key=lambda d: d.created_at)

    def reset_decisions(self) -> None:
        self.decisions = sample_decisions()
        self.challenges.clear()
        self.replies.clear()

    def new_challenge(self, session: WearableSession, decision_id: str, turn: int,
                      pending: dict[str, Any] | None, now: datetime) -> Challenge:
        c = Challenge(secrets.token_urlsafe(18), session.session_id, decision_id, turn,
                      now + timedelta(seconds=CHALLENGE_TTL_S), pending)
        self.challenges[c.nonce] = c
        return c
