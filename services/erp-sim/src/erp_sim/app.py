"""SCMTIPS Simulated S/4HANA OData Service (Task T1.041).

Emulates:
- OData v2 JSON endpoints under /sap/opu/odata/sap/<SERVICE>/
- {"d": ...} response wrapping
- CSRF token fetch emulation (x-csrf-token: fetch -> returns token)
- sap-client header handling (default '100')
- SAP-style error bodies: {"error": {"code": ..., "message": {"lang": "en", "value": ...}}}
- Fault injection engine
- Reset endpoint /_sim/reset
"""

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from erp_sim.admin_ui import router as ui_router
from erp_sim.dedupe import IdempotencyConflictError
from erp_sim.faults.warehouse import evaluate_warehouse_fault_header
from erp_sim.locks import LockContentionError
from erp_sim.routes.equipment import router as equipment_router
from erp_sim.routes.fault_admin import router as faults_router
from erp_sim.routes.maintenance import router as maint_router
from erp_sim.seed import reset_database
from erp_sim.services.fl import router as fl_router
from erp_sim.services.inbound import router as ibd_router
from erp_sim.services.matdoc import router as matdoc_router
from erp_sim.services.outbound import router as obd_router
from erp_sim.services.physinv import router as pi_router

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="SCMTIPS Simulated ERP Service (erp-sim)",
    description="Local S/4HANA OData simulator for dev, testing and contract verification",
    version="1.0.0",
)


# 1. CSRF Token & Warehouse Faults Middleware
@app.middleware("http")
async def csrf_token_middleware(request: Request, call_next: Any) -> Response:
    fault_resp = await evaluate_warehouse_fault_header(request)
    if fault_resp is not None:
        return fault_resp
    is_csrf_fetch = request.headers.get("x-csrf-token", "").lower() == "fetch"
    response: Response = await call_next(request)
    if is_csrf_fetch:
        response.headers["x-csrf-token"] = f"csrf-token-sim-{uuid.uuid4().hex[:12]}"
    return response


# 2. SAP-Style Error Handler
@app.exception_handler(IdempotencyConflictError)
async def idem_conflict_handler(request: Request, exc: IdempotencyConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": exc.code, "message": {"lang": "en", "value": str(exc)}}},
    )


@app.exception_handler(LockContentionError)
async def lock_contention_handler(request: Request, exc: LockContentionError) -> JSONResponse:
    return JSONResponse(
        status_code=423,
        content={"error": {"code": exc.code, "message": {"lang": "en", "value": str(exc)}}},
    )


@app.exception_handler(HTTPException)
async def sap_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"ZSIM/{exc.status_code}",
                "message": {
                    "lang": "en",
                    "value": str(exc.detail),
                },
            }
        },
    )


# 3. Mount OData Services
app.include_router(ibd_router)
app.include_router(obd_router)
app.include_router(matdoc_router)
app.include_router(pi_router)
app.include_router(equipment_router)
app.include_router(maint_router)
app.include_router(faults_router)
app.include_router(fl_router)
app.include_router(ui_router)


# 4. Control Endpoints
@app.get("/_sim/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "erp-sim"}


@app.post("/_sim/reset")
def reset_endpoint(client: str = "100") -> dict[str, Any]:
    """Deterministic database truncate and reseed."""
    reset_database(client)
    return {"status": "reset_completed", "client": client}
