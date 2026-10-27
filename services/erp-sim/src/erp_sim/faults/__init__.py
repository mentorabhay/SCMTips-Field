"""ERP Sim Fault Injection Engine (Task T1.052 / PR1.14 / PR1.15 / Task T3.009).

Injects deterministic or probabilistic faults:
- latency: artificial delay (e.g. 1-5s)
- http_5xx: HTTP 500 / 503 Internal Error
- lock: synthetic ZSIM/LOCKED error
- timeout: gateway timeout simulation
- partial: incomplete result payload or dropped response
- warehouse fault profiles via X-Sim-Fault-Profile
"""

import asyncio
import os
import random
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from fastapi import HTTPException

from erp_sim.faults.warehouse import evaluate_warehouse_fault_header

logger = structlog.get_logger(__name__)

FAULTS_ENABLED = os.getenv("ERPSIM_FAULTS_ENABLED", "true").lower() in ("true", "1", "yes")
SIM_ADMIN_TOKEN = os.getenv("ERPSIM_ADMIN_TOKEN", "dev-sim-admin-token")


async def evaluate_faults(
    cur: psycopg.Cursor[Any],
    client: str,
    service: str,
    operation: str,
    doc_key: str | None = None,
) -> None:
    """Evaluate active fault rules matching service and operation."""
    if not FAULTS_ENABLED:
        return

    now = datetime.now(UTC)

    cur.execute(
        """
        SELECT id, kind, probability, count, ttl_s, seed, created_at
        FROM erpsim.fault_rule
        WHERE client = %s AND active = true
          AND (service IS NULL OR service = %s)
          AND (operation IS NULL OR operation = %s)
          AND (doc_key IS NULL OR doc_key = %s)
        FOR UPDATE;
    """,
        (client, service, operation, doc_key),
    )
    rows = cur.fetchall()

    for r in rows:
        rule_id, kind, prob, count, ttl_s, seed, created_at = (
            r[0],
            r[1],
            float(r[2]),
            r[3],
            r[4],
            r[5],
            r[6],
        )

        # Check TTL
        age_s = (now - created_at).total_seconds()
        if age_s > ttl_s:
            cur.execute("UPDATE erpsim.fault_rule SET active = false WHERE id = %s;", (rule_id,))
            continue

        if count <= 0:
            cur.execute("UPDATE erpsim.fault_rule SET active = false WHERE id = %s;", (rule_id,))
            continue

        # Probability check
        rnd = random.Random(seed).random() if seed is not None else random.random()
        if rnd > prob:
            continue

        # Consume 1 count
        new_count = count - 1
        cur.execute(
            "UPDATE erpsim.fault_rule SET count = %s, active = (%s > 0) WHERE id = %s;",
            (new_count, new_count, rule_id),
        )

        logger.info(
            "fault_rule_triggered",
            rule_id=str(rule_id),
            kind=kind,
            service=service,
            operation=operation,
        )

        if kind == "latency":
            await asyncio.sleep(1.5)
        elif kind == "http_5xx":
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "ZSIM/HTTP500",
                        "message": {"lang": "en", "value": "Injected synthetic SAP 500 error"},
                    }
                },
            )
        elif kind == "lock":
            raise HTTPException(
                status_code=423,
                detail={
                    "error": {
                        "code": "ZSIM/LOCKED",
                        "message": {
                            "lang": "en",
                            "value": f"Object {doc_key or operation} locked by another transaction [SYNTHETIC]",
                        },
                    }
                },
            )
        elif kind == "timeout":
            await asyncio.sleep(3.0)
            raise HTTPException(
                status_code=504,
                detail={
                    "error": {
                        "code": "ZSIM/TIMEOUT",
                        "message": {"lang": "en", "value": "Gateway Timeout [SYNTHETIC]"},
                    }
                },
            )
        elif kind == "partial":
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "code": "ZSIM/PARTIAL",
                        "message": {
                            "lang": "en",
                            "value": "Network connection reset during transmission [SYNTHETIC]",
                        },
                    }
                },
            )


__all__ = ["evaluate_faults", "evaluate_warehouse_fault_header", "FAULTS_ENABLED", "SIM_ADMIN_TOKEN"]
