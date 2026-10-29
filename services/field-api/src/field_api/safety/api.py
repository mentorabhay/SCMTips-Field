"""Safety and Climb Session API Endpoints (Task T4.044, T4.045, T4.046 / API4.15 / SCR4.13).

Provides:
- POST /v1/climb-sessions/{visit_id}/events (API4.15)
- POST /v1/safety/visits/{visit_id}/check-in
- POST /v1/safety/visits/{visit_id}/ack
- GET /v1/safety/active-visits (SCR4.13)
- POST /v1/safety/sweep (TC4.139)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from field_api.db import get_conn
from field_api.deps import Principal, require_principal
from field_api.safety.lone_worker import (
    acknowledge_lone_worker_escalation,
    checkin_lone_worker,
    run_lone_worker_escalation_sweep,
)
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Safety & Climb Sessions"])


class SafetyEventItem(BaseModel):
    device_seq: int = Field(..., description="Monotonic per-device event sequence number")
    type: str = Field(..., description="Event type: state_changed, harness_confirmed, checkpoint_reached, check_in, climb_safe_activated, etc.")
    altitude_m: float | None = Field(None, description="Current barometric altitude in meters")
    occurred_at: str = Field(..., description="ISO 8601 timestamp when event occurred")
    payload: dict[str, Any] | None = Field(default_factory=dict, description="Additional context")


class ClimbEventsUploadRequest(BaseModel):
    events: list[SafetyEventItem] = Field(..., min_length=1, description="List of safety events in device order")


class AcknowledgeRequest(BaseModel):
    notes: str | None = Field(None, description="Optional supervisor acknowledgment notes")


class CheckInRequest(BaseModel):
    altitude_m: float | None = Field(None, description="Current altitude in meters")
    tower_fl: str | None = Field(None, description="Current tower functional location code")


@router.post(
    "/v1/climb-sessions/{visit_id}/events",
    summary="Upload summarised safety events in device order (API4.15)",
    status_code=status.HTTP_200_OK,
)
def upload_climb_session_events(
    visit_id: str,
    req: ClimbEventsUploadRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Upload summarized climb safety events enforcing strict device sequence (API4.15 / FR4.067)."""
    t_id = principal.tenant_id

    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "FIELD-SAFE-400-IDEMPOTENCY-REQUIRED", "message": "Idempotency-Key header is required for safety uploads"},
        )

    # Sort incoming events by device_seq
    sorted_events = sorted(req.events, key=lambda x: x.device_seq)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Verify site visit exists
            cur.execute(
                "SELECT id, status FROM field.site_visit WHERE tenant_id = %s AND id = %s;",
                (t_id, visit_id),
            )
            v_row = cur.fetchone()
            if not v_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error_code": "FIELD-VIS-404-NOT-FOUND", "message": f"Site visit '{visit_id}' not found"},
                )

            # 2. Sequence gap check: ensure min device_seq <= max_existing_seq + 1
            cur.execute(
                "SELECT COALESCE(MAX(device_seq), 0) FROM field.climb_safety_event WHERE tenant_id = %s AND visit_id = %s;",
                (t_id, visit_id),
            )
            row = cur.fetchone()
            max_existing_seq = int(row[0]) if row else 0

            min_incoming_seq = sorted_events[0].device_seq
            if min_incoming_seq > (max_existing_seq + 1):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "FIELD-SAFE-409-SEQ-GAP",
                        "message": "Earlier device_seq missing (client resends)",
                        "expected_seq": max_existing_seq + 1,
                        "received_min_seq": min_incoming_seq,
                    },
                )

            # 3. Insert events idempotently
            accepted = 0
            duplicates = 0
            latest_alt = None
            has_activity = False

            for evt in sorted_events:
                cur.execute(
                    """
                    INSERT INTO field.climb_safety_event (
                        tenant_id, visit_id, device_seq, type,
                        altitude_m, payload, occurred_at, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, NOW()
                    )
                    ON CONFLICT (tenant_id, visit_id, device_seq) DO NOTHING
                    RETURNING id;
                    """,
                    (
                        t_id,
                        visit_id,
                        evt.device_seq,
                        evt.type,
                        evt.altitude_m,
                        json.dumps(evt.payload or {}),
                        evt.occurred_at,
                    ),
                )
                ins_row = cur.fetchone()
                if ins_row:
                    accepted += 1
                else:
                    duplicates += 1

                if evt.altitude_m is not None:
                    latest_alt = evt.altitude_m
                if evt.type in ("check_in", "harness_confirmed", "checkpoint_reached", "state_changed"):
                    has_activity = True

            # 4. Update visit heartbeat and altitude
            if has_activity or latest_alt is not None:
                alt_clause = ", last_altitude_m = %s" if latest_alt is not None else ""
                params: list[Any] = []
                if latest_alt is not None:
                    params.append(latest_alt)
                params.extend([t_id, visit_id])

                cur.execute(
                    f"""
                    UPDATE field.site_visit
                    SET last_heartbeat_at = NOW()
                        {alt_clause},
                        updated_at = NOW()
                    WHERE tenant_id = %s AND id = %s;
                    """,
                    tuple(params),
                )

            conn.commit()

    return {"accepted": accepted, "duplicates": duplicates}


