"""Fake Core Platform Service for Development and Tests (Task T1.035 / FR1.010).

Serves:
- GET /.well-known/jwks.json (RFC 8037 OKP Ed25519 public keys)
- POST /api/v1/auth/token (Core SSO session tokens & P10 device tokens)
- GET /api/v1/devices/{id}/status (Device authorization & revocation status)
- POST /api/v1/devices/{id}/revoke (Revoke device binding)
"""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI
from pydantic import BaseModel, Field

# In-memory device revocation registry for fake-core
REVOKED_DEVICES: set[str] = set()

# Fixed Ed25519 Keypair for deterministic testing
_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
KID = "fake-core-ed25519-v1"


def get_jwk() -> dict[str, Any]:
    raw_public = _PUBLIC_KEY.public_bytes_raw()
    x_b64 = base64.urlsafe_b64encode(raw_public).decode("utf-8").rstrip("=")
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "kid": KID,
        "use": "sig",
        "alg": "EdDSA",
        "x": x_b64,
    }


app = FastAPI(
    title="SCMTIPS Fake Core Service",
    description="Mock SSO and Device Registry for local development and integration tests",
    version="1.0.0",
)


class TokenIssueRequest(BaseModel):
    principal_id: str
    tenant_id: str
    device_id: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["field.operator"])
    ttl_seconds: int = 3600


class DeviceRevokeRequest(BaseModel):
    reason: str = "administrative"


@app.get("/.well-known/jwks.json")
def get_jwks() -> dict[str, Any]:
    """Expose Ed25519 JWKS public keys."""
    return {"keys": [get_jwk()]}


@app.post("/api/v1/auth/token")
def issue_token(req: TokenIssueRequest) -> dict[str, Any]:
    """Issue a simulated core-signed JWT with Ed25519 signature."""
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=req.ttl_seconds)
    jti = str(uuid.uuid4())

    claims: dict[str, Any] = {
        "iss": "scmtips-core",
        "sub": req.principal_id,
        "aud": "scmtips-core",
        "tenant_id": req.tenant_id,
        "roles": req.roles,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
    }
    if req.device_id:
        claims["device_id"] = req.device_id
        # Simple fingerprint: sha256 of tenant_id:device_id
        claims["device_binding"] = f"fp_{req.tenant_id[:8]}_{req.device_id[:8]}"

    token = jwt.encode(
        claims,
        _PRIVATE_KEY,
        algorithm="EdDSA",
        headers={"kid": KID},
    )

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": req.ttl_seconds,
        "claims": claims,
    }


@app.get("/api/v1/devices/{device_id}/status")
def get_device_status(device_id: str) -> dict[str, Any]:
    """Check whether a device is active or revoked."""
    is_revoked = device_id in REVOKED_DEVICES
    return {
        "device_id": device_id,
        "status": "revoked" if is_revoked else "active",
        "fingerprint": f"fp_dev_{device_id[:8]}",
        "last_seen_at": datetime.now(UTC).isoformat(),
    }


@app.post("/api/v1/devices/{device_id}/revoke")
def revoke_device(device_id: str, req: DeviceRevokeRequest | None = None) -> dict[str, Any]:
    """Revoke a device."""
    REVOKED_DEVICES.add(device_id)
    return {
        "success": True,
        "device_id": device_id,
        "status": "revoked",
        "revoked_at": datetime.now(UTC).isoformat(),
    }
