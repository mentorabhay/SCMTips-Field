"""Signing key of the stand-in core (dev double): Ed25519, kid prefix ``scmtips-core-ed25519-`` as the core's.

Like the core run locally without LR_CORE_SIGNING_KEY (handover 01a), a new key is made at every start-up, so
Field must re-read the JWKS after an unknown kid or a failed signature check.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ISSUER = "scmtips-core"
AUDIENCE = "scmtips-core"
KID_PREFIX = "scmtips-core-ed25519-"


class CoreKey:
    def __init__(self, private_key: ed25519.Ed25519PrivateKey | None = None) -> None:
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        # cast: the installed cryptography stubs type these enums as str
        raw = self.private_key.public_key().public_bytes(cast(Any, serialization.Encoding.Raw),
                                                         cast(Any, serialization.PublicFormat.Raw))
        self._x = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        self.kid = f"{KID_PREFIX}standin-{hashlib.sha256(raw).hexdigest()[:12]}"

    def jwk(self) -> dict[str, Any]:
        return {"kty": "OKP", "crv": "Ed25519", "kid": self.kid, "use": "sig", "alg": "EdDSA", "x": self._x}

    def issue(self, claims: dict[str, Any], ttl_s: int) -> tuple[str, dict[str, Any]]:
        now = datetime.now(UTC)
        full = {
            "iss": ISSUER, "aud": AUDIENCE, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_s)).timestamp()), "jti": str(uuid.uuid4()), **claims,
        }
        token: Any = jwt.encode(full, cast(Any, self.private_key), algorithm="EdDSA", headers={"kid": self.kid})
        return (token if isinstance(token, str) else bytes(token).decode("ascii")), full
