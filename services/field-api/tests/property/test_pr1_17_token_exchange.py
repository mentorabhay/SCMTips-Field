"""PR1.17 / API1.03: token exchange (TC1.049, TC1.050, TC1.122).

Core tokens come from the real fake-core service (EdDSA, served JWKS) through httpx.ASGITransport;
field-api verifies them with its real JWKS cache. A field access token (HS256) must NOT be
exchangeable, and device-bound exchanges require an active field.device row.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import hypothesis.strategies as st
import psycopg
import pytest
from fake_core.app import TokenIssueRequest, issue_token
from fake_core.app import app as core_app
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth import jwks
from field_api.auth.jwt import create_dev_token, verify_token
from hypothesis import HealthCheck, given, settings

client = TestClient(app)
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")


@pytest.fixture(autouse=True)
def _core_jwks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache = jwks.JwksCache(jwks_url="http://core/.well-known/jwks.json", transport=httpx.ASGITransport(app=core_app))
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.delenv("CORE_API_URL", raising=False)
    yield


def _core_token(**kw: Any) -> str:
    return str(issue_token(TokenIssueRequest(**kw))["access_token"])


def _exchange(token: str, device_id: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"device_token": token}
    if device_id:
        body["device_id"] = device_id
    return client.post("/v1/auth/exchange", json=body)


@pytest.mark.property
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.integers(min_value=10, max_value=3600),
    st.sampled_from(["field.operator", "field.supervisor", "field.admin"]),
    st.text(min_size=4, max_size=12, alphabet="abcdef0123456789"),
)
def test_pr1_17_token_exchange_acceptance_and_ttl(core_ttl: int, role: str, user_suffix: str) -> None:
    """PR1.17: a valid core token exchanges; TTL <= min(600, core_exp - now) (TC1.049, TC1.122)."""
    tenant = str(uuid.uuid4())
    r = _exchange(_core_token(principal_id=f"usr_{user_suffix}", tenant_id=tenant, roles=[role], ttl_seconds=core_ttl))
    assert r.status_code == 200, r.text
    data = r.json()
    assert 1 <= data["expires_in"] <= min(600, core_ttl)
    assert data["token_type"] == "Bearer" and data["roles"] == [role] and data["tenant_id"] == tenant
    p = verify_token(data["access_token"])
    assert (p.id, p.tenant_id, p.device_id) == (f"usr_{user_suffix}", tenant, None)


@pytest.mark.property
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-_"))
def test_pr1_17_invalid_token_rejected(garbage_token: str) -> None:
    """PR1.17: corrupted or forged tokens are rejected with 401 (TC1.050)."""
    r = _exchange(f"invalid.{garbage_token}")
    assert r.status_code == 401 and r.json()["code"] == "FIELD-AUTH-401-UNAUTHORIZED"


def test_tc1_050_field_token_cannot_be_exchanged() -> None:
    """A field HS256 token is not a core token: no self-refresh loop."""
    tok = create_dev_token("u1", str(uuid.uuid4()), ["field.operator"])
    assert _exchange(tok).status_code == 401


def test_tc1_050_unknown_role_and_non_uuid_tenant_rejected() -> None:
    # M4 (core reply TO_FIELD section 2): a role that maps to no Field role is still refused, now with the distinct
    # 403 FIELD-AUTH-403-NO-FIELD-ROLE and a sentence for the sign-in screen instead of the bare 401.
    r = _exchange(_core_token(principal_id="u", tenant_id=str(uuid.uuid4()), roles=["root"]))
    assert r.status_code == 403 and r.json()["code"] == "FIELD-AUTH-403-NO-FIELD-ROLE"
    assert "root" in r.json()["detail"]
    assert _exchange(_core_token(principal_id="u", tenant_id="tenant-1", roles=["field.operator"])).status_code == 401


def test_t1_038_device_exchange_requires_active_device_row() -> None:
    tenant, device = str(uuid.uuid4()), str(uuid.uuid4())
    tok = _core_token(principal_id="u1", tenant_id=tenant, roles=["field.operator"], device_id=device)
    assert _exchange(tok).status_code == 403  # no field.device row yet
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute(
            "INSERT INTO field.device (id, tenant_id, kind, serial_no, model, status)"
            " VALUES (%s, %s, 'phone', %s, 'test', 'active')",
            (device, tenant, device[:8]),
        )
    r = _exchange(tok)
    assert r.status_code == 200, r.text
    assert verify_token(r.json()["access_token"]).device_id == device
    other = _core_token(principal_id="u1", tenant_id=tenant, roles=["field.operator"], device_id=device)
    assert _exchange(other, device_id=str(uuid.uuid4())).status_code == 401  # binding mismatch
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("UPDATE field.device SET status = 'revoked' WHERE id = %s", (device,))
    assert _exchange(tok).status_code == 403
