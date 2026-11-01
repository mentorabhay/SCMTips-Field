"""C3 end to end across the two implementations of the seal code (M5-T04, M5-T07): codes signed by the OEM simulator
(services/oem-sim, its real schema oemsim) verify in field-api through the OEM port's simulator adapter (in-process
ASGI); its counterfeit fails; a cloned code checked by a second person is CANNOT_VERIFY; two concurrent first checks
through field-api leave exactly one first checker at the maker. On Postgres with RLS."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.authenticity.oem import get_oem_port
from field_api.authenticity.seal import VisualPorts, get_visual_ports
from field_oem.sim.adapter import SimOemAdapter
from oem_sim import keys
from oem_sim.app import app as oem_app
from oem_sim.routes import UnitIn, reset, upsert_unit

pytestmark = pytest.mark.unit

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
SEED = "e2e-seed-" + "0f1e2d3c4b5a6978" * 3


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv(keys.SEED_ENV, SEED)
    monkeypatch.delenv("ERPSIM_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    reset()
    events = [{"type": "manufactured", "at": "2026-09-28"}, {"type": "shipped_to_seller", "at": "2026-10-02"}]
    new = upsert_unit(UnitIn.model_validate({"serial": "KSO-E2E-0001", "sku": "KSO-BIN-842", "sealed_at": "2026-09-28",
                                             "events": events}))[0]["code"]
    returned = upsert_unit(UnitIn.model_validate({
        "serial": "KSO-E2E-0002", "sku": "KSO-BIN-842", "sealed_at": "2026-09-28",
        "events": [*events, {"type": "activated", "at": "2026-10-12"}, {"type": "returned", "at": "2026-10-20"}]}))[0]
    forged = keys.forged_code("KSO-E2E-0003", "KSO-BIN-842", date(2026, 9, 28))
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status, mode) VALUES"
                    " (%s, %s, %s, 'Home', 'warehouse', 'HOME', 'active', 'sandbox')", (site, tenant, f"E2E-{site[:6].upper()}"))
    port = SimOemAdapter("http://testserver/_oem", client=lambda: TestClient(oem_app, base_url="http://testserver/_oem"))
    app.dependency_overrides[get_oem_port] = lambda: port
    app.dependency_overrides[get_visual_ports] = lambda: VisualPorts(None, None)
    try:
        yield {"new": new, "returned": returned["code"], "forged": forged, "site": site, "port": port,
               "a": create_dev_token("cust-a", tenant, ["field.operator"], site_ids=[site]),
               "b": create_dev_token("cust-b", tenant, ["field.viewer"], site_ids=[site])}
    finally:
        app.dependency_overrides.pop(get_oem_port, None)
        app.dependency_overrides.pop(get_visual_ports, None)
        reset()


def test_m5_t04_sim_signed_codes_verify_in_field_api_and_the_clone_is_caught(world: dict[str, Any]) -> None:
    api = TestClient(app)
    first = api.post("/v1/authenticity/checks", json={"code": world["new"]}, headers=_h(world["a"])).json()
    assert first["verdict"] == "GENUINE_NEW" and first["signals"]["code"]["oem_name"] == "Kestrel Optics (SAMPLE)"
    clone = api.post("/v1/authenticity/checks", json={"code": world["new"]}, headers=_h(world["b"])).json()
    assert clone["verdict"] == "CANNOT_VERIFY" and clone["rule"] == "R13"
    r = api.post("/v1/authenticity/checks", json={"code": world["returned"]}, headers=_h(world["a"])).json()
    assert r["verdict"] == "RETURNED_REFURBISHED"
    assert r["say"].startswith("Code is genuine. But this unit was activated on 12 October and returned on 20 October.")
    f = api.post("/v1/authenticity/checks", json={"code": world["forged"]}, headers=_h(world["a"])).json()
    assert f["verdict"] == "LIKELY_COUNTERFEIT" and f["rule"] == "R6"
    assert world["port"].fetches == 1  # the maker's key set was fetched once and cached


def test_m5_t07_two_concurrent_first_checks_through_field_api_one_wins(world: dict[str, Any]) -> None:
    api = TestClient(app)
    barrier = threading.Barrier(2)
    out: list[str] = []

    def go(token: str) -> None:
        barrier.wait()
        body = api.post("/v1/authenticity/checks", json={"code": world["new"]}, headers=_h(world[token])).json()
        out.append(body["signals"]["first_check"]["status"])

    threads = [threading.Thread(target=go, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == ["first", "other_checker"]