@router.post(
    "/v1/safety/visits/{visit_id}/check-in",
    summary="Technician lone-worker check-in",
    status_code=status.HTTP_200_OK,
)
def api_lone_worker_checkin(
    visit_id: str,
    req: CheckInRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Restart lone-worker countdown timer on verbal or manual check-in (FR4.043)."""
    t_id = principal.tenant_id
    try:
        return checkin_lone_worker(
            tenant_id=t_id,
            visit_id=visit_id,
            user_id=principal.id,
            altitude_m=req.altitude_m,
            tower_fl=req.tower_fl,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "FIELD-VIS-404-NOT-FOUND", "message": str(e)},
        )


@router.post(
    "/v1/safety/visits/{visit_id}/ack",
    summary="Supervisor acknowledge lone-worker escalation",
    status_code=status.HTTP_200_OK,
)
def api_lone_worker_acknowledge(
    visit_id: str,
    req: AcknowledgeRequest,
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Acknowledge escalated visit from supervisor console (SCR4.13 / FR4.044)."""
    t_id = principal.tenant_id
    try:
        return acknowledge_lone_worker_escalation(
            tenant_id=t_id,
            visit_id=visit_id,
            acknowledged_by=principal.id,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "FIELD-VIS-404-NOT-FOUND", "message": str(e)},
        )


@router.get(
    "/v1/safety/active-visits",
    summary="List active site visits for lone-worker console monitor (SCR4.13)",
    status_code=status.HTTP_200_OK,
)
def api_list_active_safety_visits(
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Retrieve active visits with timer countdowns and escalation banners (SCR4.13)."""
    t_id = principal.tenant_id
    now = datetime.now(UTC)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                SELECT v.id, v.site_id, v.user_id, v.status, v.timer_interval_min,
                       v.last_heartbeat_at, v.last_altitude_m, v.last_tower_fl,
                       v.acked_at, s.code as site_code, s.name as site_name
                FROM field.site_visit v
                JOIN field.site s ON v.site_id = s.id
                WHERE v.tenant_id = %s
                  AND v.status IN ('checked_in', 'on_structure', 'overdue', 'escalated')
                ORDER BY
                    CASE v.status
                        WHEN 'escalated' THEN 1
                        WHEN 'overdue' THEN 2
                        WHEN 'on_structure' THEN 3
                        ELSE 4
                    END,
                    v.last_heartbeat_at ASC;
                """,
                (t_id,),
            )
            rows = cur.fetchall()

    visits: list[dict[str, Any]] = []
    has_escalation = False

    for r in rows:
        v_id = str(r[0])
        status_val = r[3]
        interval_min = r[4] or 20
        last_hb = r[5]
        last_alt = float(r[6]) if r[6] is not None else 0.0
        tower_fl = r[7] or "T01"
        acked_at = r[8]
        site_code = r[9]
        site_name = r[10]

        elapsed_s = (now - last_hb).total_seconds()
        total_limit_s = interval_min * 60
        remaining_s = max(0, int(total_limit_s - elapsed_s))

        is_escalated = status_val == "escalated"
        if is_escalated and not acked_at:
            has_escalation = True

        visits.append({
            "visit_id": v_id,
            "site_id": str(r[1]),
            "site_code": site_code,
            "site_name": site_name,
            "user_id": str(r[2]),
            "status": status_val,
            "tower_fl": tower_fl,
            "last_altitude_m": last_alt,
            "timer_interval_min": interval_min,
            "timer_remaining_s": remaining_s,
            "last_heartbeat_at": last_hb.isoformat(),
            "is_escalated": is_escalated,
            "is_acknowledged": acked_at is not None,
            "escalation_message": f"Overdue check-in at {site_code} ({tower_fl}) - Last altitude: {last_alt}m [MSG4.10]" if is_escalated else None,
        })

    return {
        "visits": visits,
        "total_active": len(visits),
        "has_escalation": has_escalation,
    }


@router.post(
    "/v1/safety/sweep",
    summary="Trigger lone-worker escalation sweep (TC4.139)",
    status_code=status.HTTP_200_OK,
)
def api_trigger_lone_worker_sweep(
    time_offset_min: int | None = Query(0, description="Virtual minute offset for testing time advance"),
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Execute sweep of active visits and escalate overdue workers (TC4.139)."""
    t_id = principal.tenant_id
    sim_time = datetime.now(UTC) + timedelta(minutes=time_offset_min or 0)
    transitions = run_lone_worker_escalation_sweep(tenant_id=t_id, current_time=sim_time)
    return {"transitions": transitions, "count": len(transitions)}
