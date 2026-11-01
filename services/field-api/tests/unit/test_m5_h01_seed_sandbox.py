"""M5-H01: the hosted sandbox seed's flow, idempotency and failures (field_api.tools.seed_sandbox).

The core and field-api are an httpx MockTransport that keeps sites and locations like the real routes do (code
lookup, 409-free create, ETag / If-Match on PATCH, cursor pages); the ERP is a sandbox-port test double. The real
APIs end to end are in tests/e2e/test_m5_h01_seed_sandbox_e2e.py.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from field_api.tools import seed_sandbox
from field_sap.ports.erp_port import (
    SANDBOX_NOT_SAP,
    ErpError,
    ErpErrorKind,
    SandboxDelivery,
    SandboxDeliveryItem,
    SandboxMaterial,
    SandboxPlant,
    SandboxStorageLocation,
)

pytestmark = pytest.mark.unit

CORE, FIELD = "http://core.test", "http://field.test"
PASSWORD = "seed-test-" + uuid.uuid4().hex  # a value the output must never contain
TENANT = "6b1f6a4e-0000-4000-8000-000000000001"


class FakeSandboxPort:
    """ErpSandboxPort test double: plants and storage locations in memory, or a refusal."""

    def __init__(self, refuse: bool = False) -> None:
        self.plants: dict[str, tuple[str, dict[str, str]]] = {}
        self.refuse = refuse
        self.calls = 0

    async def ensure_sandbox_plant(self, plant: str, name: str,
                                   storage_locations: Sequence[tuple[str, str]]) -> SandboxPlant:
        self.calls += 1
        if self.refuse:
            raise ErpError(kind=ErpErrorKind.BUSINESS, code=SANDBOX_NOT_SAP, message="not an SAP capability")
        created = plant not in self.plants
        pname, slocs = self.plants.setdefault(plant, (name, {}))
        out = []
        for code, sl_name in storage_locations:
            new = code not in slocs
            slocs.setdefault(code, sl_name)
            out.append(SandboxStorageLocation(code, slocs[code], new))
        return SandboxPlant(plant, pname, created, tuple(out))

    async def create_sandbox_material(self, plant: str, description: str, base_uom: str,
                                      barcode: str) -> SandboxMaterial:
        raise AssertionError("the seed makes no material")

    async def create_sandbox_inbound_delivery(self, plant: str, storage_location: str, supplier: str,
                                              simulated: bool = False) -> SandboxDelivery:
        raise AssertionError("the seed makes no delivery")

    async def add_sandbox_inbound_delivery_item(self, delivery_document: str, material: str, quantity: str,
                                                uom: str, idempotency_key: str) -> SandboxDeliveryItem:
        raise AssertionError("the seed makes no delivery item")


class World:
    """The core and field-api as the seed sees them over HTTP."""

    def __init__(self, roles: list[str] | None = None, core_status: int = 200) -> None:
        self.roles = roles or ["field.admin"]
        self.core_status = core_status
        self.sites: dict[str, dict[str, Any]] = {}
        self.locations: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []

    def add_site(self, code: str, name: str, mode: str = "sandbox", plant: str = "HOME",
                 slocs: list[str] | None = None, site_id: str | None = None) -> str:
        sid = site_id or str(uuid.uuid4())
        self.sites[sid] = {"id": sid, "code": code, "name": name, "mode": mode, "erp_plant": plant,
                           "erp_storage_locations": slocs or [], "version": 1}
        return sid

    def writes(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        host, path = f"{req.url.scheme}://{req.url.host}", req.url.path
        body = json.loads(req.content) if req.content else {}
        if host == CORE and path == "/v1/auth/app/token":
            if self.core_status != 200:
                return httpx.Response(self.core_status, json={"code": "invalid_credentials"})
            return httpx.Response(200, json={"access_token": "core-token", "token_type": "Bearer"})
        assert host == FIELD, req.url
        if path == "/v1/auth/exchange":
            assert body == {"device_token": "core-token", "client_id": "field-console"}
            perms = ["field.*"] if "field.admin" in self.roles else ["field.task.execute"]
            return httpx.Response(200, json={"access_token": "field-token", "roles": self.roles, "permissions": perms,
                                             "tenant_id": TENANT, "site_ids": ["*"], "core_roles": ["org_admin"]})
        assert req.headers["Authorization"] == "Bearer field-token"
        if req.method == "POST":
            assert req.headers.get("Idempotency-Key")
        if path == "/v1/sites" and req.method == "GET":
            return httpx.Response(200, json={"items": sorted(self.sites.values(), key=lambda s: s["id"]),
                                             "next_cursor": None, "total_in_page": len(self.sites)})
        if path == "/v1/sites" and req.method == "POST":
            sid = self.add_site(body["code"], body["name"], body["mode"], body["erp_plant"],
                                list(body["erp_storage_locations"]))
            return httpx.Response(201, json=self.sites[sid])
        if path.startswith("/v1/sites/"):
            ref = path.rsplit("/", 1)[1]
            site = next((s for s in self.sites.values() if ref in (s["id"], s["code"])), None)
            if site is None:
                return httpx.Response(404, json={"code": "FIELD-SITE-404-NOT-FOUND", "title": "Site not found"})
            if req.method == "PATCH":
                if req.headers.get("If-Match") != f'W/"{site["version"]}"':
                    return httpx.Response(412, json={"code": "FIELD-HTTP-412-PRECONDITION"})
                site.update(body, version=site["version"] + 1)
            return httpx.Response(200, json=site, headers={"ETag": f'W/"{site["version"]}"'})
        if path == "/v1/locations" and req.method == "GET":
            mine = sorted((x for x in self.locations.values() if x["site_id"] == req.url.params["site_id"]),
                          key=lambda x: x["id"])
            start = int(req.url.params.get("cursor") or 0)
            page = mine[start:start + 2]  # two per page, so the seed must follow next_cursor
            nxt = str(start + 2) if start + 2 < len(mine) else None
            return httpx.Response(200, json={"items": page, "next_cursor": nxt, "total_in_page": len(page)})
        if path == "/v1/locations" and req.method == "POST":
            lid = str(uuid.uuid4())
            self.locations[lid] = {"id": lid, **body}
            return httpx.Response(201, json=self.locations[lid])
        raise AssertionError(f"unexpected {req.method} {req.url}")


def run(world: World, port: FakeSandboxPort | None = None, env: dict[str, str] | None = None,
        extra: list[str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = seed_sandbox.main(
        ["--admin-email", "admin@sample.test", "--core-url", CORE, "--field-url", FIELD, *(extra or [])],
        env={"SEED_ADMIN_PASSWORD": PASSWORD} if env is None else env, out=out, err=err,
        transport=httpx.MockTransport(world.handler), port=port or FakeSandboxPort())
    return code, out.getvalue(), err.getvalue()


def test_m5_h01_first_run_creates_plant_site_slocs_zone_and_bins() -> None:
    world, port = World(), FakeSandboxPort()
    code, out, err = run(world, port)
    assert code == 0, err
    assert port.plants["HOME"][0] == "Home (sandbox)"
    assert list(port.plants["HOME"][1]) == ["HM01", "101A", "101Q"]
    site = next(iter(world.sites.values()))
    assert (site["code"], site["name"], site["mode"], site["erp_plant"], site["erp_storage_locations"]) == (
        "HOME-SBX", "Home (sandbox)", "sandbox", "HOME", ["HM01", "101A", "101Q"])
    locs = {x["code"]: x for x in world.locations.values()}
    assert set(locs) == {"HOME", "HOME-A", "HOME-B"}
    zone = locs["HOME"]["id"]
    assert [(locs[b]["parent_id"], locs[b]["erp_ref"], locs[b]["erp_ref_type"]) for b in ("HOME-A", "HOME-B")] == [
        (zone, "HOME/HM01/HOME-A", "storage_bin"), (zone, "HOME/HM01/HOME-B", "storage_bin")]
    sign_in = json.loads(world.writes("POST", "/v1/auth/app/token")[0].content)
    assert sign_in["device_id"].startswith("web-console:") and sign_in["device_model"] == "WEB_CONSOLE"
    assert sign_in["client"] == "scmtips-field" and sign_in["email"] == "admin@sample.test"
    assert world.writes("POST", "/v1/auth/app/token")[0].headers["X-Requested-With"] == "lr"
    assert f"site 'Home (sandbox)' ({site['id']}): created" in out
    assert "101A" in out and "101Q" in out and f"site {site['id']} (created)" in out
    assert "opens 'Home (sandbox)'" in out and "WARNING" not in out
    assert PASSWORD not in out + err


def test_m5_h01_second_run_creates_nothing_and_prints_what_exists() -> None:
    world, port = World(), FakeSandboxPort()
    assert run(world, port)[0] == 0
    before = len(world.requests)
    code, out, err = run(world, port)
    assert code == 0, err
    again = world.requests[before:]
    assert [r for r in again if r.method in ("POST", "PATCH") and r.url.path not in (
        "/v1/auth/app/token", "/v1/auth/exchange")] == []
    assert len(world.sites) == 1 and len(world.locations) == 3
    assert "(all existed)" in out and ": exists, mode sandbox" in out and "bins HOME-A, HOME-B: exist" in out
    assert "(existed)" in out


def test_m5_h01_an_existing_site_gains_missing_storage_locations_with_if_match() -> None:
    world = World()
    sid = world.add_site("HOME-SBX", "Home (sandbox)", slocs=["HM01"])
    code, out, err = run(world)
    assert code == 0, err
    assert world.sites[sid]["erp_storage_locations"] == ["HM01", "101A", "101Q"]
    patch = world.writes("PATCH", f"/v1/sites/{sid}")[0]
    assert patch.headers["If-Match"] == 'W/"1"'
    assert "(101A, 101Q added)" in out


def test_m5_h01_case_and_quality_slocs_follow_the_field_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CASE_SLOC", "201A")
    monkeypatch.setenv("FIELD_QUALITY_SLOC", "201Q")
    world, port = World(), FakeSandboxPort()
    assert run(world, port)[0] == 0
    assert list(port.plants["HOME"][1]) == ["HM01", "201A", "201Q"]


def test_m5_h01_the_phone_opening_another_site_is_a_warning() -> None:
    world = World()
    world.add_site("PLANT-GOA", "Goa plant", mode="production", plant="PLANT-GOA",
                   site_id="00000000-0000-4000-8000-000000000001")  # sorts before any random id
    code, out, err = run(world)
    assert code == 0, err
    assert "WARNING phone: a member signed in through SCMTIPS opens 'Goa plant' (PLANT-GOA, mode production)" in out


@pytest.mark.parametrize(("world", "port", "env", "why"), [
    (World(roles=["field.operator"]), None, None, "is not a Field administrator"),
    (World(core_status=401), None, None, "core sign-in refused (the e-mail or password is not right)"),
    (World(core_status=429), None, None, "too many sign-in attempts"),
    (World(), FakeSandboxPort(refuse=True), None, "ERP plant HOME: FIELD_SANDBOX_NOT_SAP"),
    (World(), None, {}, "SEED_ADMIN_PASSWORD (the admin's password) is not set"),
])
def test_m5_h01_failures_exit_non_zero_with_the_reason(world: World, port: FakeSandboxPort | None,
                                                       env: dict[str, str] | None, why: str) -> None:
    code, out, err = run(world, port, env)
    assert code == 1 and why in err and out == ""
    assert world.sites == {} and world.locations == {}
    assert PASSWORD not in err


def test_m5_h01_a_production_site_with_the_code_is_never_changed() -> None:
    world = World()
    sid = world.add_site("HOME-SBX", "Someone's site", mode="production", plant="1010", slocs=["0001"])
    code, _, err = run(world)
    assert code == 1 and "exists with mode production and plant 1010" in err
    assert world.sites[sid]["erp_storage_locations"] == ["0001"] and world.writes("PATCH", f"/v1/sites/{sid}") == []


def test_m5_h01_password_comes_from_the_named_variable_only() -> None:
    world = World()
    code, _, err = run(world, env={"OTHER_NAME": PASSWORD}, extra=["--password-env", "OTHER_NAME"])
    assert code == 0, err
    assert json.loads(world.writes("POST", "/v1/auth/app/token")[0].content)["password"] == PASSWORD


def test_m5_h01_unreachable_core_is_a_failure() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    out, err = io.StringIO(), io.StringIO()
    code = seed_sandbox.main(["--admin-email", "a@b.test", "--core-url", CORE, "--field-url", FIELD],
                             env={"SEED_ADMIN_PASSWORD": PASSWORD}, out=out, err=err,
                             transport=httpx.MockTransport(down), port=FakeSandboxPort())
    assert code == 1 and "core sign-in: ConnectError reaching http://core.test" in err.getvalue()
