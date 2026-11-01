"""OEM simulator HTTP routes, mounted by erp-sim under /_oem (docs/design/M5_C3_CONTRACT.md section 5).

Public:
  GET  /_oem/.well-known/oem-keys                      the maker's public key set (JWKS-like); 503 without a key
Registry (X-Sim-Admin-Token = ERPSIM_ADMIN_TOKEN, the token field-api already holds for erp-sim's sandbox):
  POST /_oem/v1/units/{serial}/checks {checker, area?} the unit's history and the atomic first-check claim
  GET  /_oem/v1/units/{serial}                         the unit's history and first check (read only)
Admin (X-Sim-Admin-Token):
  POST /_oem/admin/units {serial, sku, sealed_at, events, scenario?, title?, copies?, reset_first_check?}
       -> 201 created / 200 updated, with the unit's signed ``code``; events are replaced; the nonce is kept
  POST /_oem/admin/forgeries {serial, sku, sealed_at, scenario?, title?} -> a label-sheet-only counterfeit code
  POST /_oem/admin/reset                               every unit, event, first check and forgery deleted
Errors are ``{"error": {"code", "message"}}`` (the shape erp-sim's handler passes through unchanged).

This is a simulator of a maker that signs its seals and opens its registry; no real maker does that for this build.
"""

from __future__ import annotations

import hmac
import os
from datetime import date
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from oem_sim import keys
from oem_sim.db import get_conn

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/_oem", tags=["OEM simulator (M5 C3)"])

EventType = Literal["manufactured", "shipped_to_seller", "delivered", "activated", "returned", "refurbished"]
SERIAL = r"^[A-Z0-9-]{4,40}$"
SKU = r"^[A-Z0-9-]{2,40}$"
AREA = r"^[A-Za-z][A-Za-z .'-]{0,59}$"
ADMIN_ENV = "ERPSIM_ADMIN_TOKEN"
ADMIN_DEFAULT = "dev-sim-admin-token"  # = erp-sim's dev default (routes/sandbox.py)


def err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def admin_ok(token: str | None) -> bool:
    return token is not None and hmac.compare_digest(token, os.getenv(ADMIN_ENV, ADMIN_DEFAULT))


NO_ADMIN = ("OEMSIM-401-ADMIN", "Invalid X-Sim-Admin-Token")
NO_KEY = ("OEMSIM-503-NO-KEY", f"The simulator has no signing key: set {keys.SEED_ENV}.")


class EventIn(BaseModel):
    type: EventType
    at: date
    area: str | None = Field(default=None, pattern=AREA)


class UnitIn(BaseModel):
    serial: str = Field(pattern=SERIAL)
    sku: str = Field(pattern=SKU)
    sealed_at: date
    events: list[EventIn] = Field(default_factory=list, max_length=20)
    scenario: str | None = Field(default=None, max_length=8)
    title: str | None = Field(default=None, max_length=120)
    copies: int = Field(default=1, ge=1, le=4)
    reset_first_check: bool = True


class ForgeryIn(BaseModel):
    serial: str = Field(pattern=SERIAL)
    sku: str = Field(pattern=SKU)
    sealed_at: date
    scenario: str | None = Field(default=None, max_length=8)
    title: str | None = Field(default=None, max_length=120)


class CheckIn(BaseModel):
    checker: str = Field(pattern=r"^[0-9a-f]{32}$", description="pseudonymous checker id (never a name)")
    area: str | None = Field(default=None, pattern=AREA, description="coarse, city level at most")


def unit_body(cur: Any, serial: str) -> dict[str, Any] | None:
    cur.execute("SELECT serial, oem, sku, sealed_at FROM oemsim.unit WHERE serial = %s", (serial,))
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute("SELECT type, at, area FROM oemsim.unit_event WHERE serial = %s ORDER BY at, id", (serial,))
    events = [{"type": t, "at": a.isoformat(), "area": ar} for t, a, ar in cur.fetchall()]
    return {"serial": row[0], "oem": row[1], "sku": row[2], "sealed_at": row[3].isoformat(), "events": events}


def _first(cur: Any, serial: str) -> dict[str, Any] | None:
    cur.execute("SELECT checker, at, area FROM oemsim.first_check WHERE serial = %s", (serial,))
    r = cur.fetchone()
    return None if r is None else {"checker": r[0], "at": r[1].isoformat(), "area": r[2]}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "oem-sim", "oem": keys.OEM_ID}


@router.get("/.well-known/oem-keys")
def oem_keys(response: Response) -> Any:
    try:
        body = keys.jwks()
    except keys.NoSigningKey:
        return err(503, *NO_KEY)
    response.headers["Cache-Control"] = "public, max-age=300"
    return body


def check_unit(serial: str, checker: str, area: str | None) -> dict[str, Any] | None:
    """History plus the first-check claim, in one transaction; None when the serial is not in the registry."""
    with get_conn() as conn, conn.cursor() as cur:
        unit = unit_body(cur, serial)
        if unit is None:
            return None
        cur.execute("INSERT INTO oemsim.first_check (serial, checker, area) VALUES (%s, %s, %s)"
                    " ON CONFLICT (serial) DO NOTHING RETURNING at", (serial, checker, area))
        first = cur.fetchone() is not None
        fc = _first(cur, serial)
        conn.commit()
    assert fc is not None  # the row exists: inserted now or by the check that won
    return {"unit": unit, "first_check": {"first": first, "at": fc["at"], "area": fc["area"],
                                          "same_checker": fc["checker"] == checker}}


