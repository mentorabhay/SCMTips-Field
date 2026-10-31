"""M4 F7: /v1/auth/exchange accepts the core's app tokens (handover 01/01a, M4 contract sections 2 and 4).

Tokens come from the stand-in core (tools/fake-core, a dev double of the core contract) over HTTP in process;
field-api reads the core JWKS at /v1/core/jwks.json and asks the core device status through the
FIELD_CORE_DEVICE_STATUS_URL template, both routed to the stand-in by httpx.ASGITransport. Against the real
core this is UNVERIFIED (the core is not deployed).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from fake_core.app import TokenIssueRequest, issue_token
from fake_core.app import app as core_app
from fake_core.standin.keys import CoreKey
from fake_core.standin.state import StandInState
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth import core, jwks
from field_api.auth.jwt import verify_token
from field_api.routes import auth as auth_routes

client = TestClient(app)
core_client = TestClient(core_app)
STANDIN: StandInState = core_app.state.standin
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
STATUS_TPL = "http://core/v1/core/devices/{device_id}/status?tenant_id={tenant_id}"


@pytest.fixture(autouse=True)
def _core(monkeypatch: pytest.MonkeyPatch) -> Iterator[jwks.JwksCache]:
    cache = jwks.JwksCache(jwks_url="http://core/v1/core/jwks.json", transport=httpx.ASGITransport(app=core_app))
    cache.forced_min_s = 0
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.setattr(auth_routes, "CORE_TRANSPORT", httpx.ASGITransport(app=core_app))
    monkeypatch.setenv("FIELD_CORE_DEVICE_STATUS_URL", STATUS_TPL)
    monkeypatch.delenv("CORE_API_URL", raising=False)
    yield cache


def sign_in(email: str = "operator@demo.scmtips.test", device: str | None = None) -> dict[str, Any]:
    r = core_client.post("/v1/auth/app/token", headers={"X-Requested-With": "lr"}, json={
        "email": email, "password": STANDIN.password, "device_id": device or f"phone-{uuid.uuid4().hex[:12]}",
        "device_model": "PHONE_ONLY", "client": "scmtips-field"})
    assert r.status_code == 200, r.text
    return dict(r.json())


def exchange(token: str, device_id: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"device_token": token}
    if device_id:
        body["device_id"] = device_id
    return client.post("/v1/auth/exchange", json=body)


def field_devices(tenant: str, serial: str) -> list[tuple[str, str]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT id::text, status FROM field.device WHERE tenant_id = %s AND serial_no = %s",
                    (tenant, serial))
        return [(str(r[0]), str(r[1])) for r in cur.fetchall()]


def test_m4_c01_core_app_token_exchanges_and_registers_the_core_device() -> None:
    s = sign_in("approver@demo.scmtips.test")
    core_dev, tenant = s["wearable"]["device_id"], s["claims"]["tenant_id"]
    r = exchange(s["access_token"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["core_permissions"] == ["voice.approve", "decision.read", "evidence.upload"]
    assert data["roles"] == ["field.supervisor"] and data["tenant_id"] == tenant
    field_dev = data["device_id"]
    assert uuid.UUID(field_dev) and field_devices(tenant, core_dev) == [(field_dev, "active")]
    p = verify_token(data["access_token"])
    assert p.device_id == field_dev and "email" not in data
    again = exchange(s["access_token"], field_dev)  # the app sends the id it was given
    assert again.status_code == 200 and again.json()["device_id"] == field_dev
    assert exchange(s["access_token"]).json()["device_id"] == field_dev  # no second registration
    assert len(field_devices(tenant, core_dev)) == 1


def test_m4_c01_core_revocation_and_field_revocation_both_refuse() -> None:
    s = sign_in()
    core_dev, tenant = s["wearable"]["device_id"], s["claims"]["tenant_id"]
    field_dev = exchange(s["access_token"]).json()["device_id"]
    core_client.post(f"/_standin/devices/{core_dev}/revoke")
    r = exchange(s["access_token"], field_dev)
    assert r.status_code == 403 and r.json()["code"] == "FIELD-AUTH-403-DEVICE-REVOKED"
    s2 = sign_in()
    dev2 = exchange(s2["access_token"]).json()["device_id"]
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("UPDATE field.device SET status = 'revoked' WHERE id = %s AND tenant_id = %s", (dev2, tenant))
    assert exchange(s2["access_token"]).status_code == 403  # field's own revocation wins over the core's active
    assert exchange(s2["access_token"], dev2).status_code == 403


def test_m4_c01_unknown_core_device_without_a_core_check_stays_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIELD_CORE_DEVICE_STATUS_URL")
    s = sign_in()
    assert exchange(s["access_token"]).status_code == 403
    assert field_devices(s["claims"]["tenant_id"], s["wearable"]["device_id"]) == []


def test_m4_c01_binding_mismatch_is_401() -> None:
    a, b = sign_in(), sign_in()
    dev_b = exchange(b["access_token"]).json()["device_id"]
    r = exchange(a["access_token"], dev_b)  # a's token, b's field device
    assert r.status_code == 401
    assert exchange(a["access_token"], str(uuid.uuid4())).status_code == 401
    assert exchange(a["access_token"], b["wearable"]["device_id"]).status_code == 401  # a serial is not an id


def test_m4_c01_malformed_extra_claims_are_refused() -> None:
    for extra in ({"permissions": "voice.approve"}, {"permissions": [1, 2]}, {"email": ["x"]}):
        token, _ = STANDIN.key.issue({"sub": "u1", "tenant_id": STANDIN.tenant_id, "roles": ["field.operator"],
                                      "sites": ["*"], **extra}, 600)
        assert exchange(token).status_code == 401, extra
    token, _ = STANDIN.key.issue({"sub": "u1", "tenant_id": STANDIN.tenant_id, "roles": ["field.operator"],
                                  "sites": ["*"], "permissions": [], "email": "x@demo.scmtips.test"}, 600)
    assert exchange(token).json()["core_permissions"] == []


def test_m4_c01_unbound_dev_token_is_not_asked_at_the_core_path() -> None:
    """The dev QR pairing token (fake-core /api/v1/auth/token) has no core device: the core is not asked
    about field device ids (it would answer revoked); the field.device check still applies."""
    tenant, device = str(uuid.uuid4()), str(uuid.uuid4())
    tok = str(issue_token(TokenIssueRequest(principal_id="u", tenant_id=tenant, roles=["field.operator"]))["access_token"])
    assert exchange(tok, device).status_code == 403  # no field.device
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO field.device (id, tenant_id, kind, serial_no, model, status)"
                    " VALUES (%s, %s, 'phone', %s, 'test', 'active')", (device, tenant, f"s-{device[:8]}"))
    r = exchange(tok, device)
    assert r.status_code == 200 and r.json()["device_id"] == device and r.json()["core_permissions"] == []


def test_m4_c01_jwks_reread_on_new_key_same_kid_and_on_unknown_kid(_core: jwks.JwksCache,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    s = sign_in()
    assert exchange(s["access_token"]).status_code == 200  # caches the current key
    old = STANDIN.key
    restarted = CoreKey()
    restarted.kid = old.kid  # the core restarted with a new key under the same kid
    monkeypatch.setattr(STANDIN, "key", restarted)
    assert exchange(sign_in()["access_token"]).status_code == 200  # signature failed once -> re-read -> ok
    monkeypatch.setattr(STANDIN, "key", CoreKey())  # a new kid
    assert exchange(sign_in()["access_token"]).status_code == 200
    _core.forced_min_s = 3600  # forced re-reads are rate-limited: a forged kid does not reach the core again
    rotated = CoreKey()
    monkeypatch.setattr(STANDIN, "key", rotated)
    assert exchange(sign_in()["access_token"]).status_code == 401


def test_m4_c01_core_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FIELD_CORE_BASE_URL", "FIELD_CORE_JWKS_URL", "FIELD_CORE_DEVICE_STATUS_URL", "CORE_API_URL"):
        monkeypatch.delenv(name, raising=False)
    assert core.core_base_url() == "http://127.0.0.1:8011"
    assert core.core_jwks_url() == "http://127.0.0.1:8011/v1/core/jwks.json"
    assert core.device_status_template() is None
    monkeypatch.setenv("FIELD_CORE_BASE_URL", "http://127.0.0.1:8000/")
    assert core.core_jwks_url() == "http://127.0.0.1:8000/v1/core/jwks.json"
    monkeypatch.setenv("CORE_API_URL", "http://127.0.0.1:8011/")
    assert core.device_status_template() == ("http://127.0.0.1:8011/api/v1/devices/{device_id}/status", False)
    monkeypatch.setenv("FIELD_CORE_DEVICE_STATUS_URL", STATUS_TPL)
    tpl, is_core = core.device_status_template() or ("", False)
    assert is_core and core.render_device_status_url(tpl, "a b/c", "t&1") == (
        "http://core/v1/core/devices/a%20b%2Fc/status?tenant_id=t%261")
    with pytest.raises(ValueError):
        core.render_device_status_url("http://core/status", "d", "t")


def test_m4_c01_exchanged_approver_may_use_the_spoken_brief() -> None:
    """Integration note (stream M): POST /v1/briefs/spoken needs field.assistant.use. The stand-in approver's core
    token carries the core role key ["approver"] (like the real core, TO_FIELD section 2), which FIELD_CORE_ROLE_MAP
    maps to field.supervisor, which holds it (approvers are never mapped to field.viewer only). Once stream M's route
    is merged into the app, the exchanged approver token calls it: 200, template or model."""
    s = sign_in("approver@demo.scmtips.test")
    data = exchange(s["access_token"]).json()
    assert data["roles"] == ["field.supervisor"] and "field.assistant.use" in data["permissions"]
    assert "voice.approve" in data["core_permissions"]
    paths = {getattr(r, "path", "") for r in app.routes}
    if "/v1/briefs/spoken" in paths:  # present after the integrator merges stream M (feat/m4-router)
        item = core_client.get("/v1/wearable/next", headers={
            "Authorization": f"Bearer {s['wearable']['token']}", "X-Device-Id": s["wearable"]["device_id"]}).json()["item"]
        r = client.post("/v1/briefs/spoken", json={"decision_id": item["decision_id"], "template_text": item["spoken"]},
                        headers={"Authorization": f"Bearer {data['access_token']}", "Idempotency-Key": str(uuid.uuid4()),
                                 "X-Core-Token": s["wearable"]["token"], "X-Device-Id": s["wearable"]["device_id"]})
        assert r.status_code == 200, r.text
        assert r.json()["source"] in ("model", "template")
