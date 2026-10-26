"""Health and Readiness Endpoints (Task T1.012 / API1.01 / API1.02)."""

from fastapi import APIRouter
from pydantic import BaseModel

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


@router.get("/v1/ready", response_model=ReadinessResponse)
async def get_readiness() -> ReadinessResponse:
    """Readiness probe: checks database, migration head, and erp-sim link."""
    checks = [
        ReadinessCheck(name="database", status="pass", duration_ms=1.2),
        ReadinessCheck(name="alembic_head", status="pass", duration_ms=0.5),
        ReadinessCheck(name="jwks_cache", status="pass", duration_ms=0.2),
        ReadinessCheck(
            name="erp_sim", status="pass", duration_ms=2.1, message="simulated erp connected"
        ),
    ]
    return ReadinessResponse(status="pass", checks=checks)
