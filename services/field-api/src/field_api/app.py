"""SCMTIPS Field Core API Application Factory (Task T1.011 / FR1.009)."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from field_api.assistant.api import router as assistant_router
from field_api.audit.api import router as audit_router
from field_api.audits.reports import router as audit_reports_router
from field_api.briefs.api import router as briefs_router
from field_api.codes.api import router as codes_router
from field_api.equipment.api import router as equipment_router
from field_api.errors import (
    ERR_NOT_FOUND,
    FieldError,
    problem_json_response,
)
from field_api.graph.api import router as graph_router
from field_api.installed_base.api import router as installed_base_router
from field_api.jobs.confirmations import router as job_confirmations_router
from field_api.jobs.console import router as job_console_router
from field_api.logging import configure_logging
from field_api.middleware.auth import AuthMiddleware
from field_api.middleware.idempotency import IdempotencyMiddleware
from field_api.middleware.request_id import RequestIdMiddleware
from field_api.models.api import router as models_router
from field_api.pi.api import router as pi_router
from field_api.posting.routes import router as posting_router
from field_api.routes.auth import router as auth_router
from field_api.routes.captures import router as captures_router
from field_api.routes.consents import router as consents_router
from field_api.routes.devices import router as devices_router
from field_api.routes.diagnostics import router as diagnostics_router
from field_api.routes.health import router as health_router
from field_api.routes.live import router as live_router
from field_api.routes.locations import router as locations_router
from field_api.routes.materials import router as materials_router
from field_api.routes.me import router as me_router
from field_api.routes.sites import router as sites_router
from field_api.routes.status import router as status_router
from field_api.routes.voice import router as voice_router
from field_api.safety.api import router as safety_router
from field_api.sandbox.api import router as sandbox_router
from field_api.secrets import missing_required_secrets
from field_api.sitepack.api import router as sitepack_router
from field_api.sites.tree import router as site_tree_router
from field_api.tasks.api import router as tasks_router
from field_api.trails.api import router as trails_router
from field_api.vision.api import router as vision_router
from field_api.visits.api import router as visits_router
from field_api.visits.override import router as visits_override_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifecycle manager."""
    configure_logging()
    missing = missing_required_secrets()
    if missing:
        raise RuntimeError("field-api refuses to start: " + "; ".join(missing))
    logger.info("SCMTIPS Field API starting up")
    yield
    logger.info("SCMTIPS Field API shutting down")


DEFAULT_CONSOLE_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def console_origins() -> list[str]:
    """Browser origins allowed to call the API (the field console). FIELD_CONSOLE_ORIGINS is a comma
    list; a wildcard is refused so a token can never be used from an arbitrary page."""
    raw = os.getenv("FIELD_CONSOLE_ORIGINS", DEFAULT_CONSOLE_ORIGINS)
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if any("*" in o for o in origins):
        raise RuntimeError("FIELD_CONSOLE_ORIGINS must list explicit origins; '*' is not allowed")
    return origins


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="SCMTIPS Field API",
        version="0.1.0",
        description="Field truth captured in one look — verified ERP material posting",
        lifespan=lifespan,
    )

    # 1. Middleware in strict execution order
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Outermost, so a browser preflight is answered before auth. Explicit origins only, never "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=console_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "Last-Event-ID",
                       "X-Request-ID"],
        expose_headers=["ETag", "X-Request-ID", "Idempotent-Replayed"],
    )

    # 2. RFC 9457 Problem+JSON Exception Handlers
    @app.exception_handler(FieldError)
    async def field_error_handler(request: Request, exc: FieldError) -> JSONResponse:
        return problem_json_response(
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            request=request,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_json_response(
            status=422,
            code="FIELD-VAL-422-SCHEMA-ERROR",
            title="Validation Error",
            detail="Request body or query parameters failed schema validation.",
            request=request,
            errors=errors,
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = f"FIELD-HTTP-{exc.status_code}-ERROR"
        if exc.status_code == 404:
            code = ERR_NOT_FOUND.code
        extra_fields = None
        if isinstance(exc.detail, dict):
            code = exc.detail.get("error_code", code)
            detail_msg = exc.detail.get("message", "HTTP error occurred")
            extra_fields = exc.detail
        elif isinstance(exc.detail, str):
            detail_msg = exc.detail
        else:
            detail_msg = "HTTP error occurred"
        res = problem_json_response(
            status=exc.status_code,
            code=code,
            title="HTTP Error",
            detail=detail_msg,
            request=request,
        )
        if extra_fields is not None:
            import json as _json

            content = _json.loads(res.body.decode())
            content["detail"] = extra_fields
            return JSONResponse(
                status_code=exc.status_code, content=content, headers=dict(res.headers)
            )
        return res

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Any) -> JSONResponse:
        code = ERR_NOT_FOUND.code
        detail_msg = "The requested resource does not exist."
        extra = None
        if isinstance(exc, HTTPException):
            if isinstance(exc.detail, dict):
                code = exc.detail.get("error_code", code)
                detail_msg = exc.detail.get("message", detail_msg)
                extra = exc.detail
            elif isinstance(exc.detail, str) and exc.detail not in ("Not Found", ""):
                detail_msg = exc.detail
        res = problem_json_response(
            status=404,
            code=code,
            title="Not Found",
            detail=detail_msg,
            request=request,
        )
        if extra is not None:
            import json as _json

            content = _json.loads(res.body.decode())
            content["detail"] = extra
            return JSONResponse(status_code=404, content=content, headers=dict(res.headers))
        return res

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled server exception", error=str(exc))
        return problem_json_response(
            status=500,
            code="FIELD-SYS-500-INTERNAL",
            title="Internal Server Error",
            detail="An unexpected internal server error occurred.",
            request=request,
        )

    # 3. Mount Route Handlers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(sites_router)
    app.include_router(locations_router)
    app.include_router(materials_router)
    app.include_router(devices_router)
    app.include_router(consents_router)
    app.include_router(captures_router)
    app.include_router(voice_router)
    app.include_router(live_router)
    app.include_router(diagnostics_router)
    app.include_router(status_router)
    app.include_router(posting_router)
    app.include_router(tasks_router)
    app.include_router(pi_router)
    app.include_router(site_tree_router)
    app.include_router(visits_router)
    app.include_router(visits_override_router)
    app.include_router(audit_router)
    app.include_router(equipment_router)
    app.include_router(safety_router)
    app.include_router(trails_router)
    app.include_router(graph_router)
    app.include_router(models_router)
    app.include_router(audit_reports_router)
    app.include_router(sitepack_router)
    app.include_router(installed_base_router)
    app.include_router(job_confirmations_router)
    app.include_router(job_console_router)
    app.include_router(codes_router)
    app.include_router(sandbox_router)
    app.include_router(assistant_router)
    app.include_router(briefs_router)
    app.include_router(vision_router)

    return app


app = create_app()
