"""The core's reply to Field (TO_FIELD, 31 Oct 2026) applied in field-api: core role keys mapped to Field roles at
/v1/auth/exchange (section 2, decision (b)), and ``X-Requested-With: lr`` on every call Field makes to the core
(sections 1 item 6 and 3).

Tokens come from the stand-in core (tools/fake-core, a dev double whose demo users now carry core role keys like the
real core) over HTTP in process. Against the real core all of this is UNVERIFIED (the core is not deployed).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_core.app import app as core_app
from fake_core.standin.state import StandInState
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth import core_roles, jwks
from field_api.auth.core_roles import (
    DEFAULT_CORE_ROLE_MAP,
    RoleMapError,
    map_roles,
    parse_core_role_map,
)
from field_api.auth.jwt import verify_token
from field_api.auth.permissions import ROLE_PERMISSIONS, expand_permissions
from field_api.briefs.core import CoreBriefCheck
from field_api.routes import auth as auth_routes

client = TestClient(app)
core_client = TestClient(core_app)
STANDIN: StandInState = core_app.state.standin
STATUS_TPL = "http://core/v1/core/devices/{device_id}/status?tenant_id={tenant_id}"
APPROVER, OPERATOR = "approver@demo.scmtips.test", "operator@demo.scmtips.test"


@pytest.fixture(autouse=True)
def _core(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache = jwks.JwksCache(jwks_url="http://core/v1/core/jwks.json", transport=httpx.ASGITransport(app=core_app))
    cache.forced_min_s = 0
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.setattr(auth_routes, "CORE_TRANSPORT", httpx.ASGITransport(app=core_app))
    monkeypatch.setenv("FIELD_CORE_DEVICE_STATUS_URL", STATUS_TPL)
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.delenv(core_roles.ENV_VAR, raising=False)
    yield


def sign_in(email: str) -> dict[str, Any]:
    r = core_client.post("/v1/auth/app/token", headers={"X-Requested-With": "lr"}, json={
        "email": email, "password": STANDIN.password, "device_id": f"phone-{uuid.uuid4().hex[:12]}",
        "device_model": "PHONE_ONLY", "client": "scmtips-field"})
    assert r.status_code == 200, r.text
    return dict(r.json())


def core_token(roles: list[str]) -> str:
    token, _ = STANDIN.key.issue({"sub": f"u-{uuid.uuid4().hex[:8]}", "tenant_id": STANDIN.tenant_id, "roles": roles,
                                  "sites": ["*"]}, 600)
    return token


def exchange(token: str) -> httpx.Response:
    return client.post("/v1/auth/exchange", json={"device_token": token})


# -- 1. role mapping ---------------------------------------------------------------------------------------------

def test_m4_c08_default_table_is_the_cores() -> None:
    assert dict(DEFAULT_CORE_ROLE_MAP) == {
        "approver": ("field.supervisor",), "procurement": ("field.operator",), "ops_lead": ("field.supervisor",),
        "team_lead": ("field.supervisor",), "org_admin": ("field.admin",), "integration": ("field.integration",),
        "planner": ("field.viewer",), "analyst": ("field.viewer",)}
    assert all(r in ROLE_PERMISSIONS for vals in DEFAULT_CORE_ROLE_MAP.values() for r in vals)
    # an approver needs a role that holds field.assistant.use (spoken briefs), never field.viewer only
    assert "field.assistant.use" in expand_permissions(list(DEFAULT_CORE_ROLE_MAP["approver"]))
    assert parse_core_role_map("") is DEFAULT_CORE_ROLE_MAP and parse_core_role_map(None) is DEFAULT_CORE_ROLE_MAP


def test_m4_c08_setting_is_json_or_a_file_laid_over_the_default(tmp_path: Path) -> None:
    t = parse_core_role_map('{"procurement": ["field.operator", "inventory.controller"], "planner": [],'
                            ' "buyer": "field.technician"}')
    assert t["procurement"] == ("field.operator", "inventory.controller") and t["buyer"] == ("field.technician",)
    assert "planner" not in t and t["approver"] == ("field.supervisor",)  # others keep the default
    f = tmp_path / "roles.json"
    f.write_text(json.dumps({"analyst": "field.supervisor"}), encoding="utf-8")
    assert parse_core_role_map(str(f))["analyst"] == ("field.supervisor",)
    for bad in ('{"approver": "root"}', '{"approver": 3}', "[1]", "{not json", str(tmp_path / "missing.json"),
                '{"": "field.viewer"}'):
        with pytest.raises(RoleMapError):
            parse_core_role_map(bad)


def test_m4_c08_map_roles_keeps_field_roles_maps_core_keys_ignores_the_rest() -> None:
    m = map_roles(["approver", "field.technician", "mystery", "procurement", "approver"], DEFAULT_CORE_ROLE_MAP)
    assert m.field_roles == ["field.supervisor", "field.technician", "field.operator"]
    assert m.core_roles == ["approver", "procurement", "approver"] and m.ignored == ["mystery"]
    assert map_roles(["planner"], DEFAULT_CORE_ROLE_MAP).field_roles == ["field.viewer"]
    assert map_roles([], DEFAULT_CORE_ROLE_MAP).field_roles == []


def test_m4_c08_stand_in_approver_and_operator_exchange_with_core_role_keys() -> None:
    a = sign_in(APPROVER)
    assert a["claims"]["roles"] == ["approver"]
    ra = exchange(a["access_token"])
    assert ra.status_code == 200, ra.text
    da = ra.json()
    assert da["roles"] == ["field.supervisor"] and da["core_roles"] == ["approver"]
    assert "field.assistant.use" in da["permissions"]  # POST /v1/briefs/spoken stays open to the approver
    assert verify_token(da["access_token"]).roles == ["field.supervisor"]
    assert "decision.read" in da["core_permissions"]
    o = sign_in(OPERATOR)
    do = exchange(o["access_token"]).json()
    assert do["roles"] == ["field.operator"] and do["core_roles"] == ["procurement"]
    assert "field.task.execute" in do["permissions"]


def test_m4_c08_field_role_names_keep_working() -> None:
    r = exchange(core_token(["field.operator"]))
    assert r.status_code == 200 and r.json()["roles"] == ["field.operator"] and r.json()["core_roles"] == []


def test_m4_c08_nothing_maps_is_a_clear_403_not_a_bare_401() -> None:
    for roles in (["mystery"], [], ["root", "guest"]):
        r = exchange(core_token(roles))
        assert r.status_code == 403, (roles, r.text)
        body = r.json()
        assert body["code"] == "FIELD-AUTH-403-NO-FIELD-ROLE" and body["title"] == "No SCMTips Field role"
        assert "approver or procurement" in body["detail"]
        assert all(x in body["detail"] for x in roles)


def test_m4_c08_the_owner_can_map_another_core_role(monkeypatch: pytest.MonkeyPatch) -> None:
    assert exchange(core_token(["buyer"])).status_code == 403
    monkeypatch.setenv(core_roles.ENV_VAR, '{"buyer": "field.operator"}')
    r = exchange(core_token(["buyer"]))
    assert r.status_code == 200 and r.json()["roles"] == ["field.operator"] and r.json()["core_roles"] == ["buyer"]
    monkeypatch.setenv(core_roles.ENV_VAR, '{"approver": []}')  # unmapped by the owner
    assert exchange(sign_in(APPROVER)["access_token"]).json()["code"] == "FIELD-AUTH-403-NO-FIELD-ROLE"


def test_m4_c08_a_broken_setting_refuses_every_core_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(core_roles.ENV_VAR, '{"approver": "root"}')
    r = exchange(core_token(["approver"]))
    assert r.status_code == 500 and r.json()["code"] == "FIELD-AUTH-500-ROLE-MAP-INVALID"
    assert "FIELD_CORE_ROLE_MAP" in r.json()["detail"]


def test_m4_c08_roles_must_still_be_a_list_of_strings() -> None:
    for roles in ("approver", [1], None):
        token, _ = STANDIN.key.issue({"sub": "u1", "tenant_id": STANDIN.tenant_id, "roles": roles, "sites": ["*"]}, 600)
        assert exchange(token).status_code == 401, roles


# -- 2. X-Requested-With: lr on every call to the core ----------------------------------------------------------

def test_m4_c09_device_status_and_jwks_calls_carry_requested_with(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    inner = httpx.ASGITransport(app=core_app)

    class Recording(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return await inner.handle_async_request(request)

    cache = jwks.JwksCache(jwks_url="http://core/v1/core/jwks.json", transport=Recording())
    monkeypatch.setattr(jwks, "jwks_cache", cache)
    monkeypatch.setattr(auth_routes, "CORE_TRANSPORT", Recording())
    assert exchange(sign_in(OPERATOR)["access_token"]).status_code == 200
    paths = {r.url.path for r in seen}
    assert "/v1/core/jwks.json" in paths and any(p.endswith("/status") for p in paths)
    assert all(r.headers.get("x-requested-with") == "lr" for r in seen)


def test_m4_c09_brief_check_against_the_stand_in_needs_the_header_and_decision_read() -> None:
    """field-api's brief-check client against the stand-in core, which (like the real core) answers 403 without
    X-Requested-With: lr and without decision.read: the client sends the header; the approver has decision.read."""
    a = sign_in(APPROVER)
    w = a["wearable"]
    item = core_client.get("/v1/wearable/next", headers={"Authorization": f"Bearer {w['token']}",
                                                          "X-Device-Id": w["device_id"]}).json()["item"]
    checker = CoreBriefCheck("http://core", transport=_SyncAsgi())
    ok = checker.check(item["decision_id"], item["spoken"], core_token=w["token"], device_id=w["device_id"])
    assert ok.accepted is True and ok.reasons == []
    o = sign_in(OPERATOR)["wearable"]
    no = checker.check(item["decision_id"], item["spoken"], core_token=o["token"], device_id=o["device_id"])
    assert no.accepted is False and no.reasons == ["core:http_403"]  # procurement has no decision.read
    bare = core_client.post(f"/v1/briefs/decision/{item['decision_id']}/check", json={"text": item["spoken"]},
                            headers={"Authorization": f"Bearer {w['token']}", "X-Device-Id": w["device_id"]})
    assert bare.status_code == 403 and bare.json()["code"] == "missing_requested_with"


class _SyncAsgi(httpx.BaseTransport):
    """The stand-in core app behind a sync httpx transport (CoreBriefCheck uses a sync client)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = core_client.request(request.method, request.url.path, content=request.content,
                                headers=dict(request.headers))
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)
