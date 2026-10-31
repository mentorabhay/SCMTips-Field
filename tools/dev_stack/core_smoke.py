"""`stack smoke --core` and `stack smoke --approver` against the REAL SCMTIPS core (FIELD_CORE_TARGET=core).

The stand-in smokes (stack.smoke_core / stack.smoke_approver) reset and read the stand-in through its /_standin dev
helpers. The real core has no such helpers, so these smokes use only the core's own API, as its users would:

- app sign-in ``POST /v1/auth/app/token`` (``X-Requested-With: lr`` on every call, TO_FIELD section 3), the core JWKS
  ``/v1/core/jwks.json`` and device status ``FIELD_CORE_DEVICE_STATUS_URL`` (template, 01a);
- core web sign-in ``POST /v1/auth/login`` (cookie session) for the reads a member would make on the web:
  ``/v1/open-supply``, ``/v1/inventory``, ``/v1/pipeline/runs``, ``/v1/plan``, ``/v1/decisions/{id}``;
- the approver's device token on ``/v1/wearable/next``, ``/v1/voice/challenges``, ``/v1/voice/commands``,
  ``/v1/auth/step-up``, ``/v1/briefs/decision/{id}/check`` (through Field's own CoreBriefCheck client), and
  ``DELETE /v1/wearable/sessions/{id}`` for the revocation step.

When no decision waits for the approver, the planner opens one on the demo's sample scenarios (``POST /v1/decisions``)
and submits it, as on the web. With ``--scenario <name>`` (M4-C16) the decision comes from a disruption instead: the
core's SAMPLE scenario file (``FIELD_CORE_SCENARIOS_DIR``, the core checkout's ``samples/scenarios``) is sent as the
signals workbook to the core's own file-mode API by its Org admin (``POST /v1/exchange/messages/signal/import-file``),
the core's pipeline matches, scores and auto-drafts the decision, the planner submits it, and the approver approves
exactly that decision ("approve option two").

The GR goes against one of the core's own PO lines. When erp-sim was seeded from the core's export (``stack
seed-core-export``, M4 Q9) it holds that PO under the core's ref, with the core's item and plant codes: the smoke then
receives the PO's open ASN at the site pack's Field site for that plant, and no code map is used ("export mode"). Only
when erp-sim does not hold the core's POs does it fall back to FIELD_CORE_CODE_MAP ("code-map mode", K1).

Settings (git-ignored ``.env.local``; names only here, A-02): ``FIELD_CORE_BASE_URL``, ``FIELD_CORE_JWKS_URL``,
``FIELD_CORE_DEVICE_STATUS_URL``, the feed URLs/secrets, ``FIELD_CORE_CODE_MAP`` (code-map mode only: its
``purchase_orders`` entry names the erp-sim PO the GR is posted against, its ``materials`` / ``locations`` entries the
erp-sim material and plant of that core PO line), and the core's demo members ``FIELD_CORE_SMOKE_OPERATOR`` / ``_APPROVER`` / ``_ADMIN`` / ``_PLANNER``,
each with ``..._PASSWORD``. Optional: ``FIELD_CORE_SMOKE_PO`` (which mapped erp-sim PO to use) and
``FIELD_CORE_SMOKE_APPROVER_TOTP_SECRET`` (only when the core asks for a step-up: strict sign-in on). In export mode
``FIELD_CORE_SMOKE_PO`` is the core's PO ref (e.g. ``PO-26-1002``).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import struct
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from tools.dev_stack import stack
from tools.dev_stack.stack import SmokeFailure, _accepted, _expect

__all__ = ["SmokeFailure", "scenario_csv", "smoke_approver_real", "smoke_core_real"]

LR = {"X-Requested-With": "lr"}  # on every call to the core (TO_FIELD section 3)
ROLES = ("OPERATOR", "APPROVER", "ADMIN", "PLANNER")
CORE_SITE_PREFIX = "CORE-"
CORE_SLOC = "101A"
# The core's decision statuses after an approval (lr_api.domain.decisions.service): a fully approved decision is
# APPROVED and, with its plan committed and actions created, EXECUTING at once; a two-person band PARTIALLY_APPROVED.
APPROVED_STATES = ("APPROVED", "EXECUTING", "PARTIALLY_APPROVED")


def core_base() -> str:
    base = os.environ.get("FIELD_CORE_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise SmokeFailure("FIELD_CORE_BASE_URL is not set (FIELD_CORE_TARGET=core needs the core's address)")
    return base


def member(role: str) -> tuple[str, str]:
    """(e-mail, password) of one of the core's demo members, from .env.local; a clear failure when unset."""
    email = os.environ.get(f"FIELD_CORE_SMOKE_{role}", "").strip()
    password = os.environ.get(f"FIELD_CORE_SMOKE_{role}_PASSWORD", "")
    if not email or not password:
        raise SmokeFailure(f"set FIELD_CORE_SMOKE_{role} and FIELD_CORE_SMOKE_{role}_PASSWORD in .env.local (the core's"
                           f" demo {role.lower()}; values from the core kit's `scmtips-local-demo --print`)")
    return email, password


