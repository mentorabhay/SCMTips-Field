"""Live Tick Channel Hub: WebSocket and SSE Streams (Task T2.053 / FR2.052, TC2.144, TC2.145)."""

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from field_common.uuid7 import uuid7_str

router = APIRouter(prefix="/v1/devices", tags=["Live"])

# In-memory notification buffer per device for 24h replay
_NOTIFICATION_BUFFER: dict[str, list[dict[str, Any]]] = defaultdict(list)
# Active WebSocket connections per device
_ACTIVE_WEBSOCKETS: dict[str, set[WebSocket]] = defaultdict(set)


def emit_device_tick(
    tenant_id: str,
    device_id: str,
    tick_type: str,
    capture_id: str | None = None,
    task_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """Emit a live tick to the device, storing in the 24h buffer and broadcasting to active connections (T2.053)."""
    event_id = uuid7_str()
    now_iso = datetime.now(UTC).isoformat()
    tick_payload: dict[str, Any] = {
        "event_id": event_id,
        "id": event_id,
        "tenant_id": tenant_id,
        "device_id": device_id,
        "tick": tick_type,
        "type": tick_type,
        "capture_id": capture_id,
        "task_id": task_id,
        "detail": detail,
        "timestamp": now_iso,
    }

    # Store in replay buffer
    _NOTIFICATION_BUFFER[device_id].append(tick_payload)
    if len(_NOTIFICATION_BUFFER[device_id]) > 1000:
        _NOTIFICATION_BUFFER[device_id].pop(0)

    # Broadcast to active WebSockets
    payload_str = json.dumps(tick_payload)
    for ws in list(_ACTIVE_WEBSOCKETS[device_id]):
        with contextlib.suppress(Exception):
            asyncio.create_task(ws.send_text(payload_str))

    return tick_payload


@router.websocket("/{device_id}/live")
async def websocket_live_channel(
    websocket: WebSocket,
    device_id: str,
    last_event_id: str | None = Query(None),
) -> None:
    """Live WebSocket channel pushing received, verified, mismatch, posted ticks (T2.053 / TC2.144)."""
    await websocket.accept()
    _ACTIVE_WEBSOCKETS[device_id].add(websocket)

    try:
        # Replay missed events if last_event_id is provided
        if last_event_id:
            buffer = _NOTIFICATION_BUFFER[device_id]
            found_idx = -1
            for idx, item in enumerate(buffer):
                if item["event_id"] == last_event_id or item.get("id") == last_event_id:
                    found_idx = idx
                    break

            # Send all events after last_event_id
            start_idx = found_idx + 1 if found_idx != -1 else 0
            for item in buffer[start_idx:]:
                await websocket.send_text(json.dumps(item))

        # Heartbeat ping loop every 20 seconds (D2.02)
        while True:
            try:
                # Wait for client message or timeout for ping
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                # Client may send pongs or commands
                if msg == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except TimeoutError:
                # Send server ping
                await websocket.send_text(
                    json.dumps({"type": "ping", "timestamp": datetime.now(UTC).isoformat()})
                )
    except WebSocketDisconnect:
        pass
    finally:
        _ACTIVE_WEBSOCKETS[device_id].discard(websocket)


@router.get("/{device_id}/events")
async def sse_live_channel(
    device_id: str,
    last_event_id: str | None = Query(None),
) -> StreamingResponse:
    """SSE fallback live channel (T2.053 / TC2.145)."""

    async def event_generator() -> AsyncGenerator[str]:
        # Replay missed events
        sent_ids = set()
        if last_event_id:
            buffer = _NOTIFICATION_BUFFER[device_id]
            found = False
            for item in buffer:
                if found:
                    sent_ids.add(item["event_id"])
                    yield f"id: {item['event_id']}\ndata: {json.dumps(item)}\n\n"
                elif item["event_id"] == last_event_id or item.get("id") == last_event_id:
                    found = True

        # Live loop
        last_checked = len(_NOTIFICATION_BUFFER[device_id])
        while True:
            buffer = _NOTIFICATION_BUFFER[device_id]
            if len(buffer) > last_checked:
                for item in buffer[last_checked:]:
                    if item["event_id"] not in sent_ids:
                        sent_ids.add(item["event_id"])
                        yield f"id: {item['event_id']}\ndata: {json.dumps(item)}\n\n"
                last_checked = len(buffer)

            # Send SSE keepalive comment every 15s
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