@router.post("/v1/units/{serial}/checks")
def post_check(serial: str, body: CheckIn,
               x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token")) -> Any:
    if not admin_ok(x_sim_admin_token):
        return err(401, *NO_ADMIN)
    out = check_unit(serial, body.checker, body.area)
    if out is None:
        return err(404, "OEMSIM-404-UNIT", "The maker has no unit with this serial.")
    logger.info("oem_check", serial=serial, first=out["first_check"]["first"])  # never the checker id
    return out


@router.get("/v1/units/{serial}")
def get_unit(serial: str, x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token")) -> Any:
    if not admin_ok(x_sim_admin_token):
        return err(401, *NO_ADMIN)
    with get_conn() as conn, conn.cursor() as cur:
        unit = unit_body(cur, serial)
        fc = _first(cur, serial) if unit else None
    if unit is None:
        return err(404, "OEMSIM-404-UNIT", "The maker has no unit with this serial.")
    return {"unit": unit, "first_check": None if fc is None else {"at": fc["at"], "area": fc["area"]}}


def upsert_unit(body: UnitIn) -> tuple[dict[str, Any], bool]:
    nonce = keys.nonce_for(body.serial)  # raises NoSigningKey before anything is written
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oemsim.unit (serial, oem, sku, sealed_at, nonce, scenario, title, copies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (serial) DO UPDATE SET sku = EXCLUDED.sku, sealed_at = EXCLUDED.sealed_at,
                   scenario = EXCLUDED.scenario, title = EXCLUDED.title, copies = EXCLUDED.copies, updated_at = NOW()
            RETURNING (xmax = 0), nonce
            """,
            (body.serial, keys.OEM_ID, body.sku, body.sealed_at, nonce, body.scenario, body.title, body.copies),
        )
        row = cur.fetchone()
        assert row is not None
        created, stored_nonce = bool(row[0]), str(row[1])
        cur.execute("DELETE FROM oemsim.unit_event WHERE serial = %s", (body.serial,))
        for ev in sorted(body.events, key=lambda e: e.at):
            cur.execute("INSERT INTO oemsim.unit_event (serial, type, at, area) VALUES (%s, %s, %s, %s)",
                        (body.serial, ev.type, ev.at, ev.area))
        if body.reset_first_check:
            cur.execute("DELETE FROM oemsim.first_check WHERE serial = %s", (body.serial,))
        unit = unit_body(cur, body.serial)
        conn.commit()
    assert unit is not None
    unit["code"] = keys.seal_code(body.serial, body.sku, body.sealed_at, stored_nonce)
    unit["scenario"], unit["title"], unit["copies"] = body.scenario, body.title, body.copies
    return unit, created


@router.post("/admin/units")
def post_unit(body: UnitIn, response: Response,
              x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token")) -> Any:
    if not admin_ok(x_sim_admin_token):
        return err(401, *NO_ADMIN)
    try:
        unit, created = upsert_unit(body)
    except keys.NoSigningKey:
        return err(503, *NO_KEY)
    response.status_code = 201 if created else 200
    return unit


@router.post("/admin/forgeries")
def post_forgery(body: ForgeryIn, response: Response,
                 x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token")) -> Any:
    if not admin_ok(x_sim_admin_token):
        return err(401, *NO_ADMIN)
    try:
        code = keys.forged_code(body.serial, body.sku, body.sealed_at)
    except keys.NoSigningKey:
        return err(503, *NO_KEY)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM oemsim.unit WHERE serial = %s", (body.serial,))
        if cur.fetchone() is not None:
            return err(409, "OEMSIM-409-IN-REGISTRY", "A forgery's serial must not be a registered unit.")
        cur.execute(
            """
            INSERT INTO oemsim.forged_label (serial, sku, sealed_at, scenario, title) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (serial) DO UPDATE SET sku = EXCLUDED.sku, sealed_at = EXCLUDED.sealed_at,
                   scenario = EXCLUDED.scenario, title = EXCLUDED.title
            RETURNING (xmax = 0)
            """,
            (body.serial, body.sku, body.sealed_at, body.scenario, body.title),
        )
        row = cur.fetchone()
        conn.commit()
    response.status_code = 201 if row and row[0] else 200
    return {"serial": body.serial, "sku": body.sku, "sealed_at": body.sealed_at.isoformat(), "code": code,
            "scenario": body.scenario, "title": body.title, "in_registry": False}


def reset() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE oemsim.first_check, oemsim.unit_event, oemsim.unit, oemsim.forged_label")
        conn.commit()


@router.post("/admin/reset")
def post_reset(x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token")) -> Any:
    if not admin_ok(x_sim_admin_token):
        return err(401, *NO_ADMIN)
    reset()
    return {"status": "reset_completed"}


def all_units() -> list[dict[str, Any]]:
    """Every unit with its history and first check, for the admin page and the label sheet."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT serial, nonce, scenario, title, copies FROM oemsim.unit ORDER BY scenario NULLS LAST, serial")
        rows = cur.fetchall()
        out = []
        for serial, nonce, scenario, title, copies in rows:
            unit = unit_body(cur, serial)
            assert unit is not None
            fc = _first(cur, serial)
            out.append({**unit, "nonce": nonce, "scenario": scenario, "title": title, "copies": int(copies),
                        "first_check": None if fc is None else {"at": fc["at"], "area": fc["area"]}})
    return out


def all_forgeries() -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT serial, sku, sealed_at, scenario, title FROM oemsim.forged_label"
                    " ORDER BY scenario NULLS LAST, serial")
        return [{"serial": s, "sku": k, "sealed_at": d.isoformat(), "scenario": sc, "title": t}
                for s, k, d, sc, t in cur.fetchall()]


__all__ = ["router", "check_unit", "upsert_unit", "reset", "all_units", "all_forgeries"]
