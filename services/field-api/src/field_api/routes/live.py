"""Device live channel (API2.15 / T2.053) backed by field.device_notification (C4).

Previously: an unauthenticated WebSocket and SSE stream over a process-local buffer, so any
caller could read any device's events across tenants, and events were lost on restart or on a
second worker. Now:
- the token is required (``access_token`` query parameter for WebSocket, Authorization header or
  ``access_token`` for SSE); invalid or revoked -> close 4401 / HTTP 401
- a device token may only read its own channel; other principals need field.device.read
- events are rows in field.device_notification (24 h replay via last_event_id), polled per
  connection, so every worker serves the same stream
- a second WebSocket for the same device closes the older one (4409), tracked on app.state
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from field_common.uuid7 import uuid7_str
from psycopg.types.json import Jsonb

from field_api.auth.jwt import Principal, verify_token
from field_api.auth.permissions import has_permission
from field_api.db import tenant_tx
from field_api.deps import device_is_revoked
from field_api.errors import ERR_AUTH_FORBIDDEN, ERR_AUTH_UNAUTHORIZED, FieldError

router = APIRouter(prefix="/v1/devices", tags=["Live"])

POLL_S = 1.0
PING_S = 20.0
REPLAY_HOURS = 24


def emit_device_tick(cur: Any, tenant_id: str, device_id: str, tick_type: str, payload: dict[str, Any]) -> str:
    """Queue a live event for a device inside the caller's transaction; returns the event id."""
    event_id = uuid7_str()
    cur.execute(
        """
        INSERT INTO field.device_notification (tenant_id, device_id, event_id, tick_type, payload, expires_at)
        VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '24 hours')
        """,
        (tenant_id, device_id, event_id, tick_type, Jsonb(payload)),
    )
    return event_id


def _authorise(token: str | None, device_id: str) -> Principal:
    if not token:
        raise ERR_AUTH_UNAUTHORIZED
    principal = verify_token(token)
    if principal.device_id:
        if principal.device_id != device_id:
            raise ERR_AUTH_FORBIDDEN
        if device_is_revoked(principal):
            raise ERR_AUTH_UNAUTHORIZED
    elif not has_permission(principal.permissions, "field.device.read"):
        raise ERR_AUTH_FORBIDDEN
    return principal


def _fetch(principal: Principal, device_id: str, after: str | None) -> list[dict[str, Any]]:
    with tenant_tx(principal.tenant_id, principal.site_ids) as cur:
        cur.execute(
            """
            SELECT event_id, tick_type, payload, created_at FROM field.device_notification
             WHERE device_id::text = %s AND expires_at > NOW()
               AND created_at > NOW() - make_interval(hours => %s)
               AND (%s::text IS NULL OR event_id > %s)
             ORDER BY event_id LIMIT 200
            """,
            (device_id, REPLAY_HOURS, after, after),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "kind": r[1], "payload": r[2] or {}, "subject_id": (r[2] or {}).get("subject_id"),
             "created_at": r[3].isoformat()} for r in rows]


@router.websocket("/{device_id}/live")
async def websocket_live_channel(
    websocket: WebSocket,
    device_id: str,
    last_event_id: str | None = Query(None),
    access_token: str | None = Query(None),
) -> None:
    token = access_token or (websocket.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
    try:
        principal = _authorise(token, device_id)
    except FieldError:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    registry: dict[str, WebSocket] = websocket.app.state.__dict__.setdefault("live_sockets", {})
    key = f"{principal.tenant_id}:{device_id}"
    older = registry.get(key)
    registry[key] = websocket
    if older is not None:
        with contextlib.suppress(Exception):
            await older.close(code=4409)
    cursor = last_event_id
    last_ping = datetime.now(UTC)
    try:
        while registry.get(key) is websocket:
            for ev in await asyncio.to_thread(_fetch, principal, device_id, cursor):
                await websocket.send_text(json.dumps(ev))
                cursor = ev["id"]
            if (datetime.now(UTC) - last_ping).total_seconds() >= PING_S:
                await websocket.send_text(json.dumps({"kind": "ping", "at": datetime.now(UTC).isoformat()}))
                last_ping = datetime.now(UTC)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=POLL_S)
                if msg == "ping":
                    await websocket.send_text(json.dumps({"kind": "pong"}))
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if registry.get(key) is websocket:
            registry.pop(key, None)


@router.get("/{device_id}/events")
async def sse_live_channel(
    request: Request,
    device_id: str,
    last_event_id: str | None = Query(None),
    access_token: str | None = Query(None),
    once: bool = Query(False, description="return pending events and close (polling / tests)"),
) -> StreamingResponse:
    header = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    principal = _authorise(header or access_token, device_id)
    start = request.headers.get("last-event-id") or last_event_id

    async def gen() -> AsyncGenerator[str]:
        cursor = start
        while True:
            for ev in await asyncio.to_thread(_fetch, principal, device_id, cursor):
                cursor = ev["id"]
                yield f"id: {ev['id']}\nevent: {ev['kind']}\ndata: {json.dumps(ev)}\n\n"
            if once or await request.is_disconnected():
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(POLL_S)

    return StreamingResponse(gen(), media_type="text/event-stream")
