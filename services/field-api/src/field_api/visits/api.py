"""Site Visits & Check-in / Check-out API (Tasks T4.010, T4.011, T4.012 / FR4.009 - FR4.012 / TC4.107 - TC4.110).

Implements geofence validation, permit verification, supervisor override,
lone-worker timer initialization, and check-out outbox warnings.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.db import tenant_tx
from field_api.deps import require_permission, require_site_scope

router = APIRouter(tags=["Visits"])


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance in meters between two lat/lon points."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


class CheckInRequest(BaseModel):
    # The visitor is the authenticated principal; user_id / device_id in the body are ignored.
    user_id: str | None = None
    device_id: str | None = None
    permit_ref: str = Field(..., min_length=4, max_length=40)
    permit_valid_until: datetime
    lat: float
    lon: float
    accuracy_m: float
    captured_at: datetime | None = None
    baro_baseline_hpa: float | None = None
    timer_interval_min: int = 20
    override_by: str | None = None
    override_reason: str | None = None


class CheckOutRequest(BaseModel):
    unsynced_count: int = 0


@router.post("/v1/sites/{site_id}/visits", status_code=status.HTTP_201_CREATED)
async def check_in(
    site_id: str,
    req: CheckInRequest,
    principal: Principal = Depends(require_permission("field.visit.checkin")),
) -> dict[str, Any]:
    """Check in to a site validating geofence distance and permit validity window.

    Tenant, site scope and visitor come from the token. (Previously the tenant came from a client
    header with a hard-coded fallback, no token was needed, and any caller could name any
    override_by to skip the geofence.) Overriding at check-in needs field.visit.override, and the
    override is recorded as the calling supervisor.
    """
    require_site_scope(site_id, principal)
    tenant_id = principal.tenant_id
    if req.override_by or req.override_reason:
        if not has_permission(principal.permissions, "field.visit.override"):
            raise HTTPException(status_code=403, detail={"error_code": "FIELD-AUTH-403-FORBIDDEN",
                                                         "message": "Geofence override needs field.visit.override"})
        if not req.override_reason or len(req.override_reason.strip()) < 5:
            raise HTTPException(status_code=422, detail="FIELD-VIS-422-OVERRIDE: an override needs a reason")
        req.override_by = principal.id
    now = req.captured_at or datetime.now(UTC)

    # 1. Validate permit validity window
    # Ensure timezone aware comparison
    permit_expiry = req.permit_valid_until
    if permit_expiry.tzinfo is None:
        permit_expiry = permit_expiry.replace(tzinfo=UTC)
    checkin_time = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    if permit_expiry < checkin_time:
        raise HTTPException(
            status_code=422,
            detail="FIELD-VIS-422-PERMIT: MSG4.03: Site access permit expired or invalid for check-in time",
        )

    # 2. Query site geofence (RLS scope = the token's tenant and sites, transaction-local)
    with tenant_tx(tenant_id, principal.site_ids) as cur:
        cur.execute(
            """
            SELECT id, lat, lon, geofence_radius_m
            FROM field.site
            WHERE id = %s::uuid AND tenant_id = %s::uuid;
            """,
            (site_id, tenant_id),
        )
        site_row = cur.fetchone()
        if not site_row:
            raise HTTPException(status_code=404, detail="Site not found")

        site_lat = float(site_row[1]) if site_row[1] is not None else None
        site_lon = float(site_row[2]) if site_row[2] is not None else None
        radius_m = site_row[3] or 150

        # 3. Geofence evaluation
        is_overridden = bool(req.override_by and req.override_reason)
        if not is_overridden:
            # Accuracy requirement: accuracy <= 50 m
            if req.accuracy_m > 50.0:
                raise HTTPException(
                    status_code=422,
                    detail=f"FIELD-VIS-422-GEOFENCE: GPS accuracy {req.accuracy_m:.1f} m exceeds maximum allowed 50 m",
                )

            if site_lat is not None and site_lon is not None:
                dist = haversine_distance_m(req.lat, req.lon, site_lat, site_lon)
                # Requirement: distance - accuracy <= radius
                effective_dist = dist - req.accuracy_m
                if effective_dist > radius_m:
                    raise HTTPException(
                        status_code=422,
                        detail=f"FIELD-VIS-422-GEOFENCE: Location {effective_dist:.1f} m is outside site geofence radius {radius_m} m",
                    )

        # 4. Insert site visit
        visit_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO field.site_visit (
                id, tenant_id, site_id, user_id, device_id,
                permit_ref, permit_valid_until, checkin_at,
                checkin_lat, checkin_lon, checkin_accuracy_m,
                override_by, override_reason, baro_baseline_hpa,
                timer_interval_min, last_heartbeat_at, status
            ) VALUES (
                %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, 'checked_in'
            ) RETURNING id, status, timer_interval_min, checkin_at;
            """,
            (
                visit_id,
                tenant_id,
                site_id,
                principal.id,
                principal.device_id,
                req.permit_ref,
                permit_expiry,
                checkin_time,
                req.lat,
                req.lon,
                req.accuracy_m,
                req.override_by,
                req.override_reason,
                req.baro_baseline_hpa,
                req.timer_interval_min,
                checkin_time,
            ),
        )
        v_res = cur.fetchone()
        if not v_res:
            raise HTTPException(status_code=500, detail="Failed to create visit record")
        v_id, v_status, v_interval, v_checkin = v_res

        # 5. If overridden, emit audit event to outbox
        if is_overridden:
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
                    json.dumps(
                        {
                            "visit_id": visit_id,
                            "site_id": site_id,
                            "override_by": req.override_by,
                            "reason": req.override_reason,
                            "reported_accuracy_m": req.accuracy_m,
                        }
                    ),
                ),
            )

        return {
            "id": str(v_id),
            "site_id": site_id,
            "user_id": principal.id,
            "status": v_status,
            "timer_interval_min": v_interval,
            "checkin_at": v_checkin.isoformat(),
            "override": is_overridden,
        }


@router.patch("/v1/visits/{visit_id}")
async def check_out(
    visit_id: str,
    req: CheckOutRequest,
    principal: Principal = Depends(require_permission("field.visit.checkin")),
) -> dict[str, Any]:
    """Check out of site, stop timer, and return warning if outbox items remain unsynced.

    Only the visitor themself, or a supervisor with field.visit.override, can close a visit.
    """
    tenant_id = principal.tenant_id
    is_supervisor = has_permission(principal.permissions, "field.visit.override")
    with tenant_tx(tenant_id, principal.site_ids) as cur:
        cur.execute(
            """
            UPDATE field.site_visit
            SET status = 'checked_out', checkout_at = NOW(), updated_at = NOW()
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND (%s OR user_id::text = %s)
            RETURNING id, site_id, status, checkin_at, checkout_at;
            """,
            (visit_id, tenant_id, is_supervisor, principal.id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Visit not found")

        warning = None
        if req.unsynced_count > 0:
            warning = f"MSG4.18: You have {req.unsynced_count} unsynced items. Connect to network to complete upload."

        return {
            "id": str(row[0]),
            "site_id": str(row[1]),
            "status": row[2],
            "checkin_at": row[3].isoformat(),
            "checkout_at": row[4].isoformat() if row[4] else None,
            "unsynced_count": req.unsynced_count,
            "warning": warning,
        }
