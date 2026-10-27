"""Supervisor Geofence Override Module (Task T4.011 / FR4.011 / TC4.109).

Provides supervisor override facilities with mandatory reason recording
and core P13e audit event generation.
"""

from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from field_api.db import get_conn

router = APIRouter(tags=["Visits"])


class OverrideRequest(BaseModel):
    supervisor_id: str
    reason: str = Field(..., min_length=5, description="Mandatory reason for geofence override")


@router.post("/v1/visits/{visit_id}/override")
async def override_visit_geofence(
    visit_id: str,
    req: OverrideRequest,
    tenant_id: str = Header("e8eb2a80-d529-4bdd-b669-d21fe847cb74", alias="tenant_id"),
) -> dict[str, Any]:
    """Supervisor endpoint to override geofence failure on an existing visit record."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE field.site_visit
                SET override_by = %s::uuid, override_reason = %s, updated_at = NOW()
                WHERE id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id, site_id, status;
                """,
                (req.supervisor_id, req.reason, visit_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Visit not found")

            # Write audit event to outbox
            cur.execute(
                """
                INSERT INTO field.outbox (
                    id, tenant_id, aggregate_id, event_type, payload
                ) VALUES (
                    field.uuid_generate_v7(), %s::uuid, %s::uuid,
                    'field.visit.override', %s::jsonb
                );
                """,
                (
                    tenant_id,
                    visit_id,
                    json.dumps({
                        "visit_id": visit_id,
                        "site_id": str(row[1]),
                        "override_by": req.supervisor_id,
                        "reason": req.reason,
                    }),
                ),
            )
            conn.commit()

            return {
                "id": str(row[0]),
                "status": row[2],
                "override_by": req.supervisor_id,
                "override_reason": req.reason,
                "message": "Geofence override recorded and audited",
            }
