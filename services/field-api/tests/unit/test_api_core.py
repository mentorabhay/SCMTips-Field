"""Unit Tests for Core API Endpoints (Task T1.011 / T1.012 / T1.013)."""

import uuid

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
def test_tc1_012_readiness_probes_are_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """T1.012 / API1.02: each check is measured; an unreachable dependency gives 503, not "pass"."""
    import httpx
    from fake_core.app import app as core_app
    from field_api.auth import jwks

    monkeypatch.setattr(jwks, "jwks_cache", jwks.JwksCache("http://core/.well-known/jwks.json", transport=httpx.ASGITransport(app=core_app)))
    monkeypatch.setenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:9")  # nothing listens on the discard port
    res = client.get("/v1/ready")
    assert res.status_code == 503
    checks = {c["name"]: c for c in res.json()["checks"]}
    assert checks["database"]["status"] == "pass"
    assert checks["alembic_head"]["status"] == "pass", checks["alembic_head"]
    assert checks["jwks_cache"]["status"] == "pass" and checks["jwks_cache"]["message"] == "1 key(s)"
    assert checks["erp_sim"]["status"] == "fail"
    assert res.json()["status"] == "fail"


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
def test_system_status_is_real_and_needs_permission() -> None:
    """API1.13: permission field.system.read; checks are measured, not constants."""
    assert client.get("/v1/system/status").status_code == 401
    op = create_dev_token("op", str(uuid.uuid4()), ["field.operator"])
    assert client.get("/v1/system/status", headers={"Authorization": f"Bearer {op}"}).status_code == 403
    sup = create_dev_token("sup", str(uuid.uuid4()), ["field.supervisor"])
    res = client.get("/v1/system/status", headers={"Authorization": f"Bearer {sup}"})
    assert res.status_code == 200, res.text
    data = res.json()
    checks = {c["name"]: c for c in data["checks"]}
    assert checks["postgres"]["ok"] is True and checks["postgres"]["probe_ms"] is not None
    assert set(checks) == {"postgres", "field-worker", "erp"}
    assert data["ready"] == all(c["ok"] for c in data["checks"])
    assert data["erp"]["p95_ms"] is None
    assert set(data["compat"].values()) <= {"PASS", "FAIL", "SKIPPED-PENDING", "UNVERIFIED"}
