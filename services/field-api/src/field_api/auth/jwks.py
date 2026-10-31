"""JWKS Client with Caching, Dynamic Key Refresh, and Signature Verification (Task T1.036 / PR1.17).

Fetches and caches JWKS (FIELD_JWKS_TTL_S), re-reads it once on an unknown kid or a failed signature check
(M4 F7: the core makes a new signing key at every local start-up, handover 01a), at most once per
FIELD_JWKS_FORCED_REFRESH_MIN_S (5 s) so forged tokens cannot make field-api hammer the core;
allows only EdDSA and RS256/ES256 per config, checks iss, aud, exp, nbf with 60 s skew.
The JWKS URL is FIELD_CORE_JWKS_URL, default {FIELD_CORE_BASE_URL}/v1/core/jwks.json (field_api.auth.core).
"""

import base64
import os
import time
from typing import Any

import httpx
import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

from field_api.auth.core import CORE_HEADERS, core_jwks_url

logger = structlog.get_logger(__name__)

DEFAULT_JWKS_URL = core_jwks_url()
JWKS_TTL_SECONDS = int(os.getenv("FIELD_JWKS_TTL_S", "300"))
ALLOWED_ALGORITHMS = ("EdDSA", "RS256", "ES256")


class JwksCache:
    """In-memory cache for remote JWKS keys."""

    def __init__(
        self,
        jwks_url: str = DEFAULT_JWKS_URL,
        ttl: int = JWKS_TTL_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self.ttl = ttl
        self._transport = transport  # tests: httpx.ASGITransport(app=fake_core.app)
        self._keys_by_kid: dict[str, Any] = {}
        self._last_fetched: float = 0.0
        self._last_forced: float = float("-inf")
        self.forced_min_s = float(os.getenv("FIELD_JWKS_FORCED_REFRESH_MIN_S", "5"))

    async def refresh_forced(self) -> bool:
        """Re-read the JWKS now (unknown kid, failed signature), unless one was forced < forced_min_s ago."""
        now = time.monotonic()
        if now - self._last_forced < self.forced_min_s:
            return False
        self._last_forced = now
        await self.refresh()
        return True

    async def get_key_for_kid(self, kid: str | None) -> Any:
        """Get public key matching kid, refreshing cache if necessary."""
        now = time.time()
        # If cache expired or empty, fetch
        if not self._keys_by_kid or (now - self._last_fetched) > self.ttl:
            await self.refresh()

        if kid and kid in self._keys_by_kid:
            return self._keys_by_kid[kid]

        # Unknown kid: refresh once (rate-limited)
        await self.refresh_forced()
        if kid and kid in self._keys_by_kid:
            return self._keys_by_kid[kid]

        # If kid is None and there is exactly one key, return it
        if kid is None and len(self._keys_by_kid) == 1:
            return next(iter(self._keys_by_kid.values()))

        raise ValueError(f"Key ID (kid) '{kid}' not found in JWKS")

    async def refresh(self) -> None:
        """Fetch and parse JWKS from endpoint."""
        try:
            timeout_s = float(os.getenv("FIELD_JWKS_TIMEOUT_S", "2.0"))
            async with httpx.AsyncClient(timeout=timeout_s, transport=self._transport) as client:
                resp = await client.get(self.jwks_url, headers=dict(CORE_HEADERS))
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

    if alg not in ALLOWED_ALGORITHMS:  # never HS256: core tokens are asymmetric
        raise ValueError(f"Algorithm '{alg}' is not in allowed list: {ALLOWED_ALGORITHMS}")

    key = await jwks_cache.get_key_for_kid(kid)
    try:
        return _decode(token, key, alg, expected_audience)
    except jwt.InvalidSignatureError:
        # The core may have restarted with a new key under the same kid (01a): re-read once, then decide.
        if not await jwks_cache.refresh_forced():
            raise
        return _decode(token, await jwks_cache.get_key_for_kid(kid), alg, expected_audience)


def _decode(token: str, key: Any, alg: str, audience: str) -> dict[str, Any]:
    payload: dict[str, Any] = jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=audience,
        issuer="scmtips-core",
        leeway=60,  # 60s clock skew tolerance
        options={"require": ["exp", "iss", "sub"]},
    )
    return payload
