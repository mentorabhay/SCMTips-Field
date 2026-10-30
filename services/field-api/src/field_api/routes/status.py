"""System status (API1.13) and AI spend (A-02 budget guard).

GET /v1/system/status: real ready checks, not constants.
- postgres: ``SELECT 1`` as the app role, timed
- field-worker: age of its ops.service_heartbeat row (stale after FIELD_WORKER_STALE_S, default 30 s)
- erp: GET <FIELD_ERP_SIM_URL>/_sim/health, timed (the S/4 adapter is not implemented: UNVERIFIED)
- compat: read from FIELD_COMPAT_REPORT (JSON {"core-p13": "PASS", ...}) when that file exists;
  otherwise every core version is reported UNVERIFIED
``erp.p95_ms`` is null: one probe per request gives no distribution; ``probe_ms`` is that probe.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from field_api.ai.budget import BudgetGuard
from field_api.auth.jwt import Principal
from field_api.db import get_conn
from field_api.deps import require_permission

router = APIRouter(prefix="/v1/system", tags=["System"])

CORE_VERSIONS = ("core-p13", "core-p14")


class Check(BaseModel):
    name: str
    ok: bool
    probe_ms: float | None = None
    detail: str = ""


class ErpStatus(BaseModel):
    system: str
    reachable: bool
    probe_ms: float | None = None
    p95_ms: float | None = None


class SystemStatusResponse(BaseModel):
    ready: bool
    compat: dict[str, str]
    erp: ErpStatus
    checks: list[Check]


def _postgres() -> Check:
    t0 = time.perf_counter()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return Check(name="postgres", ok=True, probe_ms=round((time.perf_counter() - t0) * 1000, 2))
    except Exception as e:  # report, never raise: this endpoint must answer when things are down
        return Check(name="postgres", ok=False, detail=type(e).__name__)


def _worker() -> Check:
    stale_s = float(os.getenv("FIELD_WORKER_STALE_S", "30"))
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(EPOCH FROM NOW() - beat_at) FROM ops.service_heartbeat WHERE service = 'field-worker'")
            row = cur.fetchone()
    except Exception as e:
        return Check(name="field-worker", ok=False, detail=type(e).__name__)
    if row is None:
        return Check(name="field-worker", ok=False, detail="no heartbeat recorded")
    age = float(row[0])
    return Check(name="field-worker", ok=age <= stale_s, detail=f"last heartbeat {age:.0f}s ago")


async def _erp() -> ErpStatus:
    adapter = os.getenv("FIELD_ERP_ADAPTER", "sim")
    if adapter != "sim":
        return ErpStatus(system=adapter, reachable=False)
    url = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002").rstrip("/") + "/_sim/health"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
        ok = r.status_code == 200
    except httpx.HTTPError:
        ok = False
    return ErpStatus(system="erp-sim", reachable=ok, probe_ms=round((time.perf_counter() - t0) * 1000, 2) if ok else None)


def _compat() -> dict[str, str]:
    path = os.getenv("FIELD_COMPAT_REPORT")
    data: dict[str, Any] = {}
    if path and Path(path).is_file():
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {}
    return {v: str(data.get(v, "UNVERIFIED")) for v in CORE_VERSIONS}


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(_p: Principal = Depends(require_permission("field.system.read"))) -> SystemStatusResponse:
    checks = [_postgres(), _worker()]
    erp = await _erp()
    checks.append(Check(name="erp", ok=erp.reachable, probe_ms=erp.probe_ms))
    return SystemStatusResponse(ready=all(c.ok for c in checks), compat=_compat(), erp=erp, checks=checks)


@router.get("/ai-usage")
async def get_ai_usage(_p: Principal = Depends(require_permission("field.system.read"))) -> dict[str, Any]:
    """Cloud AI spend vs. the hard caps (A-02)."""
    return BudgetGuard().usage()
