"""OemPort over HTTP to the OEM simulator (services/oem-sim, mounted by erp-sim under /_oem).

- keys: ``GET {base}/.well-known/oem-keys`` (public), cached on this adapter for ``keys_ttl_s`` (default
  FIELD_OEM_KEYS_TTL_S or 300 s). A cache, not a store: a new adapter, an expired entry or ``refresh=True`` fetches.
- check_unit: ``POST {base}/v1/units/{serial}/checks`` with X-Sim-Admin-Token (ERPSIM_ADMIN_TOKEN, read by name,
  never logged), 5 s timeout. 404 -> UnitNotFound; any other failure -> OemUnavailable.
The simulator speaks for one SAMPLE maker (``kestrel-sample``); ``knows`` is true for that id only.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import httpx
import structlog

from field_oem.ports.oem_port import (
    EVENT_TYPES,
    FirstCheck,
    OemKey,
    OemKeySet,
    OemUnavailable,
    SeedUnit,
    UnitCheck,
    UnitEvent,
    UnitHistory,
    UnitNotFound,
)

logger = structlog.get_logger(__name__)

SIM_OEM_ID = "kestrel-sample"
ADMIN_TOKEN_ENV = "ERPSIM_ADMIN_TOKEN"
ADMIN_TOKEN_DEV = "dev-sim-admin-token"  # erp-sim's dev default (routes/sandbox.py)
KEYS_TTL_ENV = "FIELD_OEM_KEYS_TTL_S"
TIMEOUT_S = 5.0
KID_RE = re.compile(r"^[0-9a-f]{16}$")


def keys_ttl_s() -> float:
    raw = os.getenv(KEYS_TTL_ENV, "").strip()
    try:
        return max(0.0, min(3600.0, float(raw)))
    except ValueError:
        return 300.0


def _unb64(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_keys(body: Any) -> OemKeySet:
    if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
        raise OemUnavailable("the key set has no keys list")
    out = []
    for k in body["keys"]:
        if not isinstance(k, dict) or k.get("kty") != "OKP" or k.get("crv") != "Ed25519":
            continue
        kid, x = k.get("kid"), k.get("x")
        if not isinstance(kid, str) or not KID_RE.match(kid) or not isinstance(x, str):
            continue
        try:
            raw = _unb64(x)
        except (ValueError, binascii.Error):
            continue
        if len(raw) == 32:
            out.append(OemKey(kid, raw))
    if not out:
        raise OemUnavailable("the key set has no usable Ed25519 key")
    return OemKeySet(str(body.get("oem") or SIM_OEM_ID), str(body.get("name") or ""), tuple(out),
                     sample=body.get("sample") is True)


def parse_check(body: Any, oem: str) -> UnitCheck:
    try:
        u, fc = body["unit"], body["first_check"]
        events = []
        for ev in u["events"]:
            if ev["type"] not in EVENT_TYPES:
                raise ValueError(f"unknown event type {ev['type']!r}")
            area = ev.get("area")
            events.append(UnitEvent(str(ev["type"]), date.fromisoformat(str(ev["at"])[:10]),
                                    str(area) if area else None))
        unit = UnitHistory(oem, str(u["serial"]), str(u["sku"]), tuple(events))
        at = datetime.fromisoformat(str(fc["at"]))
        first = FirstCheck(bool(fc["first"] is True), at, str(fc["area"]) if fc.get("area") else None,
                           bool(fc["same_checker"] is True))
    except (KeyError, TypeError, ValueError) as e:
        raise OemUnavailable(f"malformed registry answer ({type(e).__name__})") from None
    return UnitCheck(unit, first)


class SimOemAdapter:
    """OemPort for the OEM simulator. ``client`` (tests) builds the httpx client; else one per call."""

    def __init__(self, base_url: str, *, keys_ttl: float | None = None,
                 client: Callable[[], httpx.Client] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.base_url = base_url.rstrip("/")
        self.keys_ttl = keys_ttl_s() if keys_ttl is None else keys_ttl
        self._client = client
        self._clock = clock
        self._cached: OemKeySet | None = None
        self._cached_at = 0.0
        self.fetches = 0  # how many times the key set was fetched (tests read it)

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client()
        return httpx.Client(base_url=self.base_url, timeout=TIMEOUT_S)

    def knows(self, oem: str) -> bool:
        return oem == SIM_OEM_ID

    def keys(self, oem: str, *, refresh: bool = False) -> OemKeySet:
        now = self._clock()
        if not refresh and self._cached is not None and now - self._cached_at < self.keys_ttl:
            return self._cached
        try:
            with self._http() as c:
                r = c.get("/.well-known/oem-keys")
        except httpx.HTTPError as e:
            raise OemUnavailable(f"keys: {type(e).__name__}") from None
        self.fetches += 1
        if r.status_code != 200:
            raise OemUnavailable(f"keys: HTTP {r.status_code}")
        try:
            ks = parse_keys(r.json())
        except ValueError:
            raise OemUnavailable("keys: not JSON") from None
        self._cached, self._cached_at = ks, now
        return ks

    def check_unit(self, oem: str, serial: str, checker: str, area: str | None) -> UnitCheck:
        token = os.getenv(ADMIN_TOKEN_ENV, ADMIN_TOKEN_DEV)
        try:
            with self._http() as c:
                r = c.post(f"/v1/units/{serial}/checks", json={"checker": checker, "area": area},
                           headers={"X-Sim-Admin-Token": token})
        except httpx.HTTPError as e:
            raise OemUnavailable(f"registry: {type(e).__name__}") from None
        if r.status_code == 404:
            raise UnitNotFound(serial)
        if r.status_code != 200:
            logger.warning("oem_registry_refused", status=r.status_code)
            raise OemUnavailable(f"registry: HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError:
            raise OemUnavailable("registry: not JSON") from None
        return parse_check(body, oem)

    # -- OemSeedPort: the C3 scenarios through the simulator's admin API (X-Sim-Admin-Token)
    def _admin(self, method: str, path: str, **kw: Any) -> httpx.Response:
        token = os.getenv(ADMIN_TOKEN_ENV, ADMIN_TOKEN_DEV)
        try:
            with self._http() as c:
                r = c.request(method, path, headers={"X-Sim-Admin-Token": token}, **kw)
        except httpx.HTTPError as e:
            raise OemUnavailable(f"admin: {type(e).__name__}") from None
        if r.status_code not in (200, 201):
            raise OemUnavailable(f"admin {path}: HTTP {r.status_code} {r.text[:200]}")
        return r

    def seed_unit(self, unit: SeedUnit) -> str:
        body = {"serial": unit.serial, "sku": unit.sku, "sealed_at": unit.sealed_at.isoformat(),
                "events": [{"type": e.type, "at": e.at.isoformat(), "area": e.area} for e in unit.events],
                "scenario": unit.scenario, "title": unit.title, "copies": unit.copies, "reset_first_check": True}
        return str(self._admin("POST", "/admin/units", json=body).json()["code"])

    def seed_forgery(self, serial: str, sku: str, sealed_at: date, scenario: str | None, title: str | None) -> str:
        body = {"serial": serial, "sku": sku, "sealed_at": sealed_at.isoformat(), "scenario": scenario, "title": title}
        return str(self._admin("POST", "/admin/forgeries", json=body).json()["code"])

    def labels_html(self) -> str:
        try:
            with self._http() as c:
                r = c.get("/labels")
        except httpx.HTTPError as e:
            raise OemUnavailable(f"labels: {type(e).__name__}") from None
        if r.status_code != 200:
            raise OemUnavailable(f"labels: HTTP {r.status_code}")
        return r.text
