"""The SAMPLE maker's signing key and the seal code it signs (docs/design/M5_C3_CONTRACT.md sections 2.1, 2.2, 5).

Key: the Ed25519 private key whose 32-byte seed is sha256(KEY_DOMAIN + OEMSIM_SIGNING_SEED). The seed is a secret
read by name (A-02): generated into .env.local by ``stack up``, set as a secret on a host, never committed, never
logged. Without it (or shorter than 32 characters) ``NoSigningKey`` is raised and the routes answer 503.

Code: ``SEAL1.<kid>.<payload_b64url>.<signature_b64url>``; the payload is the canonical JSON of
{v, oem, serial, sku, sealed_at, nonce} (sorted keys, no whitespace, ASCII); the signature is over
SIGN_DOMAIN + payload bytes. field-api verifies the same format on its side (field_api.authenticity.seal_code);
tests/e2e/test_m5_c3_seal_code_e2e.py proves that a code signed here verifies there and a forged one does not.

The forger's key (scenario L3, the counterfeit label) is derived from the same seed with another domain string: a
key the maker never published, so a code it signs carries the maker's ``kid`` but fails the signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import date
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SEED_ENV = "OEMSIM_SIGNING_SEED"
MIN_SEED_CHARS = 32
KEY_DOMAIN = b"scmtips-field/oem-sim-key/v1\n"
FORGER_DOMAIN = b"scmtips-field/oem-sim-forger/v1\n"
NONCE_DOMAIN = b"scmtips-field/oem-sim-nonce/v1\n"
SIGN_DOMAIN = b"scmtips-field/oem-seal/v1\n"
PREFIX = "SEAL1"
OEM_ID = "kestrel-sample"
OEM_NAME = "Kestrel Optics (SAMPLE)"


class NoSigningKey(Exception):
    """OEMSIM_SIGNING_SEED is not set (or too short): the simulator cannot sign or publish a key."""


@dataclass(frozen=True)
class Payload:
    oem: str
    serial: str
    sku: str
    sealed_at: date
    nonce: str
    v: int = 1

    def as_dict(self) -> dict[str, object]:
        return {"nonce": self.nonce, "oem": self.oem, "serial": self.serial, "sealed_at": self.sealed_at.isoformat(),
                "sku": self.sku, "v": self.v}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical(payload: Payload) -> bytes:
    return json.dumps(payload.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _seed() -> bytes:
    raw = os.getenv(SEED_ENV, "")
    if len(raw) < MIN_SEED_CHARS:
        raise NoSigningKey(f"{SEED_ENV} is not set (at least {MIN_SEED_CHARS} characters; see .env.example)")
    return raw.encode("utf-8")


def _key(domain: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(domain + _seed()).digest())


def signing_key() -> Ed25519PrivateKey:
    return _key(KEY_DOMAIN)


def forger_key() -> Ed25519PrivateKey:
    return _key(FORGER_DOMAIN)


def public_raw(key: Ed25519PrivateKey) -> bytes:
    # cast: the installed types-cryptography stubs declare Encoding.Raw / PublicFormat.Raw as str.
    return key.public_key().public_bytes(cast(Encoding, Encoding.Raw), cast(PublicFormat, PublicFormat.Raw))


def kid_of(public: bytes) -> str:
    return hashlib.sha256(public).hexdigest()[:16]


def jwks() -> dict[str, object]:
    pub = public_raw(signing_key())
    return {"oem": OEM_ID, "name": OEM_NAME, "sample": True,
            "keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": kid_of(pub),
                      "x": b64url(pub)}]}


def nonce_for(serial: str) -> str:
    """Stable per serial and deployment, so seeding again keeps every printed label valid."""
    return hmac.new(_seed(), NONCE_DOMAIN + serial.encode("ascii"), hashlib.sha256).hexdigest()[:16]


def encode(payload: Payload, key: Ed25519PrivateKey, kid: str) -> str:
    body = canonical(payload)
    sig = key.sign(SIGN_DOMAIN + body)
    return f"{PREFIX}.{kid}.{b64url(body)}.{b64url(sig)}"


def seal_code(serial: str, sku: str, sealed_at: date, nonce: str) -> str:
    """The maker's genuine code of a unit."""
    key = signing_key()
    return encode(Payload(OEM_ID, serial, sku, sealed_at, nonce), key, kid_of(public_raw(key)))


def forged_code(serial: str, sku: str, sealed_at: date) -> str:
    """A counterfeit: the maker's kid, a well-formed payload, a signature by a key the maker never published."""
    kid = kid_of(public_raw(signing_key()))
    return encode(Payload(OEM_ID, serial, sku, sealed_at, nonce_for(serial)), forger_key(), kid)
