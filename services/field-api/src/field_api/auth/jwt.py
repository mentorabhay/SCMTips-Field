"""JWT Verification with JWKS Caching and Claims Parsing (Task T1.036 / PR1.17)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
import structlog
from pydantic import BaseModel

from field_api.auth.permissions import expand_permissions
from field_api.errors import ERR_AUTH_UNAUTHORIZED
from field_api.secrets import required_secret

logger = structlog.get_logger(__name__)


FIELD_ISSUER = "scmtips-field"  # field access tokens; core tokens (iss scmtips-core) are only accepted by /v1/auth/exchange


def get_jwt_secret() -> str:
    """HS256 key for field access tokens. Required; there is no built-in fallback (A-02)."""
    return required_secret("FIELD_JWT_SECRET", "JWT_SECRET_KEY")


class Principal(BaseModel):
    id: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]
    site_ids: list[str]  # ['*'] means all sites
    device_id: str | None = None
    auth_type: str = "bearer"


def create_dev_token(
    principal_id: str,
    tenant_id: str,
    roles: list[str],
    site_ids: list[str] | None = None,
    device_id: str | None = None,
    exp_seconds: int = 3600,
) -> str:
    """Generate a development JWT token for testing."""
    now = int(datetime.now(UTC).timestamp())
    sites = site_ids if site_ids is not None else ["*"]
    payload: dict[str, Any] = {
        "sub": principal_id,
        "iss": FIELD_ISSUER,
        "aud": "scmtips-field",
        "tid": tenant_id,
        "roles": roles,
        "sites": sites,
        "did": device_id,
        "iat": now,
        "nbf": now - 10,
        "exp": now + exp_seconds,
    }
    encoded = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")
    return str(encoded)


def verify_token(token: str) -> Principal:
    """Validate JWT token claims and return verified Principal."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=["HS256"],
            audience="scmtips-field",
            issuer=FIELD_ISSUER,
            leeway=60,
        )

        principal_id = str(claims.get("sub", ""))
        tenant_id = str(claims.get("tid", ""))
        roles = list(claims.get("roles", []))
        site_ids = list(claims.get("sites", ["*"]))
        device_id = claims.get("did")

        if not principal_id or not tenant_id:
            raise ERR_AUTH_UNAUTHORIZED
        uuid.UUID(tenant_id)  # tenants are UUIDs (RLS casts app.tenant_id to uuid); anything else is refused

        permissions = expand_permissions(roles)

        return Principal(
            id=principal_id,
            tenant_id=tenant_id,
            roles=roles,
            permissions=permissions,
            site_ids=site_ids,
            device_id=device_id,
        )
    except Exception as e:
        logger.warning("Token verification failed", error=str(e))
        raise ERR_AUTH_UNAUTHORIZED from e
