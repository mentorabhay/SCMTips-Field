"""Fault Rules Admin CRUD API (Task T1.052 / PR1.14).

Enabled only when ERPSIM_FAULTS_ENABLED=true and X-Sim-Admin-Token matches.
"""

import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from erp_sim.db import get_conn

router = APIRouter(prefix="/_sim/faults", tags=["Simulator Admin"])

FAULTS_ENABLED = os.getenv("ERPSIM_FAULTS_ENABLED", "true").lower() in ("true", "1", "yes")
SIM_ADMIN_TOKEN = os.getenv("ERPSIM_ADMIN_TOKEN", "dev-sim-admin-token")


class FaultRuleIn(BaseModel):
    kind: str = Field(..., description="latency, http_5xx, lock, timeout, partial")
    service: str | None = None
    operation: str | None = None
    doc_key: str | None = None
    probability: float = Field(1.0, ge=0.0, le=1.0)
    count: int = Field(1, ge=1)
    ttl_s: int = Field(300, ge=1)
    seed: int | None = None


def verify_admin(token: str | None) -> None:
    if not FAULTS_ENABLED:
        raise HTTPException(status_code=403, detail="Fault injection disabled")
    if token != SIM_ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid X-Sim-Admin-Token")


@router.get("")
async def list_faults(
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
) -> list[dict[str, Any]]:
    verify_admin(x_sim_admin_token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, kind, service, operation, doc_key, probability, count, ttl_s, active, created_at
                FROM erpsim.fault_rule
                ORDER BY created_at DESC;
            """
            )
            return [
                {
                    "id": str(r[0]),
                    "kind": r[1],
                    "service": r[2],
                    "operation": r[3],
                    "doc_key": r[4],
                    "probability": float(r[5]),
                    "count": r[6],
                    "ttl_s": r[7],
                    "active": r[8],
                    "created_at": r[9].isoformat(),
                }
                for r in cur.fetchall()
            ]


@router.post("", status_code=201)
async def create_fault(
    rule_in: FaultRuleIn,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
) -> dict[str, Any]:
    verify_admin(x_sim_admin_token)
    rule_id = uuid.uuid4()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erpsim.fault_rule (
                    id, client, kind, service, operation, doc_key, probability, count, ttl_s, seed, active
                )
                VALUES (%s, '100', %s, %s, %s, %s, %s, %s, %s, %s, true);
            """,
                (
                    rule_id,
                    rule_in.kind,
                    rule_in.service,
                    rule_in.operation,
                    rule_in.doc_key,
                    rule_in.probability,
                    rule_in.count,
                    rule_in.ttl_s,
                    rule_in.seed,
                ),
            )
            conn.commit()

    return {"id": str(rule_id), "status": "active", **rule_in.model_dump()}


@router.delete("/{rule_id}")
async def delete_fault(
    rule_id: str,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
) -> dict[str, Any]:
    verify_admin(x_sim_admin_token)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM erpsim.fault_rule WHERE id = %s;", (rule_id,))
        conn.commit()
    return {"id": rule_id, "deleted": True}
