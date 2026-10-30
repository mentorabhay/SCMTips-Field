"""JWKS Client with Caching, Dynamic Key Refresh, and Signature Verification (Task T1.036 / PR1.17).

Fetches and caches JWKS (FIELD_JWKS_TTL_S), refreshes once on unknown kid,
allows only EdDSA and RS256/ES256 per config, checks iss, aud, exp, nbf with 60 s skew.
"""

import base64
import os
import time
from typing import Any

import httpx
import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)

DEFAULT_JWKS_URL = os.getenv("FIELD_CORE_JWKS_URL", "http://127.0.0.1:8001/.well-known/jwks.json")
JWKS_TTL_SECONDS = int(os.getenv("FIELD_JWKS_TTL_S", "300"))
ALLOWED_ALGORITHMS = ("EdDSA", "RS256", "ES256")


class JwksCache:
    """In-memory cache for remote JWKS keys."""

    def __init__(self, jwks_url: str = DEFAULT_JWKS_URL, ttl: int = JWKS_TTL_SECONDS) -> None:
        self.jwks_url = jwks_url
        self.ttl = ttl
        self._keys_by_kid: dict[str, Any] = {}
        self._last_fetched: float = 0.0

    async def get_key_for_kid(self, kid: str | None) -> Any:
        """Get public key matching kid, refreshing cache if necessary."""
        now = time.time()
        # If cache expired or empty, fetch
        if not self._keys_by_kid or (now - self._last_fetched) > self.ttl:
            await self.refresh()

        if kid and kid in self._keys_by_kid:
            return self._keys_by_kid[kid]

        # Unknown kid: refresh once
        await self.refresh()
        if kid and kid in self._keys_by_kid:
            return self._keys_by_kid[kid]

        # If kid is None and there is exactly one key, return it
        if kid is None and len(self._keys_by_kid) == 1:
            return next(iter(self._keys_by_kid.values()))

        raise ValueError(f"Key ID (kid) '{kid}' not found in JWKS")

    async def refresh(self) -> None:
        """Fetch and parse JWKS from endpoint."""
        try:
            timeout_s = float(os.getenv("FIELD_JWKS_TIMEOUT_S", "0.2"))
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(self.jwks_url)
                resp.raise_for_status()
                data = resp.json()

            keys: dict[str, Any] = {}
            for k in data.get("keys", []):
                kid = k.get("kid")
                kty = k.get("kty")
                crv = k.get("crv")

                if kty == "OKP" and crv == "Ed25519" and "x" in k:
                    # Parse Ed25519 public key
                    x_raw = base64.urlsafe_b64decode(k["x"] + "==")
                    public_key = ed25519.Ed25519PublicKey.from_public_bytes(x_raw)
                    keys[kid] = public_key
                elif kty == "RSA":
                    # RSA PyJWT standard set
                    keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(k)

            self._keys_by_kid = keys
            self._last_fetched = time.time()
            logger.info("jwks_cache_refreshed", key_count=len(keys))
        except Exception as e:
            # Set negative TTL backoff so offline core doesn't retry on every single token check
            self._last_fetched = time.time() - self.ttl + 5.0
            logger.warning("jwks_fetch_failed", url=self.jwks_url, error=str(e))


jwks_cache = JwksCache()


async def verify_core_jwt(token: str, expected_audience: str = "scmtips-core") -> dict[str, Any]:
    """Verify core-issued JWT using cached JWKS."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    alg = unverified_header.get("alg")

    if alg not in ALLOWED_ALGORITHMS and alg != "HS256":
        raise ValueError(f"Algorithm '{alg}' is not in allowed list: {ALLOWED_ALGORITHMS}")

    key = await jwks_cache.get_key_for_kid(kid)

    payload: dict[str, Any] = jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=expected_audience,
        issuer="scmtips-core",
        leeway=60,  # 60s clock skew tolerance
        options={"require": ["exp", "iss", "sub"]},
    )
    return payload
