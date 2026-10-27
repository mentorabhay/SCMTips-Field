"""Warehouse Fault Profiles for erp-sim (Task T3.009).

Implements:
- warehouse_lock (HTTP 423, 30% probability or deterministic trigger)
- timeout_after_commit (5% probability or deterministic trigger)
- validation_400 (HTTP 400 Bad Request)
- latency_p95_2s (2.0s artificial sleep)
- Controlled via X-Sim-Fault-Profile header
- Strictly rejects X-Sim-Fault-Profile in production environments
"""

import asyncio
import os
import random

from fastapi import Request
from fastapi.responses import JSONResponse

PROFILES = {
    "warehouse_lock",
    "timeout_after_commit",
    "validation_400",
    "latency_p95_2s",
}


async def evaluate_warehouse_fault_header(request: Request) -> JSONResponse | None:
    """Inspect request headers for X-Sim-Fault-Profile and apply simulated faults."""
    fault_profile = request.headers.get("x-sim-fault-profile")
    if not fault_profile:
        return None

    env = os.getenv("ENVIRONMENT", os.getenv("FIELD_ENV", "development")).lower()
    # Reject in production builds per FR3.040 / FR3.043
    if env in ("production", "prod"):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "FIELD-FAULT-PROD-REJECTED",
                    "message": "X-Sim-Fault-Profile header is strictly forbidden in production",
                }
            },
        )

    profile_name = fault_profile.strip().lower()
    if profile_name not in PROFILES:
        return None

    if profile_name == "warehouse_lock":
        # 30% probability unless forced
        if random.random() < 0.30 or request.headers.get("x-sim-force-fault") == "true":
            return JSONResponse(
                status_code=423,
                content={
                    "error": {
                        "code": "ZSIM/LOCKED",
                        "message": {
                            "lang": "en",
                            "value": "Document is locked by concurrent warehouse picking session (simulated fault)",
                        },
                    }
                },
            )

    elif profile_name == "timeout_after_commit":
        if random.random() < 0.05 or request.headers.get("x-sim-force-fault") == "true":
            await asyncio.sleep(0.5)
            return JSONResponse(
                status_code=504,
                content={
                    "error": {
                        "code": "ZSIM/GATEWAY-TIMEOUT",
                        "message": {
                            "lang": "en",
                            "value": "Gateway timed out waiting for backend commit response (simulated fault)",
                        },
                    }
                },
            )

    elif profile_name == "validation_400":
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ZSIM/VALIDATION-ERROR",
                    "message": {
                        "lang": "en",
                        "value": "Simulated SAP validation failure: Storage bin not found in storage type",
                    },
                }
            },
        )

    elif profile_name == "latency_p95_2s":
        await asyncio.sleep(2.0)

    return None
