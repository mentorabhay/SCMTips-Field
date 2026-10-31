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
from typing import Any

import psycopg
import structlog
from fastapi import HTTPException

from erp_sim.db import DATABASE_URL
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
    """Evaluate active fault rules matching service and operation.

    The rule bookkeeping (expiry, count) runs on its own autocommit connection, not on the caller's
    cursor: an injected fault makes the caller roll back, which used to roll back the count too, so a
    rule armed for one failure failed every call until its TTL ran out (PR1.14). ``cur`` is kept for
    the call sites and is not written to.
    """
    if not FAULTS_ENABLED:
        return
    del cur

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as fc:
        fc.execute(
            """
            UPDATE erpsim.fault_rule SET active = false
            WHERE client = %s AND active = true
              AND (count <= 0 OR created_at + ttl_s * interval '1 second' < now());
            """,
            (client,),
        )
        fc.execute(
            """
            SELECT id, kind, probability, seed
            FROM erpsim.fault_rule
            WHERE client = %s AND active = true
              AND (service IS NULL OR service = %s)
              AND (operation IS NULL OR operation = %s)
              AND (doc_key IS NULL OR doc_key = %s)
            ORDER BY created_at;
            """,
            (client, service, operation, doc_key),
        )
        rules = fc.fetchall()
        fired: tuple[Any, str] | None = None
        for rule_id, kind, prob, seed in rules:
            rnd = random.Random(seed).random() if seed is not None else random.random()
            if rnd > float(prob):
                continue
            # Consume one count atomically; a concurrent call may have used the last one.
            fc.execute(
                """
                UPDATE erpsim.fault_rule SET count = count - 1, active = (count - 1 > 0)
                WHERE id = %s AND active = true AND count > 0
                RETURNING count;
                """,
                (rule_id,),
            )
            if fc.fetchone() is not None:
                fired = (rule_id, str(kind))
                break
    if fired is None:
        return
    rule_id, kind = fired
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
