"""Property Test PR1.17: Token Exchange Acceptance and Expiration (Hypothesis)."""

import hypothesis.strategies as st
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from hypothesis import given, settings

client = TestClient(app)


@pytest.mark.property
@settings(max_examples=40, deadline=1000)
@given(
    st.integers(min_value=10, max_value=3600),
    st.sampled_from(["field.operator", "field.supervisor", "field.admin"]),
    st.text(min_size=4, max_size=12, alphabet="abcdef0123456789"),
)
def test_pr1_17_token_exchange_acceptance_and_ttl(
    core_ttl: int, role: str, user_suffix: str
) -> None:
    """PR1.17: Token exchange succeeds for valid core tokens, TTL <= min(600, core_exp - now) (TC1.049, TC1.122)."""
    user_id = f"usr_{user_suffix}"
    tenant_id = "00000000-0000-0000-0000-000000000001"

    # Create core device token
    core_token = create_dev_token(
        principal_id=user_id,
        tenant_id=tenant_id,
        roles=[role],
        site_ids=["SITE-01"],
        exp_seconds=core_ttl,
    )

    resp = client.post(
        "/v1/auth/exchange",
        json={"device_token": core_token, "device_id": f"dev_{user_suffix}"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Verification 1: Issued TTL is bounded by min(600s, core_ttl)
    expected_max_ttl = min(600, core_ttl)
    assert 1 <= data["expires_in"] <= expected_max_ttl

    # Verification 2: Token type is Bearer
    assert data["token_type"] == "Bearer"

    # Verification 3: Role and tenant are preserved
    assert role in data["roles"]
    assert data["tenant_id"] == tenant_id
    assert len(data["permissions"]) > 0


@pytest.mark.property
@settings(max_examples=25)
@given(
    st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-_"),
)
def test_pr1_17_invalid_token_rejected(garbage_token: str) -> None:
    """PR1.17: Corrupted or forged tokens are strictly rejected with 401 UNAUTHORIZED (TC1.050)."""
    resp = client.post(
        "/v1/auth/exchange",
        json={"device_token": f"invalid.{garbage_token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "FIELD-AUTH-401-UNAUTHORIZED"
