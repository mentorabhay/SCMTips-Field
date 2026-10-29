"""Tests for tools/fake-core service (Task T1.035)."""

import pytest
from fake_core.app import KID, app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.unit
def test_jwks_endpoint(client: TestClient) -> None:
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert len(data["keys"]) == 1
    key = data["keys"][0]
    assert key["kid"] == KID
    assert key["kty"] == "OKP"
    assert key["crv"] == "Ed25519"
    assert "x" in key


@pytest.mark.unit
def test_issue_token_and_device_status(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/token",
        json={
            "principal_id": "usr_999",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "device_id": "dev_phone_1",
            "roles": ["field.operator"],
        },
    )
    assert resp.status_code == 200
    token_data = resp.json()
    assert "access_token" in token_data

    # Check device status
    status_resp = client.get("/api/v1/devices/dev_phone_1/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "active"

    # Revoke device
    revoke_resp = client.post("/api/v1/devices/dev_phone_1/revoke")
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"

    # Verify status is now revoked
    status_resp2 = client.get("/api/v1/devices/dev_phone_1/status")
    assert status_resp2.json()["status"] == "revoked"