def totp_now(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP (SHA-1, 30 s, 6 digits), the authenticator the core enrols; for a strict-mode step-up only."""
    key = base64.b32decode(secret_b32.strip().replace(" ", "").upper() + "=" * (-len(secret_b32.strip()) % 8))
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10**digits
    return f"{code:0{digits}d}"


class Reader(Protocol):
    def get(self, path: str, **params: Any) -> Any: ...


class CoreWeb:
    """A member's signed-in web session at the core (cookie), for the reads and the decision preparation."""

    def __init__(self, base: str, role: str) -> None:
        self.email, password = member(role)
        self.c = httpx.Client(base_url=base, headers=LR, timeout=30)
        r = self.c.post("/v1/auth/login", json={"email": self.email, "password": password})
        body = _accepted(r, f"core web sign-in of {self.email}")
        if body.get("mfa_required"):
            raise SmokeFailure(f"{self.email}: the core asks for an authenticator code at sign-in (strict sign-in on);"
                               " these smokes sign in with e-mail and password (LR_ENV=local or staging)")

    def get(self, path: str, **params: Any) -> Any:
        r = self.c.get(path, params=params)
        if r.status_code != 200:
            raise SmokeFailure(f"core GET {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.c.post(path, json=body)

    def close(self) -> None:
        self.c.close()


def app_sign_in(base: str, role: str, device: str, model: str) -> dict[str, Any]:
    email, password = member(role)
    r = httpx.post(f"{base}/v1/auth/app/token", headers=LR, timeout=15, json={
        "email": email, "password": password, "device_id": device, "device_model": model,
        "display_capable": False, "client": "scmtips-field"})
    return _accepted(r, f"app sign-in of {email} at the core")


def device_status(device: str, tenant: str) -> str:
    tpl = os.environ.get("FIELD_CORE_DEVICE_STATUS_URL", "").strip()
    _expect(bool(tpl), "FIELD_CORE_DEVICE_STATUS_URL is not set")
    r = httpx.get(tpl.format(device_id=device, tenant_id=tenant), headers=LR, timeout=10)
    return str(_accepted(r, "core device status")["status"])


def check_signed_token(base: str, signed: dict[str, Any], core_role: str) -> dict[str, Any]:
    """The core token is the core's (kid in the core JWKS, iss/aud scmtips-core) with the claims Field reads."""
    import jwt

    claims: dict[str, Any] = dict(signed["claims"])
    _expect({"sub", "tenant_id", "roles", "permissions", "email", "device_id"} <= set(claims),
            f"core claims {sorted(claims)}")
    _expect(claims["roles"] == [core_role], f"core roles {claims['roles']}, expected [{core_role!r}]")
    _expect(claims["iss"] == "scmtips-core" and claims["aud"] == "scmtips-core", f"iss/aud {claims}")
    kid = jwt.get_unverified_header(signed["access_token"])["kid"]
    jwks = os.environ.get("FIELD_CORE_JWKS_URL", "").strip() or f"{base}/v1/core/jwks.json"
    kids = {k["kid"] for k in _accepted(httpx.get(jwks, headers=LR, timeout=10), "core JWKS")["keys"]}
    _expect(kid.startswith("scmtips-core-ed25519-") and kid in kids, f"kid {kid} not in the core JWKS {sorted(kids)}")
    return claims


def exchange(api: str, core_token: str, device_id: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"device_token": core_token}
    if device_id:
        body["device_id"] = device_id
    return httpx.post(f"{api}/v1/auth/exchange", json=body, timeout=15)


# --- the core's PO line, mapped to erp-sim through FIELD_CORE_CODE_MAP ---------------------------------------------

def mapped_line(codes: Any, web: Reader) -> dict[str, Any]:
    """The erp-sim PO (FIELD_CORE_SMOKE_PO, else the code map's first PO), the core's open-supply line it maps to,
    and the erp-sim material and plant that map to that line's item and location."""
    pos = dict(codes.purchase_orders)
    _expect(bool(pos), "FIELD_CORE_CODE_MAP has no purchase_orders entry: name the erp-sim PO and the core's PO ref"
                       " (e.g. {\"purchase_orders\": {\"4500261001\": \"PO-26-1001\"}})")
    erp_po = os.environ.get("FIELD_CORE_SMOKE_PO", "").strip() or next(iter(pos))
    _expect(erp_po in pos, f"FIELD_CORE_SMOKE_PO {erp_po} is not in FIELD_CORE_CODE_MAP purchase_orders")
    ref = pos[erp_po]
    lines = [x for x in web.get("/v1/open-supply", limit=200, q=ref).get("items", []) if x.get("ref") == ref]
    if not lines:  # q may not be a filter on every core version: read the pages
        lines = [x for x in _all(web, "/v1/open-supply") if x.get("ref") == ref]
    _expect(len(lines) == 1, f"the core has {len(lines)} open-supply lines with ref {ref} (expected one)")
    line = lines[0]
    item, loc = str(line["item_code"]), str(line["location_code"])
    mats = [m for m, core in codes.materials.items() if core.upper() == item]
    plants = [p for p, core in codes.locations.items() if core.upper() == loc and "/" not in p]
    _expect(len(mats) == 1, f"FIELD_CORE_CODE_MAP materials: no single erp-sim material maps to {item} ({mats})")
    _expect(len(plants) == 1, f"FIELD_CORE_CODE_MAP locations: no single erp-sim plant maps to {loc} ({plants})")
    return {"erp_po": erp_po, "ref": ref, "line": line, "item": item, "location": loc, "material": mats[0],
            "plant": plants[0]}


def erp_holds_core_pos() -> set[str]:
    """The PO numbers erp-sim holds as purchase orders (seeded from the core's export: the core's own refs)."""
    import psycopg

    with psycopg.connect(stack._admin_url("erpsim")) as c, c.cursor() as cur:
        cur.execute("SELECT purchase_order FROM erpsim.purchase_order WHERE client = '100'")
        return {str(r[0]) for r in cur.fetchall()}


def export_line(web: Reader, erp_pos: set[str]) -> dict[str, Any] | None:
    """Export mode: the core's PO line to receive (FIELD_CORE_SMOKE_PO, else the first core PO line erp-sim holds that
    is not received yet), with the codes as they are: erp-sim uses the core's. None when erp-sim holds none of them, or
    when FIELD_CORE_SMOKE_PO names a PO erp-sim does not hold under that number (a code-map PO)."""
    lines = [x for x in _all(web, "/v1/open-supply") if str(x.get("kind", "PO")).upper() == "PO"
             and str(x.get("ref")) in erp_pos]
    if not lines:
        return None
    want = os.environ.get("FIELD_CORE_SMOKE_PO", "").strip()
    if want and want not in erp_pos:  # an erp-sim PO of the code map (code-map mode), not one of the core's refs
        return None
    if want:
        pick = [x for x in lines if x["ref"] == want]
        _expect(len(pick) == 1, f"FIELD_CORE_SMOKE_PO {want}: the core has {len(pick)} PO lines with that ref that"
                                " erp-sim also holds (expected one)")
    else:
        pick = sorted((x for x in lines if x.get("status") != "received"), key=lambda x: str(x["ref"])) or sorted(
            lines, key=lambda x: str(x["ref"]))
    line = pick[0]
    item, loc = str(line["item_code"]), str(line["location_code"])
    return {"erp_po": str(line["ref"]), "ref": str(line["ref"]), "line": line, "item": item, "location": loc,
            "material": item, "plant": loc, "export": True}


def export_site(tenant: str, plant: str) -> tuple[str, str]:
    """(site id, storage location) of the tenant's production Field site on the plant (the site pack's)."""
    import psycopg

    with psycopg.connect(stack._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT id::text, erp_storage_locations FROM field.site WHERE tenant_id = %s AND erp_plant = %s"
                    " AND status = 'active' AND mode = 'production' ORDER BY code = %s DESC, created_at LIMIT 1",
                    (tenant, plant, plant))
        row = cur.fetchone()
    _expect(row is not None, f"no production Field site on plant {plant} in tenant {tenant}: run `stack"
                             " seed-core-export <the core's samples/exports/erp-sim>` (it creates the site pack's sites)")
    assert row is not None
    slocs = list(row[1] or [])
    _expect(bool(slocs), f"the Field site on {plant} names no storage location")
    return str(row[0]), str(slocs[0])


def open_asn(po: str, material: str, plant: str) -> tuple[str, float] | None:
    """An open inbound delivery of the seeded PO with an open item for the material: (delivery, its quantity)."""
    import psycopg

    with psycopg.connect(stack._admin_url("erpsim")) as c, c.cursor() as cur:
        cur.execute("SELECT d.delivery_document, i.delivery_qty FROM erpsim.inbound_delivery d"
                    " JOIN erpsim.inbound_delivery_item i USING (client, delivery_document)"
                    " WHERE d.client = '100' AND d.status = 'open' AND d.plant = %s AND i.purchase_order = %s"
                    " AND i.material_no = %s AND i.status = 'open' ORDER BY d.created_at LIMIT 1",
                    (plant, po, material))
        row = cur.fetchone()
    return (str(row[0]), float(row[1])) if row else None


def _all(web: Reader, path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(50):
        page = web.get(path, limit=200, **({"cursor": cursor} if cursor else {}))
        out += list(page.get("items", []))
        cursor = page.get("next_cursor")
        if not cursor or not page.get("has_more", True):
            return out
    return out


def core_on_hand(web: Reader, item: str, loc: str) -> float | None:
    """The core's current on-hand of an item at a location. The core keeps one inventory row per (item, location,
    as_of): a stock row with today's as_of adds a row next to the sample's older count, so the latest as_of counts."""
    rows = [x for x in _all(web, "/v1/inventory") if x.get("item_code") == item and x.get("location_code") == loc]
    if not rows:
        return None
    return float(max(rows, key=lambda x: str(x.get("as_of")))["on_hand_qty"])


def core_line(web: Reader, ref: str, item: str) -> dict[str, Any] | None:
    rows = [x for x in _all(web, "/v1/open-supply") if x.get("ref") == ref and x.get("item_code") == item]
    return rows[0] if rows else None


def delivery_answers(tenant: str, doc_number: str) -> dict[str, int | None]:
    """The core's last HTTP answer per feed for one goods receipt (field.core_feed_delivery.last_status)."""
    import psycopg

    with psycopg.connect(stack._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT feed, last_status FROM field.core_feed_delivery WHERE tenant_id = %s AND doc_number = %s",
                    (tenant, doc_number))
        return {str(r[0]): (int(r[1]) if r[1] is not None else None) for r in cur.fetchall()}


def ensure_erp_plant(plant: str, name: str) -> None:
    """The erp-sim plant (and storage location 101A) of the core's location, idempotent."""
    import psycopg

    with psycopg.connect(stack._admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, %s) ON CONFLICT DO NOTHING",
                    (plant, name))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES ('100', %s, %s, 'Raw materials') ON CONFLICT DO NOTHING", (plant, CORE_SLOC))


def align_opening_stock(material: str, plant: str, qty: float) -> bool:
    """Dev seed, once: when erp-sim holds no stock of the material at the plant yet, book the core's current on-hand
    there, so the absolute on-hand the GR's stock row carries continues the core's figure. Returns True if seeded."""
    import psycopg

    with psycopg.connect(stack._admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM erpsim.stock WHERE client = '100' AND plant = %s AND material_no = %s",
                    (plant, material))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity)"
                    " VALUES ('100', %s, %s, %s, %s)", (plant, CORE_SLOC, material, qty))
        return True


