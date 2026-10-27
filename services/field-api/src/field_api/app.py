"""SCMTIPS Field Core API Application Factory (Task T1.011 / FR1.009)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from field_api.errors import (
    ERR_NOT_FOUND,
    FieldError,
    problem_json_response,
)
from field_api.logging import configure_logging
from field_api.middleware.auth import AuthMiddleware
from field_api.middleware.idempotency import IdempotencyMiddleware
from field_api.middleware.request_id import RequestIdMiddleware
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

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifecycle manager."""
    configure_logging()
    logger.info("SCMTIPS Field API starting up")
    yield
    logger.info("SCMTIPS Field API shutting down")


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
        detail_msg = exc.detail if isinstance(exc.detail, str) else "HTTP error occurred"
        return problem_json_response(
            status=exc.status_code,
            code=code,
            title="HTTP Error",
            detail=detail_msg,
            request=request,
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Any) -> JSONResponse:
        return problem_json_response(
            status=404,
            code=ERR_NOT_FOUND.code,
            title="Not Found",
            detail="The requested resource does not exist.",
            request=request,
        )

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

    return app


app = create_app()
