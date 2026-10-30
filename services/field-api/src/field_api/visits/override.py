"""Supervisor Geofence Override Module (Task T4.011 / FR4.011 / TC4.109).

A supervisor (field.visit.override) records a geofence override with a mandatory reason on an
existing visit; an audit event goes to the outbox for the core P13e mirror.

The supervisor is the authenticated caller and the tenant comes from the token. (Previously the
supervisor_id came from the request body and the tenant from a header with a hard-coded default,
so anyone could override any tenant's visit without a token.)
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import tenant_tx
from field_api.deps import require_permission

router = APIRouter(tags=["Visits"])


class OverrideRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Mandatory reason for geofence override")
    mock_location: bool | None = Field(None, description="Whether the phone reported a mock location provider")


@router.post("/v1/visits/{visit_id}/override")
async def override_visit_geofence(
    visit_id: str,
    req: OverrideRequest,
    principal: Principal = Depends(require_permission("field.visit.override")),
) -> dict[str, Any]:
    """Supervisor endpoint to override geofence failure on an existing visit record."""
    with tenant_tx(principal.tenant_id, principal.site_ids) as cur:
        cur.execute(
            """
            UPDATE field.site_visit
            SET override_by = %s::uuid, override_reason = %s, updated_at = NOW()
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            RETURNING id, site_id, status;
            """,
            (principal.id, req.reason, visit_id, principal.tenant_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Visit not found")
        cur.execute(
            """
            INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
            VALUES (field.uuid_generate_v7(), %s::uuid, %s::uuid, 'field.visit.override', %s::jsonb);
            """,
            (
                principal.tenant_id,
                visit_id,
                json.dumps({"visit_id": visit_id, "site_id": str(row[1]), "override_by": principal.id,
                            "reason": req.reason, "mock_location": req.mock_location}),
            ),
        )
    return {
        "id": str(row[0]),
        "status": row[2],
        "override_by": principal.id,
        "override_reason": req.reason,
        "message": "Geofence override recorded and audited",
    }
