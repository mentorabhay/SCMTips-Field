"""The OEM simulator's routers, mounted by erp-sim under /_oem when ERPSIM_OEM_ENABLED is true (default).

``include(app)`` is what erp-sim calls; ``app`` is a standalone FastAPI app with the same routes (tests, or running
the OEM simulator on its own: ``uvicorn oem_sim.app:app``).
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from oem_sim.pages import router as pages_router
from oem_sim.routes import router as api_router

ENABLED_ENV = "ERPSIM_OEM_ENABLED"


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "true").strip().lower() in ("true", "1", "yes")


def include(app: FastAPI) -> None:
    app.include_router(api_router)
    app.include_router(pages_router)


app = FastAPI(title="SCMTIPS OEM simulator (SAMPLE maker, M5 case C3)", version="1.0.0")
include(app)
