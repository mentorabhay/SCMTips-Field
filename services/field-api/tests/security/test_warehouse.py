"""Security & authorization for warehouse operations on the spec API (T3.070 / FR3.030, FR1.022).

C3 rewrite: the previous test exercised the invented in-memory /v1/warehouse/inventory routes.
"""

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import create_app
from field_api.auth.jwt import create_dev_token

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _headers(tenant: str, site: str, roles: list[str]) -> dict[str, str]:
    tok = create_dev_token("sec-user", tenant, roles, site_ids=[site])
    return {"Authorization": f"Bearer {tok}", "Idempotency-Key": str(uuid.uuid4())}


@pytest.mark.unit
def test_t3_070_warehouse_rbac_enforcement(client: TestClient) -> None:
    """T3.070: unauthenticated -> 401; operator/supervisor cannot create PI docs; controller can."""
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, status)"
                    " VALUES (%s, %s, 'SEC-1', 'Sec DC', 'warehouse', 'active')", (site, tenant))
    body = {"site_id": site, "plant": "1000", "storage_location": "0001",
            "items": [{"bin": "B1", "material": "M1", "book_qty": "5", "unit_price": "1"}]}
    assert client.post("/v1/pi-documents", json=body).status_code == 401
    assert client.post("/v1/pi-documents", json=body, headers=_headers(tenant, site, ["field.operator"])).status_code == 403
    # supervisors approve PI differences, so they must not also create the book snapshot (SoD)
    assert client.post("/v1/pi-documents", json=body,
                       headers=_headers(tenant, site, ["field.supervisor"])).status_code == 403
    r = client.post("/v1/pi-documents", json=body, headers=_headers(tenant, site, ["inventory.controller"]))
    assert r.status_code == 201, r.text
    # out-of-scope site
    other = str(uuid.uuid4())
    r = client.post("/v1/pi-documents", json={**body, "site_id": other},
                    headers=_headers(tenant, site, ["inventory.controller"]))
    assert r.status_code == 403 and "SCOPE" in r.text
    # operators cannot post differences or decide approvals
    assert client.post(f"/v1/pi-documents/{r.json().get('id', uuid.uuid4())}/post-differences",
                       headers=_headers(tenant, site, ["field.operator"])).status_code == 403
    assert client.post(f"/v1/approval-requests/{uuid.uuid4()}/decide", json={"decision": "approve", "reason": "x"},
                       headers=_headers(tenant, site, ["field.operator"])).status_code == 403
