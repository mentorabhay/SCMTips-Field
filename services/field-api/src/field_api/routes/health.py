"""Health and Readiness Endpoints (Task T1.012 / API1.01 / API1.02)."""

import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from field_api.auth import jwks
from field_api.db import get_conn

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "field-api"
    version: str = "0.1.0"


class ReadinessCheck(BaseModel):
    name: str
    status: str
    duration_ms: float
    message: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    checks: list[ReadinessCheck]


@router.get("/v1/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Liveness probe: returns 200 without dependencies."""
    return HealthResponse(status="pass")


@router.get("/v1/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
async def get_readiness() -> JSONResponse:
    """Readiness: database, migration head, core JWKS and erp-sim, each actually probed; 503 if any fails."""
    checks = [_database(), _alembic_head(), await _jwks(), await _erp_sim()]
    ok = all(c.status == "pass" for c in checks)
    body = ReadinessResponse(status="pass" if ok else "fail", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)


def _timed(name: str, fn: Callable[[], str | None]) -> ReadinessCheck:
    t0 = time.perf_counter()
    try:
        msg = fn()
        return ReadinessCheck(name=name, status="pass", duration_ms=_ms(t0), message=msg)
    except Exception as e:  # a probe failure is reported, never raised
        return ReadinessCheck(name=name, status="fail", duration_ms=_ms(t0), message=f"{type(e).__name__}: {e}"[:200])


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _database() -> ReadinessCheck:
    def probe() -> None:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return _timed("database", probe)


def _alembic_head() -> ReadinessCheck:
    def probe() -> str:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))  # independent of cwd
        script = ScriptDirectory.from_config(cfg)
        heads = set(script.get_heads())
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT version_num FROM field.alembic_version")
            current = {r[0] for r in cur.fetchall()}
        if current != heads:
            raise RuntimeError(f"database at {sorted(current)}, code expects {sorted(heads)}")
        return ",".join(sorted(heads))
    return _timed("alembic_head", probe)


async def _jwks() -> ReadinessCheck:
    t0 = time.perf_counter()
    try:
        await jwks.jwks_cache.refresh()
        n = len(jwks.jwks_cache._keys_by_kid)  # noqa: SLF001 - read-only size of the cache
        if n == 0:
            raise RuntimeError(f"no signing keys from {jwks.jwks_cache.jwks_url}")
        return ReadinessCheck(name="jwks_cache", status="pass", duration_ms=_ms(t0), message=f"{n} key(s)")
    except Exception as e:
        return ReadinessCheck(name="jwks_cache", status="fail", duration_ms=_ms(t0), message=str(e)[:200])


async def _erp_sim() -> ReadinessCheck:
    t0 = time.perf_counter()
    url = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002").rstrip("/") + "/_sim/health"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
        r.raise_for_status()
        return ReadinessCheck(name="erp_sim", status="pass", duration_ms=_ms(t0))
    except httpx.HTTPError as e:
        return ReadinessCheck(name="erp_sim", status="fail", duration_ms=_ms(t0), message=f"{type(e).__name__} {url}")
