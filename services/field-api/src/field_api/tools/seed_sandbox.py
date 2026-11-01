"""Hosted sandbox seed (M5-H01): the "Home (sandbox)" site the phone's grocery / pharmacy starters need.

On the hosted deployment (scmtips.com) the tenant is the real SCMTIPS core's organisation (SAMPLE). It has no sandbox
site, erp-sim has no plant HOME and no storage locations 101A / 101Q, so ``POST /v1/sandbox/cases`` (Today's "New
grocery delivery" / "New pharmacy delivery") cannot run there. The dev stack makes them with fake-core tokens and
direct database writes (tools/dev_stack/stack.py ``ensure_home``, tools/dev_stack/m5.py ``ensure_case_slocs``); this
command makes the same things on a real deployment through real APIs only:

1. signs in at the core as an organisation admin: ``POST {core}/v1/auth/app/token`` (``X-Requested-With: lr``,
   e-mail + password, device id ``web-console:field-sandbox-seed``, device model ``WEB_CONSOLE``, client
   ``scmtips-field``), exactly as the hosted console's server does (M5-J01);
2. exchanges that token at field-api: ``POST {field}/v1/auth/exchange`` with ``client_id: field-console`` and no device
   id (an unbound field token); the core role ``org_admin`` maps to ``field.admin`` (field_api.auth.core_roles), which
   is required: anything else fails;
3. ensures plant HOME with storage locations HM01 (home shelf), FIELD_CASE_SLOC (default 101A, unrestricted) and
   FIELD_QUALITY_SLOC (default 101Q, quality area) in the ERP through the sandbox port chosen by config
   (FIELD_ERP_ADAPTER, FIELD_ERP_SIM_URL: erp-sim's ``POST /_sim/sandbox/plants`` with ERPSIM_ADMIN_TOKEN; the S/4
   adapter refuses, a sandbox is not an SAP capability);
4. ensures the site HOME-SBX "Home (sandbox)" (``POST /v1/sites``, mode sandbox, plant HOME, those storage
   locations; an existing one gains missing storage locations by ``PATCH`` with If-Match), its zone HOME and bins
   HOME-A / HOME-B (``POST /v1/locations``, erp_ref HOME/HM01/<bin>);
5. prints what exists, and which site a phone signed in through the core opens: the first one GET /v1/sites lists
   (apps/field-android SiteChoice; the core's tokens carry ``sites: ["*"]``, and site ids are UUIDv7, so that is the
   tenant's oldest site). A tenant that already had sites gets a ``NOTE phone:`` line: the phone opens that site
   first, and Me -> Site -> Change (M5-H05) switches it to the sandbox site, where Today's grocery / pharmacy
   starters show.

Idempotent: a second run creates nothing and prints what is there. Exit 0 when everything exists afterwards, 1 on any
failure (the reason on stderr). No database is written directly; no dev stand-in is called.

Run inside the field-api container (its environment already holds FIELD_CORE_BASE_URL, FIELD_ERP_SIM_URL and
ERPSIM_ADMIN_TOKEN)::

    SEED_ADMIN_PASSWORD=... python -m field_api.tools.seed_sandbox --admin-email <org admin e-mail>

Options: ``--core-url`` (default FIELD_CORE_BASE_URL), ``--field-url`` (default FIELD_SEED_FIELD_API_URL, else
http://127.0.0.1:8020, the image's uvicorn), ``--erp-sim-url`` (default FIELD_ERP_SIM_URL), ``--password-env`` (the
NAME of the variable holding the password, default SEED_ADMIN_PASSWORD; the value is never printed or logged).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TextIO

import httpx
from field_sap.ports.erp_port import ErpError, ErpSandboxPort

from field_api.auth.core import CORE_HEADERS, core_base_url
from field_api.sandbox import erp
from field_api.vision.cases import case_sloc
from field_api.warehouse.receiving.post import quality_storage_location

SITE_CODE = "HOME-SBX"
SITE_NAME = "Home (sandbox)"
PLANT = "HOME"
PLANT_NAME = "Home (sandbox)"
HOME_SLOC = "HM01"
ZONE = "HOME"
BINS = ("HOME-A", "HOME-B")
# The core binds its token to a device id; a ``web-console:`` id exchanged with client_id field-console gets an
# unbound field token (field_api.routes.auth.is_web_console). Stable, so repeated runs reuse one core device entry.
DEVICE_ID = "web-console:field-sandbox-seed"
DEVICE_MODEL = "WEB_CONSOLE"
CORE_CLIENT = "scmtips-field"
FIELD_CLIENT_ID = "field-console"
DEFAULT_FIELD_URL = "http://127.0.0.1:8020"
DEFAULT_PASSWORD_ENV = "SEED_ADMIN_PASSWORD"
TIMEOUT_S = 15.0


class SeedError(Exception):
    """A step failed; the message says which and why (never a secret)."""


def storage_locations() -> tuple[tuple[str, str], ...]:
    """(code, name) of the home site's storage locations: the M3 home shelf, then the M5 case locations."""
    out: dict[str, str] = {HOME_SLOC: "Home shelf"}
    out.setdefault(case_sloc(), "Home shelf (unrestricted)")
    out.setdefault(quality_storage_location(), "Home quality area")
    return tuple(out.items())


