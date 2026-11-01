"""M5-J01: the hosted field console signs in through the core (e-mail + password -> core app token -> exchange).

The console's server sends the core a per-browser device id ``web-console:<uuid>`` (device_model WEB_CONSOLE) and
exchanges the core token with ``client_id: field-console`` and no ``device_id``. A browser is not a field device: the
exchange answers an unbound field token, registers no field.device and asks no device status. A phone's core token
keeps every device check whatever client id it claims.

Tokens come from the stand-in core (tools/fake-core, a dev double of the core contract) in process, as in
test_m4_core_exchange.py. Against the real core this is UNVERIFIED.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from fake_core.app import app as core_app
from fake_core.standin.state import StandInState
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth import jwks
from field_api.auth.jwt import verify_token
from field_api.routes import auth as auth_routes

client = TestClient(app)
core_client = TestClient(core_app)
STANDIN: StandInState = core_app.state.standin
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
STATUS_TPL = "http://core/v1/core/devices/{device_id}/status?tenant_id={tenant_id}"


@pytest.fixture(autouse=True)
def _core(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache = jwks.JwksCache(jwks_url="http://core/v1/core/jwks.json", transport=httpx.ASGITransport(app=core_app))
    cache.forced_min_s = 0
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.setattr(auth_routes, "CORE_TRANSPORT", httpx.ASGITransport(app=core_app))
    monkeypatch.setenv("FIELD_CORE_DEVICE_STATUS_URL", STATUS_TPL)
    monkeypatch.delenv("CORE_API_URL", raising=False)
    yield


def console_device() -> str:
    return f"web-console:{uuid.uuid4()}"


def sign_in(device: str, email: str = "approver@demo.scmtips.test", model: str = "WEB_CONSOLE") -> dict[str, Any]:
    r = core_client.post("/v1/auth/app/token", headers={"X-Requested-With": "lr"}, json={
        "email": email, "password": STANDIN.password, "device_id": device, "device_model": model,
        "client": "scmtips-field"})
    assert r.status_code == 200, r.text
    return dict(r.json())


def exchange(token: str, client_id: str | None = "field-console", device_id: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"device_token": token}
    if client_id is not None:
        body["client_id"] = client_id
    if device_id is not None:
        body["device_id"] = device_id
    return client.post("/v1/auth/exchange", json=body)


def field_devices(tenant: str, serial: str) -> list[str]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT id::text FROM field.device WHERE tenant_id = %s AND serial_no = %s", (tenant, serial))
        return [str(r[0]) for r in cur.fetchall()]


def test_m5_j01_console_token_exchanges_unbound_and_registers_no_device() -> None:
    dev = console_device()
    s = sign_in(dev)
    assert s["claims"]["device_id"] == dev  # the core binds the console's browser id
    r = exchange(s["access_token"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["device_id"] is None and data["roles"] == ["field.supervisor"]
    assert verify_token(data["access_token"]).device_id is None
    assert field_devices(s["claims"]["tenant_id"], dev) == []
    me = client.get("/v1/devices", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200, me.text  # a supervisor's console token reads the device list


def test_m5_j01_console_token_needs_no_core_device_session() -> None:
    """The real core keeps a device session only for members who may pair glasses; its device status says
    revoked for everyone else. The console's exchange does not ask it."""
    dev = console_device()
    s = sign_in(dev)
    core_client.post(f"/_standin/devices/{dev}/revoke")
    assert exchange(s["access_token"]).status_code == 200


def test_m5_j01_phone_token_claiming_the_console_client_keeps_the_device_checks() -> None:
    phone = f"phone-{uuid.uuid4().hex[:12]}"
    s = sign_in(phone, model="PHONE_ONLY")
    core_client.post(f"/_standin/devices/{phone}/revoke")
    r = exchange(s["access_token"])  # client_id field-console, but the token is bound to a phone
    assert r.status_code == 403 and r.json()["code"] == "FIELD-AUTH-403-DEVICE-REVOKED"


def test_m5_j01_console_device_id_is_unbound_only_for_the_console_client_without_a_device_id() -> None:
    dev = console_device()
    s = sign_in(dev)
    other = exchange(s["access_token"], client_id=None)  # not the console's server: the device path, as before
    assert other.status_code == 200 and other.json()["device_id"] is not None
    assert field_devices(s["claims"]["tenant_id"], dev) == [other.json()["device_id"]]
    explicit = exchange(s["access_token"], device_id=str(uuid.uuid4()))  # an explicit device id is checked
    assert explicit.status_code == 401


def test_m5_j01_no_field_role_is_still_refused_for_the_console() -> None:
    token, _ = STANDIN.key.issue({"sub": "u1", "tenant_id": STANDIN.tenant_id, "roles": ["guest"], "sites": ["*"],
                                  "device_id": console_device(), "permissions": [], "email": "g@demo.scmtips.test"}, 600)
    r = exchange(token)
    assert r.status_code == 403 and r.json()["code"] == "FIELD-AUTH-403-NO-FIELD-ROLE"
