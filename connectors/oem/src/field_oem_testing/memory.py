"""An in-memory OemPort for tests (rule 2.4: the test double of the OEM port; never imported by production code).

It holds one SAMPLE maker with a fresh Ed25519 key per instance, signs seal codes in the format of
docs/design/M5_C3_CONTRACT.md section 2.1, and records first checks atomically under a lock. Switches let a test
make the maker unreachable or publish a rotated key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from field_oem.ports.oem_port import (
    FirstCheck,
    OemKey,
    OemKeySet,
    OemUnavailable,
    UnitCheck,
    UnitEvent,
    UnitHistory,
    UnitNotFound,
)

SIGN_DOMAIN = b"scmtips-field/oem-seal/v1\n"
OEM_ID = "kestrel-sample"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical_payload(oem: str, serial: str, sku: str, sealed_at: date, nonce: str, v: int = 1) -> bytes:
    p = {"nonce": nonce, "oem": oem, "serial": serial, "sealed_at": sealed_at.isoformat(), "sku": sku, "v": v}
    return json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def raw_public(key: Ed25519PrivateKey) -> bytes:
    # cast: the installed types-cryptography stubs declare Encoding.Raw / PublicFormat.Raw as str.
    return key.public_key().public_bytes(cast(Encoding, Encoding.Raw), cast(PublicFormat, PublicFormat.Raw))


def kid_of(key: Ed25519PrivateKey) -> str:
    return hashlib.sha256(raw_public(key)).hexdigest()[:16]


def encode(payload: bytes, key: Ed25519PrivateKey, kid: str) -> str:
    return f"SEAL1.{kid}.{b64url(payload)}.{b64url(key.sign(SIGN_DOMAIN + payload))}"


@dataclass
class _Unit:
    sku: str
    sealed_at: date
    nonce: str
    events: list[UnitEvent] = field(default_factory=list)


class MemoryOem:
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.old_keys: list[Ed25519PrivateKey] = []
        self.units: dict[str, _Unit] = {}
        self.first: dict[str, tuple[str, datetime, str | None]] = {}
        self.unreachable = False
        self.key_fetches = 0
        self.checks: list[tuple[str, str, str | None]] = []
        self._lock = threading.Lock()

    @property
    def kid(self) -> str:
        return kid_of(self.key)

    def add_unit(self, serial: str, sku: str = "KSO-BIN-842", sealed_at: date = date(2026, 9, 28),
                 events: list[tuple[str, date]] | None = None) -> str:
        """Registers a unit and returns its genuine seal code."""
        nonce = secrets.token_hex(8)
        self.units[serial] = _Unit(sku, sealed_at, nonce, [UnitEvent(t, d) for t, d in (events or [])])
        return self.code(serial)

    def code(self, serial: str) -> str:
        u = self.units[serial]
        return encode(canonical_payload(OEM_ID, serial, u.sku, u.sealed_at, u.nonce), self.key, self.kid)

    def forged(self, serial: str, sku: str = "KSO-BIN-842", sealed_at: date = date(2026, 9, 28)) -> str:
        """The maker's kid, a well-formed payload, a signature by another key."""
        return encode(canonical_payload(OEM_ID, serial, sku, sealed_at, secrets.token_hex(8)),
                      Ed25519PrivateKey.generate(), self.kid)

    def rotate(self) -> None:
        self.old_keys.append(self.key)
        self.key = Ed25519PrivateKey.generate()

    # -- OemPort
    def knows(self, oem: str) -> bool:
        return oem == OEM_ID

    def keys(self, oem: str, *, refresh: bool = False) -> OemKeySet:
        if self.unreachable:
            raise OemUnavailable("test: unreachable")
        self.key_fetches += 1
        ks = [OemKey(kid_of(k), raw_public(k)) for k in [self.key, *self.old_keys]]
        return OemKeySet(OEM_ID, "Kestrel Optics (SAMPLE)", tuple(ks), sample=True)

    def check_unit(self, oem: str, serial: str, checker: str, area: str | None) -> UnitCheck:
        if self.unreachable:
            raise OemUnavailable("test: unreachable")
        u = self.units.get(serial)
        if u is None:
            raise UnitNotFound(serial)
        with self._lock:
            self.checks.append((serial, checker, area))
            first = serial not in self.first
            if first:
                self.first[serial] = (checker, datetime.now(UTC), area)
            who, at, where = self.first[serial]
        events = tuple(sorted(u.events, key=lambda e: e.at))
        return UnitCheck(UnitHistory(oem, serial, u.sku, events), FirstCheck(first, at, where, who == checker))