@dataclass
class Report:
    site_id: str = ""
    site_created: bool = False
    phone_site: str | None = None
    site_ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        self.lines.append(line)


def _problem(r: httpx.Response) -> str:
    """A short reason from a problem body (code / title / detail), never the request."""
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}"
    if isinstance(body, dict):
        bits = [str(body[k]) for k in ("code", "title", "detail") if isinstance(body.get(k), str) and body.get(k)]
        if not bits and isinstance(body.get("detail"), (dict, list)):
            bits = [str(body["detail"])[:200]]
        if bits:
            return f"HTTP {r.status_code} " + ": ".join(bits)[:300]
    return f"HTTP {r.status_code}"


def _call(client: httpx.Client, method: str, path: str, what: str, **kw: Any) -> httpx.Response:
    try:
        return client.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise SeedError(f"{what}: {type(e).__name__} reaching {client.base_url}") from None


class Seeder:
    def __init__(self, core: httpx.Client, field_api: httpx.Client, port: ErpSandboxPort,
                 run: Callable[[Any], Any] = erp.run) -> None:
        self.core, self.field, self.port, self.run_erp = core, field_api, port, run
        self.token = ""

    # ------------------------------------------------------------------ sign-in
    def sign_in(self, email: str, password: str, report: Report) -> None:
        r = _call(self.core, "POST", "/v1/auth/app/token", "core sign-in", headers=dict(CORE_HEADERS), json={
            "email": email, "password": password, "device_id": DEVICE_ID, "device_model": DEVICE_MODEL,
            "client": CORE_CLIENT})
        if r.status_code != 200:
            why = {401: "the e-mail or password is not right",
                   429: "too many sign-in attempts; wait a few minutes"}.get(r.status_code, _problem(r))
            raise SeedError(f"core sign-in refused ({why})")
        core_token = r.json().get("access_token")
        if not isinstance(core_token, str) or not core_token:
            raise SeedError("core sign-in answered no access_token")
        x = _call(self.field, "POST", "/v1/auth/exchange", "field-api exchange",
                  json={"device_token": core_token, "client_id": FIELD_CLIENT_ID})
        if x.status_code != 200:
            raise SeedError(f"field-api did not exchange the core token ({_problem(x)})")
        body = x.json()
        roles, perms = list(body.get("roles") or []), list(body.get("permissions") or [])
        if "field.admin" not in roles and "field.*" not in perms:
            raise SeedError(f"{email} is not a Field administrator (Field roles {roles}, core roles"
                            f" {body.get('core_roles')}); sign in with the organisation's org_admin")
        self.token = str(body["access_token"])
        report.site_ids = [str(s) for s in body.get("site_ids") or []]
        report.say(f"signed in: tenant {body.get('tenant_id')}, Field roles {', '.join(roles)}"
                   f" (core roles {', '.join(body.get('core_roles') or [])})")

    def _h(self, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", **extra}

    def _post(self, path: str, body: Mapping[str, Any], what: str) -> dict[str, Any]:
        r = _call(self.field, "POST", path, what, json=dict(body),
                  headers=self._h(**{"Idempotency-Key": str(uuid.uuid4())}))
        if r.status_code != 201:
            raise SeedError(f"{what}: {_problem(r)}")
        return dict(r.json())

    # ------------------------------------------------------------------ ERP
    def ensure_plant(self, slocs: Sequence[tuple[str, str]], report: Report) -> None:
        try:
            p = self.run_erp(self.port.ensure_sandbox_plant(PLANT, PLANT_NAME, slocs))
        except ErpError as e:
            raise SeedError(f"ERP plant {PLANT}: {e.code or e.kind}: {e.message}") from None
        added = [s.storage_location for s in p.storage_locations if s.created]
        have = [s.storage_location for s in p.storage_locations]
        report.say(f"ERP plant {p.plant} ({p.name}): {'created' if p.created else 'exists'}; storage locations"
                   f" {', '.join(have)}" + (f" ({', '.join(added)} added)" if added else " (all existed)"))

    # ------------------------------------------------------------------ site
    def ensure_site(self, slocs: Sequence[str], report: Report) -> None:
        r = _call(self.field, "GET", f"/v1/sites/{SITE_CODE}", "read the site", headers=self._h())
        if r.status_code == 404:
            site = self._post("/v1/sites", {"code": SITE_CODE, "name": SITE_NAME, "kind": "warehouse",
                                            "erp_plant": PLANT, "erp_storage_locations": list(slocs),
                                            "mode": "sandbox"}, f"create site {SITE_CODE}")
            report.site_id, report.site_created = str(site["id"]), True
            report.say(f"site {SITE_NAME!r} ({report.site_id}): created, mode sandbox, plant {PLANT},"
                       f" storage locations {', '.join(slocs)}")
            return
        if r.status_code != 200:
            raise SeedError(f"read site {SITE_CODE}: {_problem(r)}")
        site = dict(r.json())
        report.site_id = str(site["id"])
        if site.get("mode") != "sandbox" or site.get("erp_plant") != PLANT:
            raise SeedError(f"site {SITE_CODE} exists with mode {site.get('mode')} and plant {site.get('erp_plant')},"
                            f" not sandbox on {PLANT}; fix it in the console (Sites) and run again")
        have = list(site.get("erp_storage_locations") or [])
        missing = [s for s in slocs if s not in have]
        if missing:
            p = _call(self.field, "PATCH", f"/v1/sites/{report.site_id}", "update the site",
                      json={"erp_storage_locations": have + missing},
                      headers=self._h(**{"If-Match": r.headers.get("ETag", "")}))
            if p.status_code != 200:
                raise SeedError(f"add storage locations {missing} to site {SITE_CODE}: {_problem(p)}")
            have = list(p.json().get("erp_storage_locations") or [])
        report.say(f"site {site.get('name')!r} ({report.site_id}): exists, mode sandbox, plant {PLANT}, storage"
                   f" locations {', '.join(have)}" + (f" ({', '.join(missing)} added)" if missing else ""))

    def _locations(self, site_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        cursor: str | None = None
        while True:
            params = {"site_id": site_id, "limit": "200", **({"cursor": cursor} if cursor else {})}
            r = _call(self.field, "GET", "/v1/locations", "list locations", params=params, headers=self._h())
            if r.status_code != 200:
                raise SeedError(f"list the locations of {SITE_CODE}: {_problem(r)}")
            body = r.json()
            out.update({str(i["code"]): str(i["id"]) for i in body.get("items") or []})
            cursor = body.get("next_cursor")
            if not cursor:
                return out

    def ensure_bins(self, report: Report) -> None:
        have = self._locations(report.site_id)
        made: list[str] = []
        if ZONE not in have:
            have[ZONE] = str(self._post("/v1/locations", {"site_id": report.site_id, "kind": "zone", "code": ZONE},
                                        f"create zone {ZONE}")["id"])
            made.append(ZONE)
        for b in BINS:
            if b in have:
                continue
            self._post("/v1/locations", {"site_id": report.site_id, "parent_id": have[ZONE], "kind": "position",
                                         "code": b, "erp_ref": f"{PLANT}/{HOME_SLOC}/{b}",
                                         "erp_ref_type": "storage_bin"}, f"create bin {b}")
            made.append(b)
        report.say(f"zone {ZONE}, bins {', '.join(BINS)}: " + (f"{', '.join(made)} created" if made else "exist"))

    def phone_site(self, report: Report) -> None:
        """The site a core-signed-in phone opens: the first of its token's sites that GET /v1/sites lists, else the
        first listed (apps/field-android SiteChoice.pick, GET /v1/sites?limit=200)."""
        r = _call(self.field, "GET", "/v1/sites", "list sites", params={"limit": "200"}, headers=self._h())
        if r.status_code != 200:
            raise SeedError(f"list sites: {_problem(r)}")
        items = [dict(i) for i in r.json().get("items") or []]
        pick = next((i for s in report.site_ids for i in items if str(i.get("id")) == s), items[0] if items else None)
        report.phone_site = str(pick["id"]) if pick else None
        if pick is None or report.phone_site == report.site_id:
            report.say(f"phone: a member signed in through SCMTIPS opens {SITE_NAME!r} (the first site listed)")
        else:
            others = len(items) - 1
            report.say(f"NOTE phone: a member signed in through SCMTIPS first opens {pick.get('name')!r}"
                       f" ({pick.get('code')}, mode {pick.get('mode')}), the oldest of the {others + 1} sites listed;"
                       f" on the phone, Me -> Site -> Change to {SITE_NAME!r} (the choice is kept until sign-out) to see"
                       " the grocery / pharmacy starters")

    def run(self, email: str, password: str) -> Report:
        report = Report()
        slocs = storage_locations()
        self.sign_in(email, password, report)
        self.ensure_plant(slocs, report)
        self.ensure_site([s for s, _ in slocs], report)
        self.ensure_bins(report)
        self.phone_site(report)
        report.say(f"cases: POST /v1/sandbox/cases {{site_id: {report.site_id}, case: grocery|pharmacy}}; good units"
                   f" to {case_sloc()}, flagged to {quality_storage_location()}; core token sites"
                   f" {report.site_ids or ['(none)']}; needs field.task.execute (core procurement -> field.operator,"
                   " org_admin -> field.admin; approver -> field.supervisor cannot start a case)")
        return report


def parse_args(argv: Sequence[str] | None, env: Mapping[str, str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m field_api.tools.seed_sandbox",
                                 description="Create the hosted 'Home (sandbox)' site through real APIs (M5-H01).")
    ap.add_argument("--admin-email", required=True, help="the core organisation admin (core role org_admin)")
    ap.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV,
                    help=f"NAME of the environment variable holding the password (default {DEFAULT_PASSWORD_ENV})")
    ap.add_argument("--core-url", default=None, help="the SCMTIPS core (default FIELD_CORE_BASE_URL)")
    ap.add_argument("--field-url", default=env.get("FIELD_SEED_FIELD_API_URL") or DEFAULT_FIELD_URL,
                    help=f"field-api (default FIELD_SEED_FIELD_API_URL, else {DEFAULT_FIELD_URL})")
    ap.add_argument("--erp-sim-url", default=None, help="erp-sim (default FIELD_ERP_SIM_URL)")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, out: TextIO | None = None,
         err: TextIO | None = None, transport: httpx.BaseTransport | None = None,
         port: ErpSandboxPort | None = None) -> int:
    env = os.environ if env is None else env
    out, err = out or sys.stdout, err or sys.stderr
    a = parse_args(argv, env)
    password = env.get(a.password_env, "")
    if not password:
        print(f"FAIL: the environment variable {a.password_env} (the admin's password) is not set", file=err)
        return 1
    core_url = (a.core_url or core_base_url()).rstrip("/")
    with httpx.Client(base_url=core_url, timeout=TIMEOUT_S, transport=transport) as core, \
            httpx.Client(base_url=a.field_url.rstrip("/"), timeout=TIMEOUT_S, transport=transport) as field_api:
        seeder = Seeder(core, field_api, port or erp.get_sandbox_port(a.erp_sim_url))
        try:
            report = seeder.run(a.admin_email, password)
        except SeedError as e:
            print(f"FAIL: {e}", file=err)
            return 1
    for line in report.lines:
        print(line, file=out)
    print(f"sandbox seed complete: site {report.site_id} ({'created' if report.site_created else 'existed'})",
          file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
