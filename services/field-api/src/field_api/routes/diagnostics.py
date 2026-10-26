"""Latency Diagnostic Probe Endpoint (API1.12 / FR1.016)."""

import time

from fastapi import APIRouter, Depends
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.deps import require_principal

router = APIRouter(prefix="/v1/diagnostics", tags=["Diagnostics"])


class ProbeRequest(BaseModel):
    client_sent_ms: float = Field(..., description="Client epoch timestamp in ms")
    device_id: str | None = None
    is_probe: bool = True


class ProbeResponse(BaseModel):
    probe_id: str
    client_sent_ms: float
    server_received_ms: float
    server_duration_ms: float
    status: str = "ok"


@router.post("/probe", response_model=ProbeResponse)
async def latency_probe(
    probe_in: ProbeRequest,
    principal: Principal = Depends(require_principal),
) -> ProbeResponse:
    """Execute end-to-end latency measurement probe through full middleware stack."""
    recv_ms = time.time() * 1000.0
    probe_id = uuid7_str()
    duration_ms = (time.time() * 1000.0) - recv_ms

    return ProbeResponse(
        probe_id=probe_id,
        client_sent_ms=probe_in.client_sent_ms,
        server_received_ms=recv_ms,
        server_duration_ms=round(duration_ms, 3),
        status="ok",
    )
