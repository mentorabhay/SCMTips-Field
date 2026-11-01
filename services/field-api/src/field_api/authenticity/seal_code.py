"""Seal code parsing and signature verification in field-api (docs/design/M5_C3_CONTRACT.md section 2.1).

``SEAL1.<kid>.<payload_b64url>.<signature_b64url>``; the signature is Ed25519 over SIGN_DOMAIN + the payload bytes;
the payload is the canonical JSON of {v, oem, serial, sku, sealed_at, nonce}. Verification is local (the maker's
public key comes through the OEM port, cached by its adapter); a model never takes part.

``verify(code, port)`` returns a ``CodeResult`` whose ``status`` is one of
not_a_seal_code | unknown_oem | oem_not_configured | oem_unavailable | unknown_key | bad_signature | bad_payload |
valid, in the order of the contract: structure, payload JSON, maker known, maker's keys, kid (one forced refetch for
key rotation), signature over the exact bytes, then the canonical form and every field's pattern.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from field_oem.ports.oem_port import OemKeySet, OemNotConfigured, OemPort, OemUnavailable

PREFIX = "SEAL1"
SIGN_DOMAIN = b"scmtips-field/oem-seal/v1\n"
MAX_CODE_LEN = 1024
KID_RE = re.compile(r"^[0-9a-f]{16}$")
B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
FIELDS = frozenset({"v", "oem", "serial", "sku", "sealed_at", "nonce"})
PATTERNS = MappingProxyType({"oem": re.compile(r"^[a-z0-9-]{3,40}$"), "serial": re.compile(r"^[A-Z0-9-]{4,40}$"),
            "sku": re.compile(r"^[A-Z0-9-]{2,40}$"), "nonce": re.compile(r"^[0-9a-f]{16}$"),
            "sealed_at": re.compile(r"^\d{4}-\d{2}-\d{2}$")})
STATUSES = ("valid", "not_a_seal_code", "bad_payload", "unknown_oem", "unknown_key", "bad_signature",
            "oem_unavailable", "oem_not_configured")


@dataclass(frozen=True)
class CodeResult:
    status: str
    kid: str | None = None
    oem: str | None = None
    oem_name: str | None = None
    serial: str | None = None
    sku: str | None = None
    sealed_at: str | None = None

    def signal(self) -> dict[str, Any]:
        return {"status": self.status, "oem": self.oem, "oem_name": self.oem_name, "kid": self.kid,
                "serial": self.serial, "sku": self.sku, "sealed_at": self.sealed_at}


@dataclass(frozen=True)
class Parsed:
    kid: str
    payload: bytes
    signature: bytes
    fields: dict[str, Any]


def _unb64(text: str) -> bytes:
    if not B64_RE.match(text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(fields: dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def parse(code: str) -> Parsed | None:
    """The code's parts, or None when it is not a seal code at all (wrong shape, base64, JSON or not an object)."""
    code = code.strip()
    if not code or len(code) > MAX_CODE_LEN:
        return None
    parts = code.split(".")
    if len(parts) != 4 or parts[0] != PREFIX or not KID_RE.match(parts[1]):
        return None
    try:
        payload, sig = _unb64(parts[2]), _unb64(parts[3])
        fields = json.loads(payload.decode("ascii"))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if len(sig) != 64 or not isinstance(fields, dict):
        return None
    return Parsed(parts[1], payload, sig, fields)


def fields_ok(fields: dict[str, Any], payload: bytes) -> bool:
    if set(fields) != FIELDS or fields.get("v") != 1 or isinstance(fields.get("v"), bool):
        return False
    for k, rx in PATTERNS.items():
        if not isinstance(fields.get(k), str) or not rx.match(fields[k]):
            return False
    try:
        date.fromisoformat(fields["sealed_at"])
    except ValueError:
        return False
    return canonical(fields) == payload


def _signed(keyset: OemKeySet, p: Parsed) -> bool | None:
    """True / False for the signature with the key of ``p.kid``; None when the key set has no such kid."""
    key = keyset.find(p.kid)
    if key is None:
        return None
    try:
        Ed25519PublicKey.from_public_bytes(key.public).verify(p.signature, SIGN_DOMAIN + p.payload)
    except (InvalidSignature, ValueError):
        return False
    return True


def verify(code: str, port: OemPort) -> CodeResult:
    p = parse(code)
    if p is None:
        return CodeResult("not_a_seal_code")
    oem = p.fields.get("oem") if isinstance(p.fields.get("oem"), str) else None
    if oem is None or not PATTERNS["oem"].match(oem) or not port.knows(oem):
        return CodeResult("unknown_oem", kid=p.kid, oem=oem if oem and PATTERNS["oem"].match(oem) else None)
    try:
        keyset = port.keys(oem)
        ok = _signed(keyset, p)
        if ok is None:  # a rotated key: fetch once more before calling the kid unknown
            keyset = port.keys(oem, refresh=True)
            ok = _signed(keyset, p)
    except OemNotConfigured:
        return CodeResult("oem_not_configured", kid=p.kid, oem=oem)
    except OemUnavailable:
        return CodeResult("oem_unavailable", kid=p.kid, oem=oem)
    base = {"kid": p.kid, "oem": oem, "oem_name": keyset.name or None}
    if ok is None:
        return CodeResult("unknown_key", **base)
    if not ok:
        return CodeResult("bad_signature", **base)
    if not fields_ok(p.fields, p.payload):
        return CodeResult("bad_payload", **base)
    f = p.fields
    return CodeResult("valid", serial=f["serial"], sku=f["sku"], sealed_at=f["sealed_at"], **base)
