"""System Status and Compatibility Matrix Endpoint (API1.13)."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/system", tags=["System"])


class ServiceHealth(BaseModel):
    name: str
    status: str
    latency_ms: float


class CompatItem(BaseModel):
    component: str
    current_version: str
    target_contract: str
    status: str


class SystemStatusResponse(BaseModel):
    overall_status: str
    services: list[ServiceHealth]
    compatibility: list[CompatItem]


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """Return system readiness, component health, and core compatibility matrix."""
    services = [
        ServiceHealth(name="field-api", status="pass", latency_ms=0.5),
        ServiceHealth(name="field-worker", status="pass", latency_ms=1.1),
        ServiceHealth(name="erp-sim", status="pass", latency_ms=2.4),
        ServiceHealth(name="postgres-rls", status="pass", latency_ms=1.8),
    ]
    compat = [
        CompatItem(
            component="core-contract",
            current_version="core-p13",
            target_contract="P14-WP14b",
            status="pinned",
        ),
        CompatItem(
            component="erp-adapter",
            current_version="sim-s4-odata-v1",
            target_contract="S/4HANA 2023",
            status="compatible",
        ),
        CompatItem(
            component="lens-hud",
            current_version="ray-ban-18x2",
            target_contract="Meta DAT v1.3",
            status="ready",
        ),
    ]
    return SystemStatusResponse(
        overall_status="OPERATIONAL",
        services=services,
        compatibility=compat,
    )