def ensure_core_site(api: str, base: str, tenant: str, plant: str, loc: str) -> str:
    """A Field warehouse site in the core's organisation on the erp-sim plant, created by the core's Org admin
    (core role org_admin -> field.admin) through field-api, the way the owner would. Reused when it exists."""
    code = f"{CORE_SITE_PREFIX}{plant}"
    site = stack._site_by_code(tenant, code)
    if site:
        return site
    signed = app_sign_in(base, "ADMIN", f"smoke-core-admin-{uuid.uuid4().hex[:8]}", "PHONE_ONLY")
    ex = _accepted(exchange(api, str(signed["access_token"])), "exchange of the core Org admin's token")
    _expect("field.admin" in ex["roles"], f"core org_admin mapped to {ex['roles']}, expected field.admin")
    r = httpx.post(f"{api}/v1/sites", json={
        "code": code, "name": f"Core plant {plant} (the core's {loc})", "kind": "warehouse", "erp_plant": plant,
        "erp_storage_locations": [CORE_SLOC]},
        headers={"Authorization": f"Bearer {ex['access_token']}", "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
    return str(_accepted(r, "create the core organisation's Field site", 201)["id"])


def wait_until(what: str, fn: Any, timeout_s: float, every: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(every)
    raise SmokeFailure(f"{what} did not happen within {timeout_s:.0f} s (last: {str(last)[:300]})")


def base_plan(web: CoreWeb, item: str) -> tuple[str | None, dict[str, Any] | None]:
    """(the latest base plan run id, the item's plan row) as the core's plan page reads them."""
    r = web.c.get("/v1/plan", params={"view": "item"})
    if r.status_code != 200:
        return None, None
    body = r.json()
    rows = [x for x in body.get("items", []) if x.get("item_code", x.get("item")) == item]
    return str((body.get("run") or {}).get("id")), (rows[0] if rows else None)


def _plan_brief(row: dict[str, Any] | None) -> str:
    """on-hand, the first three buckets' scheduled receipts and projected available balance, the first short bucket."""
    if not row:
        return "no plan row"
    pab = [float(x) for x in row.get("pab") or []]
    short = next((i for i, v in enumerate(pab) if v < 0), None)
    sched = [round(float(x)) for x in (row.get("scheduled") or [])[:3]]
    return (f"on_hand {row.get('on_hand')}, scheduled {sched}, pab {[round(v) for v in pab[:3]]}, first short bucket"
            f" {short if short is not None else 'none'}")


def site_clock(web: CoreWeb, loc: str, item: str) -> tuple[str, str | None]:
    """The dashboard's starvation clock at the site: (soonest stockout and the item's clock, the run it is read from).
    The clocks come from the open signals' exposure runs, which the core re-scores when its data changes."""
    r = web.c.get("/v1/dashboard/sites")
    if r.status_code != 200:
        return f"dashboard sites HTTP {r.status_code}", None
    site = next((x for x in r.json().get("sites", []) if x.get("code") == loc), None)
    if site is None:
        return f"{loc} not on the dashboard", None
    clock = next((c for c in site.get("clocks", []) if c.get("item") == item), None)
    run = str(clock["run_id"]) if clock else (str(site["clocks"][0]["run_id"]) if site.get("clocks") else None)
    mine = (f"{item} {clock['days_to_stockout']} d to stockout on {clock['stockout']}, recovery lands {clock['lands']}"
            if clock else f"no clock for {item}")
    return f"{loc} soonest stockout {site.get('soonest_stockout_days')} d; {mine} (exposure run {str(run)[:8]})", run


# --- smoke --core ---------------------------------------------------------------------------------------------------

def smoke_core_real(api: str, state: dict[str, Any], wait: float) -> None:
    """M4 stream C against the real core: app sign-in, exchange (core role procurement -> field.operator), core device
    status, a GR 101 in erp-sim against the core's own PO line, the two signed feed rows the core accepts, the core's
    PO line received and on-hand = erp-sim, what the base plan does next, then core revocation -> exchange refused."""
    from field_worker.core_feeds import load_code_map

    base = core_base()
    device = f"smoke-core-{uuid.uuid4().hex[:10]}"
    signed = app_sign_in(base, "OPERATOR", device, "PHONE_ONLY")
    claims = check_signed_token(base, signed, "procurement")
    tenant = str(claims["tenant_id"])
    _expect(signed.get("wearable") is not None, "the core gave the operator no device session (it pairs with"
                                                " heartbeat.report or action.update)")
    print(f"core     signed in {claims['email']} at the core {base}: tenant {tenant}, kid ok, roles {claims['roles']}")

    ex = _accepted(exchange(api, str(signed["access_token"])), "exchange of the core token")
    _expect(ex["roles"] == ["field.operator"] and ex.get("core_roles") == ["procurement"],
            f"core roles {claims['roles']} -> field roles {ex['roles']} / core_roles {ex.get('core_roles')}")
    _expect(ex["tenant_id"] == tenant, f"field tenant {ex['tenant_id']} != core tenant {tenant}")
    field_dev = str(ex["device_id"])
    _expect(device_status(device, tenant) == "active", "the core reports the operator's device as not active")
    again = _accepted(exchange(api, str(signed["access_token"]), field_dev), "re-exchange")
    _expect(again["device_id"] == field_dev, "re-exchange gave another device")
    print(f"         exchanged at field-api: field.operator, field device {field_dev}; core device {device} active")

    codes = load_code_map(os.environ.get("FIELD_CORE_CODE_MAP", ""))
    web = CoreWeb(base, "OPERATOR")
    try:
        m = export_line(web, erp_holds_core_pos()) or mapped_line(codes, web)
        print(f"         {'export mode: erp-sim holds the core PO under its own codes, no code map' if m.get('export')
                          else 'code-map mode: FIELD_CORE_CODE_MAP maps erp-sim to the core'}")
        before_line, before_hand = m["line"], core_on_hand(web, m["item"], m["location"])
        run_before, plan_before = base_plan(web, m["item"])
        clock_before, clock_run = site_clock(web, m["location"], m["item"])
        print(f"         core before: {m['ref']} {m['item']}@{m['location']} qty {before_line['qty']} status"
              f" {before_line['status']}; on-hand {before_hand}")
        print(f"         core before: base plan run {run_before}: {m['item']} {_plan_brief(plan_before)}")
        print(f"         core before: starvation clock {clock_before}")
        if before_line["status"] == "received":
            print(f"         note: {m['ref']} was received by an earlier run; this run receives it again (the row is"
                  " an upsert), so the check below is the line's update time and the new on-hand")
        if m.get("export"):
            site, sloc = export_site(tenant, m["plant"])
            seeded = open_asn(m["erp_po"], m["material"], m["plant"])
        else:
            ensure_erp_plant(m["plant"], f"Core plant (the core's {m['location']})")
            if before_hand is not None and align_opening_stock(m["material"], m["plant"], before_hand):
                print(f"         erp-sim opening stock of {m['material']} at {m['plant']} set to the core's on-hand"
                      f" {before_hand:g} (dev seed, once)")
            site, sloc, seeded = ensure_core_site(api, base, tenant, m["plant"], m["location"]), CORE_SLOC, None
        state.setdefault("core_sites", {})[tenant] = site
        stack.STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

        phone = stack.Phone(api, str(signed["access_token"]))
        phone.token, phone.device_id = str(again["access_token"]), field_dev
        if seeded:
            deliv, qty = seeded
            print(f"         receiving the PO's seeded ASN {deliv} ({m['material']} {qty:g}) at site {site}")
        else:
            qty = float(before_line["qty"])
            deliv = stack.create_inbound_delivery(1, plant=m["plant"], sloc=sloc, purchase_order=m["erp_po"],
                                                  materials=[m["material"]], qty=qty)
        task = stack._wait_task(phone, site, "receive", lambda t: t.get("ref_doc_no") == deliv, wait)
        staged: list[tuple[str, float]] = []
        for ln in task["lines"]:
            cr = phone.count(ln, float(ln["expected_qty"]))
            _accepted(cr, "count", 201)
            staged.append((ln["id"], phone.counted(cr, float(ln["expected_qty"]))))
        _expect(_accepted(phone.finish(task["id"], staged), "post (touch)", 202)["status"] == "queued", "GR not queued")
        ev = phone.wait_event(("erp.posted",), task["id"], wait)
        _expect(ev["kind"] == "erp.posted", f"GR: {ev}")
        [(material, mvt, got)] = stack.erp_movements(ev["doc_number"], ev["doc_year"])
        _expect(mvt == "101" and material == m["material"] and got == qty, f"movement {mvt} {material} {got}")
        on_hand = stack.erp_plant_stock(m["material"], m["plant"])
        print(f"         GR {ev['doc_number']}/{ev['doc_year']} in erp-sim: {material} {got:g} at {m['plant']} against"
              f" PO {m['erp_po']} line 10 (the core's {m['ref']}); erp-sim on-hand now {on_hand:g}")

        dl = wait_until("both feed deliveries", lambda: (
            lambda d: d if d and all(s == "delivered" for _, s, _ in d) and len(d) == 2 else None)(
            stack.core_deliveries(tenant, ev["doc_number"])), wait)
        _expect([(f, n) for f, _, n in dl] == [("inventory", 1), ("open_supply", 1)], f"deliveries {dl}")
        print(f"         field-worker: both signed rows delivered to the core, once each {dl}")

        answers = delivery_answers(tenant, ev["doc_number"])
        if answers.get("open_supply") == 409:  # the core: same body within 10 min -> 409 duplicate (TO_FIELD 4)
            _expect(before_line["status"] == "received", f"the core called a first PO row a duplicate: {answers}")
            print(f"         the core answered 409 duplicate to the identical PO row (an earlier run sent it within"
                  f" 10 min); Field counted it delivered, as agreed. HTTP answers {answers}")
        else:
            _expect(answers.get("open_supply") == 202 and answers.get("inventory") == 202, f"core answers {answers}")

        def received() -> dict[str, Any] | None:
            x = core_line(web, m["ref"], m["item"])
            fresh = answers.get("open_supply") == 409 or str((x or {}).get("updated_at")) > str(before_line["updated_at"])
            return x if x and x["status"] == "received" and fresh else None

        line = wait_until(f"the core's {m['ref']} received", received, wait)
        _expect(float(line["qty"]) == got and line["location_code"] == m["location"], f"core line {line}")
        hand = wait_until("the core's on-hand = erp-sim's", lambda: (
            lambda v: v if v is not None and v == on_hand else None)(core_on_hand(web, m["item"], m["location"])),
            wait)
        runs = {e: (lambda b: b if isinstance(b, list) else b.get("items", []))(
            web.get("/v1/pipeline/runs", entity=e))[:1] for e in ("inventory", "open_supply")}
        print(f"         core after: {m['ref']} status {line['status']} qty {line['qty']} (was {before_line['status']}"
              f" {before_line['qty']}); {m['item']}@{m['location']} on-hand {hand:g} (was {before_hand})")
        for e, rr in runs.items():
            if rr:
                r0 = rr[0]
                print(f"         core pipeline {e}: last run {r0.get('status')} from {r0.get('source', r0.get('feed'))}"
                      f" rows {r0.get('rows_in')}")

        def replanned() -> tuple[str | None, dict[str, Any] | None] | None:
            run, row = base_plan(web, m["item"])
            return (run, row) if run and run != run_before else None

        try:
            run_after, plan_after = wait_until("a new base plan run", replanned, wait, every=2)
            print(f"         re-plan: base plan run {run_before} -> {run_after}; {m['item']} now {_plan_brief(plan_after)}")
        except SmokeFailure:
            print(f"         re-plan: no new base plan run within {wait:.0f} s (still {run_before}); observation only")
        try:  # the open signals' exposure runs are re-scored on the core's data change: wait for the new run
            after = wait_until("the starvation clock's re-scored exposure run", lambda: (
                lambda c: c if c[1] and c[1] != clock_run else None)(site_clock(web, m["location"], m["item"])),
                wait, every=2)[0]
        except SmokeFailure:
            after = site_clock(web, m["location"], m["item"])[0] + f"; not re-scored within {wait:.0f} s"
        print(f"         starvation clock after: {after} (observation only)")
    finally:
        web.close()

    sid = str(signed["wearable"]["session_id"])
    wh = {**LR, "Authorization": f"Bearer {signed['wearable']['token']}", "X-Device-Id": device}
    gone = httpx.delete(f"{base}/v1/wearable/sessions/{sid}", headers=wh, timeout=10)
    _expect(gone.status_code == 204, f"revoke the device session at the core: HTTP {gone.status_code} {gone.text[:200]}")
    _expect(device_status(device, tenant) == "revoked", "the core still reports the revoked device as active")
    refused = exchange(api, str(signed["access_token"]), field_dev)
    _expect(refused.status_code == 403, f"exchange after core revocation: HTTP {refused.status_code}")
    print("         core revocation (DELETE /v1/wearable/sessions/{id}): device revoked at the core, next exchange 403")


# --- smoke --approver -----------------------------------------------------------------------------------------------

def prepare_decision(base: str, wait: float) -> str:
    """One decision waiting for approval, made the way a planner makes one on the web: a decision on the demo's sample
    scenarios (``POST /v1/decisions {scenario_ids}``, ``scmtips-local-demo`` prepares them), then submitted. (A TEST
    signal is not used: the core's news pipeline merges a repeated article into the signal it already made.)"""
    planner = CoreWeb(base, "PLANNER")
    try:
        page = planner.get("/v1/scenarios")
        items = page["items"] if isinstance(page, dict) else page
        ids = [str(x["id"]) for x in items if str(x.get("name", "")).endswith("(sample)")][:4]
        _expect(bool(ids), "the core has no sample scenarios: run the core kit's `scmtips-local-demo --with-team`")
        made = planner.post("/v1/decisions", {"scenario_ids": ids,
                                              "title": f"Field smoke: sample response ({time.strftime('%H:%M:%S')})"})
        _expect(made.status_code in (201, 202), f"planner opens a decision: HTTP {made.status_code} {made.text[:200]}")
        did = str(made.json()["id"])

        def ready() -> dict[str, Any] | None:
            d: dict[str, Any] = planner.get(f"/v1/decisions/{did}")
            return d if any(o["status"] == "ready" for o in d["options"]) else None

        d = wait_until("the decision's options", ready, wait * 2)
        _accepted(planner.post(f"/v1/decisions/{did}/submit", {"version": d["version"]}), "planner submits the decision")
        return did
    finally:
        planner.close()


def scenario_message(name: str) -> dict[str, Any]:
    """The core's SAMPLE scenario message (an exchange-contract ``signal`` message) from its checkout."""
    folder = os.environ.get("FIELD_CORE_SCENARIOS_DIR", "").strip()
    if not folder:
        raise SmokeFailure("set FIELD_CORE_SCENARIOS_DIR in .env.local to the core checkout's samples/scenarios")
    root = Path(folder)
    manifest = json.loads((root / "scenarios.json").read_text(encoding="utf-8"))
    entry = next((x for x in manifest["scenarios"] if x["name"] == name), None)
    _expect(entry is not None, f"the core's scenario pack has no {name!r}")
    assert entry is not None  # for mypy: _expect raised otherwise
    _expect(entry["transport"] == "signal_file", f"{name} is a test injection, not a signals workbook")
    msg: dict[str, Any] = json.loads((root / str(entry["file"])).read_text(encoding="utf-8"))
    _expect(msg.get("message") == "signal" and msg.get("simulated") is True, f"{name} is not a SIMULATED signal message")
    return msg


def scenario_csv(msg: dict[str, Any], run: str, now: float | None = None) -> tuple[bytes, str]:
    """The message's rows as the signals workbook's CSV (a fresh external id and event time, so the core sees a new
    article; lists separated by semicolons, as in the core's template) and the first row's title."""
    rows = list(msg["rows"])
    columns = list(rows[0].keys())
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for row in rows:
        fresh = {**row, "external_id": f"{row['external_id']}-{run}", "event_at": at}
        w.writerow([";".join(map(str, v)) if isinstance(v, list) else "" if v is None else v
                    for v in (fresh.get(c) for c in columns)])
    return buf.getvalue().encode("utf-8"), str(rows[0]["title"])


def prepare_scenario_decision(base: str, wait: float, name: str) -> str:
    """One decision waiting for approval, made by a disruption: the Org admin sends the core's SAMPLE scenario as the
    signals workbook, the core's pipeline auto-drafts the decision, and the planner submits it. A repeated scenario
    merges into the core's open signal for the same event (48 h); then its open decision is used, or the planner opens
    a new one on that signal."""
    data, title = scenario_csv(scenario_message(name), uuid.uuid4().hex[:8])
    since = time.time() - 5
    admin = CoreWeb(base, "ADMIN")
    planner = CoreWeb(base, "PLANNER")
    try:
        sent = admin.c.post("/v1/exchange/messages/signal/import-file", files={"file": (f"{name}.csv", data, "text/csv")})
        _accepted(sent, f"the core's file-mode signal import of {name}", 202)

        def signal() -> dict[str, Any] | None:
            for x in admin.get("/v1/signals", limit=50)["items"]:
                seen = datetime.fromisoformat(str(x["last_seen_at"]).replace("Z", "+00:00")).timestamp()
                if seen < since:
                    continue
                if x["title"] == title:
                    return dict(x)
                arts = admin.get(f"/v1/signals/{x['id']}").get("articles") or []
                if any(a.get("title") == title for a in arts):
                    return dict(x)
            return None

        sig = wait_until(f"the core's signal for {name}", signal, wait * 2)

        def decision() -> dict[str, Any] | None:
            items = admin.get("/v1/decisions", view="all", signal=sig["id"]).get("items") or []
            live = [i for i in items if i["status"] in ("DRAFT", "PENDING_APPROVAL")]
            if not live:
                return None
            d: dict[str, Any] = planner.get(f"/v1/decisions/{live[0]['id']}")
            return d if any(o["status"] == "ready" for o in d["options"]) else None

        try:
            d = wait_until(f"the core's auto-drafted decision on {name}", decision, wait * 2)
        except SmokeFailure:  # the event's decision was decided in an earlier run: a new one on the same signal
            made = planner.post("/v1/decisions", {"signal_id": sig["id"]})
            _expect(made.status_code in (201, 202), f"planner opens a decision: HTTP {made.status_code} {made.text[:200]}")
            d = wait_until("the new decision's options", decision, wait * 2)
        if d["status"] == "DRAFT":
            _accepted(planner.post(f"/v1/decisions/{d['id']}/submit", {"version": d["version"]}),
                      "planner submits the scenario's decision")
        print(f"         scenario {name}: signal {sig['id']} ({sig['band_label']}), decision {d['id']} with"
              f" {len(d['options'])} options ({', '.join(o['template'] for o in d['options'])}), submitted")
        return str(d["id"])
    finally:
        admin.close()
        planner.close()


def prepare_given_decision(base: str, wait: float, did: str) -> str:
    """The decision ``did`` (``--decision``, M4-C17: the one the core's ``scmtips-scenario inject --wait`` reported),
    waiting for approval: read by the planner, submitted when it is still a draft once an option is ready. A decision
    that is already decided (or gone) is refused, so the demo run never approves another one by accident."""
    planner = CoreWeb(base, "PLANNER")
    try:
        def ready() -> dict[str, Any] | None:
            d: dict[str, Any] = planner.get(f"/v1/decisions/{did}")
            return d if any(o["status"] == "ready" for o in d["options"]) else None

        d = wait_until(f"decision {did}'s options", ready, wait * 2)  # a missing decision: core GET raises at once
        _expect(d["status"] in ("DRAFT", "PENDING_APPROVAL"),
                f"decision {did} is {d['status']}, not waiting for approval (reset the core's demo and inject again)")
        if d["status"] == "DRAFT":
            _accepted(planner.post(f"/v1/decisions/{did}/submit", {"version": d["version"]}),
                      "planner submits the decision")
        print(f"         decision {did} ({d.get('title', '')[:60]}): {len(d['options'])} options"
              f" ({', '.join(o['template'] for o in d['options'])}), {'submitted' if d['status'] == 'DRAFT' else 'waiting'}")
        return did
    finally:
        planner.close()


def smoke_approver_real(api: str, state: dict[str, Any], wait: float, scenario: str | None = None,
                        decision: str | None = None) -> None:
    """M4 F2 + F1 + F3 against the real core: app sign-in, exchange (approver -> field.supervisor), next decision,
    field-api spoken brief, Field's core brief check (template accepted, a changed number refused), voice challenge,
    "approve option two" -> read-back -> replay and reuse rules -> step-up when the band needs it -> confirm ->
    approved at the core; a decided decision refuses a new challenge."""
    from field_api.briefs.core import CoreBriefCheck

    del state
    base = core_base()
    device = f"smoke-approver-{uuid.uuid4().hex[:10]}"
    signed = app_sign_in(base, "APPROVER", device, "RAYBAN_META_GEN2")
    claims = check_signed_token(base, signed, "approver")
    _expect(signed["capabilities"]["approve_decisions"] is True, f"approver capabilities {signed['capabilities']}")
    _expect(signed.get("wearable") is not None, "the core gave the approver no device session")
    wtoken, wdevice = str(signed["wearable"]["token"]), str(signed["wearable"]["device_id"])
    ex = _accepted(exchange(api, str(signed["access_token"])), "exchange of the approver's core token")
    _expect("voice.approve" in ex.get("core_permissions", []), f"core_permissions {ex.get('core_permissions')}")
    _expect(ex["roles"] == ["field.supervisor"] and ex.get("core_roles") == ["approver"],
            f"approver core role mapped to {ex['roles']}")
    _expect(device_status(device, str(claims["tenant_id"])) == "active", "the approver's device is not active")
    field_token = str(ex["access_token"])
    print(f"approver signed in {claims['email']} at the core {base}; field.supervisor, field device {ex['device_id']}")

    core_h = {**LR, "Authorization": f"Bearer {wtoken}", "X-Device-Id": wdevice}

    def next_item() -> dict[str, Any] | None:
        item = _accepted(httpx.get(f"{base}/v1/wearable/next", headers=core_h, timeout=30), "next decision")["item"]
        return item if isinstance(item, dict) else None

    def say(nonce: str, words: str, idem: str | None = None) -> dict[str, Any]:
        h = {**core_h, "Idempotency-Key": idem or str(uuid.uuid4())}
        return _accepted(httpx.post(f"{base}/v1/voice/commands", headers=h, timeout=30,
                                    json={"nonce": nonce, "transcript": words}), f"voice command {words!r}")

    if scenario or decision:
        wanted = prepare_given_decision(base, wait, decision) if decision else prepare_scenario_decision(
            base, wait, str(scenario))

        def scenario_item() -> dict[str, Any] | None:
            got = next_item()
            return got if got is not None and str(got["decision_id"]) == wanted else None

        try:
            item = wait_until(f"the scenario's decision {wanted} first for the approver", scenario_item, wait)
        except SmokeFailure as e:
            raise SmokeFailure(f"{e}; another decision waits first (approve it or reset the core's demo)") from None
    else:
        item = next_item()
    if item is None:
        did = prepare_decision(base, wait)
        print(f"         nothing was waiting: the planner opened decision {did} on the sample scenarios and submitted it")
        item = wait_until("the prepared decision for the approver", next_item, wait)
    did, band_step_up = str(item["decision_id"]), bool(item["band"]["step_up"])
    _expect(len(item["card"]) <= 240 and item["spoken"].strip() and len(item["options"]) >= 2, f"next item {item}")

    brief = _accepted(httpx.post(f"{api}/v1/briefs/spoken", timeout=30, json={
        "decision_id": did, "template_text": item["spoken"]}, headers={
        "Authorization": f"Bearer {field_token}", "Idempotency-Key": str(uuid.uuid4()),
        "X-Core-Token": wtoken, "X-Device-Id": wdevice}), "spoken brief from field-api")
    _expect(brief["source"] in ("model", "template") and brief["text"].strip(), f"brief {brief}")
    if brief["source"] == "template":
        _expect(brief["text"] == item["spoken"], "template brief differs from the core's template")
    check = CoreBriefCheck(base_url=base)
    ok = check.check(did, item["spoken"], core_token=wtoken, device_id=wdevice)
    _expect(ok.accepted and not ok.reasons, f"the core refused its own template: {ok}")
    bad = check.check(did, item["spoken"] + " It also costs 987654 more.", core_token=wtoken, device_id=wdevice)
    _expect(not bad.accepted and bool(bad.reasons) and bool(bad.template_text),
            f"the core accepted a changed number: {bad}")
    print(f"decision {did}: {item['waiting']} waiting, band {item['band']['label']!r} step-up {band_step_up};"
          f" brief from {brief['source']} ({', '.join(brief['reasons']) or 'accepted by the core check'})")
    print(f"         Field's core check client at the real core: template accepted; a changed number refused"
          f" ({bad.reasons[0][:80]})")

    ch = _accepted(httpx.post(f"{base}/v1/voice/challenges", headers=core_h, timeout=30, json={"decision_id": did}),
                   "voice challenge", 201)
    waived = bool(ch.get("step_up_waived"))
    idem = str(uuid.uuid4())
    rb = say(ch["nonce"], "approve option two", idem)
    _expect(rb["outcome"] == "readback" and (rb.get("pending") or {}).get("letter") == "B", f"read-back {rb}")
    _expect(bool(rb["step_up_required"]) == (band_step_up and not waived and not ch.get("step_up_fresh")),
            f"step-up flag {rb['step_up_required']} vs band {band_step_up}, waived {waived}")
    _expect(say(ch["nonce"], "approve option two", idem) == rb, "replayed command did not return the same reply")
    reuse = httpx.post(f"{base}/v1/voice/commands", timeout=30, headers={**core_h, "Idempotency-Key": "fresh-" + idem},
                       json={"nonce": ch["nonce"], "transcript": "confirm"})
    _expect(reuse.status_code == 409, f"a used challenge answered HTTP {reuse.status_code}")
    print(f"         'approve option two' -> read-back: {rb['say'][:110]}; replay same reply, reused challenge 409")
    nonce = str(rb["next"]["nonce"])
    if rb["step_up_required"]:
        secret = os.environ.get("FIELD_CORE_SMOKE_APPROVER_TOTP_SECRET", "").strip()
        _expect(bool(secret), "the core asks for a step-up: set FIELD_CORE_SMOKE_APPROVER_TOTP_SECRET (strict sign-in)")
        held = say(nonce, "confirm")
        _expect(held["outcome"] != "executed", f"confirm before the step-up committed: {held}")
        su = httpx.post(f"{base}/v1/auth/step-up", headers=core_h, timeout=30, json={"code": totp_now(secret)})
        _accepted(su, "phone step-up at the core")
        nonce = str(held["next"]["nonce"])
        print("         confirm before the step-up was held; step-up with the authenticator code accepted")
    elif band_step_up:
        print("         the band asks for a step-up, and the core waives it (strict sign-in off: LR_ENV=local);"
              " the approval records the waiver")
    out = say(nonce, "confirm")
    _expect(out["outcome"] == "executed" and out["approval_id"], f"confirm: {out}")
    status = str(out["decision"]["status"])
    # The core moves a fully approved decision on at once: APPROVED -> EXECUTING (plan committed, actions created).
    _expect(status in APPROVED_STATES, f"decision status after confirm: {status}")
    web = CoreWeb(base, "ADMIN")
    try:
        seen = web.get(f"/v1/decisions/{did}")
    finally:
        web.close()
    _expect(seen["status"] == status, f"the core's decision page says {seen['status']}, the voice turn said {status}")
    print(f"         confirm -> {out['say'][:100]} (approval {out['approval_id']}); the core's decision is {status}")
    late = httpx.post(f"{base}/v1/voice/challenges", headers=core_h, timeout=30, json={"decision_id": did})
    if status != "PARTIALLY_APPROVED":
        _expect(late.status_code == 409, f"a challenge on a decided decision answered HTTP {late.status_code}")
        print("         a decided decision refuses a new challenge (409)")
