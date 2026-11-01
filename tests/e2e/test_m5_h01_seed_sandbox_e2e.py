"""M5-H01 through the real APIs: the hosted sandbox seed against field-api, erp-sim and a core, then the phone's
grocery / pharmacy starters (POST /v1/sandbox/cases) as a core-signed-in operator.

In process: field-api (its routes, auth exchange, RLS on Postgres), erp-sim (reached only through the simulator
adapter, as on the host), and the stand-in core (tools/fake-core, a dev double of the core's app-token contract) with
an org_admin member added for the test. Each test gets its own tenant id. Against the real core and the host this is
UNVERIFIED until the hosting session runs the command there.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from erp_sim.app import app as erp_app
from fake_core.app import app as core_app
from fake_core.standin.state import DemoUser, StandInState
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth import jwks
from field_api.routes import auth as auth_routes
from field_api.sandbox import erp as sandbox_erp
from field_api.tools import seed_sandbox
from field_sap.sim.adapter import SimAdapter

pytestmark = pytest.mark.unit

STANDIN: StandInState = core_app.state.standin
ADMIN_EMAIL = "org.admin@demo.scmtips.test"
OPERATOR, APPROVER = "operator@demo.scmtips.test", "approver@demo.scmtips.test"
ORG_ADMIN = DemoUser("5a3e0a00-0000-4000-8000-0000000000a1", ADMIN_EMAIL, "SAMPLE Org admin", ("org_admin",),
                     ("voice.approve", "decision.read"), approve_decisions=True, field_operator=False)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    cache = jwks.JwksCache(jwks_url="http://core/v1/core/jwks.json", transport=httpx.ASGITransport(app=core_app))
    cache.forced_min_s = 0
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.setattr(auth_routes, "CORE_TRANSPORT", httpx.ASGITransport(app=core_app))
    monkeypatch.setenv("FIELD_CORE_DEVICE_STATUS_URL", "http://core/v1/core/devices/{device_id}/status?tenant_id={tenant_id}")
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.delenv("FIELD_CASE_SLOC", raising=False)
    monkeypatch.delenv("FIELD_QUALITY_SLOC", raising=False)
    monkeypatch.setattr(STANDIN, "users", (*STANDIN.users, ORG_ADMIN))
    monkeypatch.setattr(STANDIN, "tenant_id", str(uuid.uuid4()))
    # field-api's own sandbox calls (the cases) reach the same in-process erp-sim
    monkeypatch.setattr(sandbox_erp, "get_sandbox_port", lambda sim_url=None: SimAdapter(app=erp_app))
    yield STANDIN.tenant_id


def seed() -> seed_sandbox.Report:
    with TestClient(core_app) as core, TestClient(app) as field_api:
        return seed_sandbox.Seeder(core, field_api, SimAdapter(app=erp_app)).run(ADMIN_EMAIL, STANDIN.password)


def field_token(email: str, device: str) -> dict[str, Any]:
    """The phone's sign-in: core app token bound to the phone's install id, exchanged with no device id."""
    core, field_api = TestClient(core_app), TestClient(app)
    r = core.post("/v1/auth/app/token", headers={"X-Requested-With": "lr"}, json={
        "email": email, "password": STANDIN.password, "device_id": device, "device_model": "PHONE_ONLY",
        "client": "scmtips-field"})
    assert r.status_code == 200, r.text
    x = field_api.post("/v1/auth/exchange", json={"device_token": r.json()["access_token"]})
    assert x.status_code == 200, x.text
    return dict(x.json())


def _rows(db: str, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    url = os.environ["FIELD_ADMIN_DATABASE_URL"].rsplit("/", 1)[0] + "/" + db
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def counts(tenant: str, site: str) -> tuple[int, int]:
    return (int(_rows("field", "SELECT count(*) FROM field.site WHERE tenant_id = %s", (tenant,))[0][0]),
            int(_rows("field", "SELECT count(*) FROM field.location WHERE site_id = %s", (site,))[0][0]))


def test_m5_h01_seed_then_the_operator_starts_both_cases_on_the_sandbox_site(_world: str) -> None:
    report = seed()
    assert report.site_created and report.site_ids == ["*"]
    assert report.phone_site == report.site_id  # the only site of the tenant: the phone opens it
    api = TestClient(app)
    admin = field_token(ADMIN_EMAIL, f"phone-{uuid.uuid4().hex[:12]}")
    site = api.get(f"/v1/sites/{report.site_id}", headers={"Authorization": f"Bearer {admin['access_token']}"}).json()
    assert (site["code"], site["name"], site["mode"], site["erp_plant"], site["erp_storage_locations"]) == (
        "HOME-SBX", "Home (sandbox)", "sandbox", "HOME", ["HM01", "101A", "101Q"])
    assert sorted(_rows("erpsim", "SELECT storage_location FROM erpsim.storage_location WHERE client = '100'"
                               " AND plant = 'HOME'", ())) == [("101A",), ("101Q",), ("HM01",)]

    op = field_token(OPERATOR, f"phone-{uuid.uuid4().hex[:12]}")
    assert op["roles"] == ["field.operator"] and op["site_ids"] == ["*"]
    h = {"Authorization": f"Bearer {op['access_token']}"}
    sites = api.get("/v1/sites", params={"limit": 200}, headers=h).json()["items"]
    assert [s["id"] for s in sites] == [report.site_id]  # what the phone's SiteChoice picks from
    made = {}
    for case in ("grocery", "pharmacy"):
        r = api.post("/v1/sandbox/cases", json={"site_id": report.site_id, "case": case},
                     headers={**h, "Idempotency-Key": str(uuid.uuid4())})
        assert r.status_code == 201, r.text
        made[case] = r.json()
    assert made["grocery"]["expected_units"] == 20 and made["grocery"]["expected_pieces_per_unit"] == 12
    assert made["pharmacy"]["expiry_window_days"] == 90
    for case in made.values():  # each case's delivery is in plant HOME, storage location 101A (good units)
        assert _rows("erpsim", "SELECT plant, storage_location FROM erpsim.inbound_delivery WHERE client = '100'"
                               " AND delivery_document = %s", (case["ref_doc_no"],)) == [("HOME", "101A")]

    sup = field_token(APPROVER, f"phone-{uuid.uuid4().hex[:12]}")  # core approver -> field.supervisor
    r = api.post("/v1/sandbox/cases", json={"site_id": report.site_id, "case": "grocery"},
                 headers={"Authorization": f"Bearer {sup['access_token']}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 403  # no field.task.execute: an approver cannot start a case


def test_m5_h01_second_seed_creates_nothing(_world: str) -> None:
    first = seed()
    before = counts(_world, first.site_id)
    assert before == (1, 3)
    again = seed()
    assert (again.site_id, again.site_created) == (first.site_id, False)
    assert counts(_world, first.site_id) == before
    assert any("(all existed)" in line for line in again.lines)
    assert any("bins HOME-A, HOME-B: exist" in line for line in again.lines)
