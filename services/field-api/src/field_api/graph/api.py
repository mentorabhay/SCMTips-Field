"""3D Routing API (Task T4.051 / FR4.047 / API4.11).

Exposes:
- GET /v1/sites/{id}/route?from={from}&to={to}
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, status
from field_api.deps import Principal, require_principal
from field_api.graph.route3d import compute_3d_route
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Site Graph & Routing"])


class Route3DResponse(BaseModel):
    cost: float = Field(..., description="Weighted route cost: walk_m + 3 * climb_m")
    climb_m: float = Field(..., description="Total vertical climb distance in meters")
    walk_m: float = Field(..., description="Total horizontal walk distance in meters")
    nodes: list[str] = Field(..., description="Ordered list of node names along the path")
    guidance: str = Field(..., description="Pre-climb spoken newcomer guidance text")


@router.get(
    "/v1/sites/{id}/route",
    response_model=Route3DResponse,
    summary="3D route with climb weighting and guidance (API4.11)",
    status_code=status.HTTP_200_OK,
)
def api_get_3d_route(
    id: str,
    from_node: str = Query(..., alias="from", description="Source node name or UUID"),
    to_node: str = Query(..., alias="to", description="Target node name or UUID"),
    principal: Principal = Depends(require_principal),
) -> Route3DResponse:
    """Compute 3D route between two nodes with climb weighting and safety guidance (API4.11)."""
    result = compute_3d_route(
        tenant_id=principal.tenant_id,
        site_id=id,
        from_ref=from_node,
        to_ref=to_node,
    )
    return Route3DResponse(
        cost=result["cost"],
        climb_m=result["climb_m"],
        walk_m=result["walk_m"],
        nodes=result["nodes"],
        guidance=result["guidance"],
    )
