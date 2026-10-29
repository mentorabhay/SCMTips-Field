"""Security & Authorization Tests for Warehouse Operations (Task T3.070 / FR3.030)."""

import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def auth_headers(roles: list[str]) -> dict[str, str]:
    token = create_dev_token(
        principal_id="test-sec-user",
        tenant_id="tenant-sec",
        roles=roles,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.unit
def test_t3_070_warehouse_rbac_enforcement(client):
    """T3.070: Unauthenticated requests and unauthorized roles fail with 401/403."""
    # 1. Unauthenticated request fails with 401
    resp = client.post(
        "/v1/warehouse/inventory/documents",
        json={"plant": "1000", "storage_location": "0001", "bins": ["B1"]},
    )
    assert resp.status_code in (401, 403)

    # 2. Operator role cannot create PI documents (requires supervisor or admin)
    op_headers = auth_headers(["field.operator"])
    resp = client.post(
        "/v1/warehouse/inventory/documents",
        json={"plant": "1000", "storage_location": "0001", "bins": ["B1"]},
        headers=op_headers,
    )
    assert resp.status_code == 403

    # 3. Supervisor role can create PI documents
    sup_headers = auth_headers(["field.supervisor"])
    resp = client.post(
        "/v1/warehouse/inventory/documents",
        json={"plant": "1000", "storage_location": "0001", "bins": ["B1"]},
        headers=sup_headers,
    )
    assert resp.status_code == 201
