"""Unit Tests for Core API Endpoints (Task T1.011 / T1.012 / T1.013)."""

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token

client = TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_dev_token(
        principal_id="test-operator-01",
        tenant_id="00000000-0000-0000-0000-000000000001",
        roles=["field.operator", "field.admin"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": "test-req-00123456",
    }


@pytest.mark.unit
def test_liveness_health() -> None:
    res = client.get("/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pass"
    assert data["service"] == "field-api"


@pytest.mark.unit
def test_readiness() -> None:
    res = client.get("/v1/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pass"
    assert len(data["checks"]) >= 3


@pytest.mark.unit
def test_problem_json_404_format() -> None:
    res = client.get("/v1/nonexistent-route")
    assert res.status_code == 404
    assert res.headers["Content-Type"] == "application/problem+json"
    data = res.json()
    assert data["type"] == "urn:scmtips-field:problem:FIELD-CORE-404-NOT-FOUND"
    assert data["code"] == "FIELD-CORE-404-NOT-FOUND"
    assert "request_id" in data


@pytest.mark.unit
def test_unauthenticated_request_fails(auth_headers: dict[str, str]) -> None:
    res = client.get("/v1/me")
    assert res.status_code == 401
    assert res.headers["Content-Type"] == "application/problem+json"
    data = res.json()
    assert data["code"] == "FIELD-AUTH-401-UNAUTHORIZED"


@pytest.mark.unit
def test_authenticated_me_endpoint(auth_headers: dict[str, str]) -> None:
    res = client.get("/v1/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "test-operator-01"
    assert data["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert "field.capture.create" in data["permissions"]


@pytest.mark.unit
def test_system_status() -> None:
    res = client.get("/v1/system/status")
    assert res.status_code == 200
    data = res.json()
    assert data["overall_status"] == "OPERATIONAL"
    assert len(data["services"]) >= 4
    assert len(data["compatibility"]) >= 3
