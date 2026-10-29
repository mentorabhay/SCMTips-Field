"""Asset Model Versioning, Publishing, and Pinning (Task T4.059 / FR4.054 / API4.13 / API4.14 / TC4.146).

Manages:
- Semantic model publishing with step-up security.
- Published model immutability: PATCH on published BOM returns 409 FIELD-MOD-409-PUBLISHED (TC4.146).
- Equipment version pinning: installed equipment pinned to model version active at install time.
- Emits outbox event asset_model.published.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from field_api.db import get_conn
from field_api.models.balloons import assign_model_balloons_in_db

logger = structlog.get_logger(__name__)


def _to_uuid(val: str | None) -> str | None:
    if not val:
        return None
    try:
        return str(uuid.UUID(val))
    except (ValueError, TypeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, val))


def publish_asset_model(
    tenant_id: str,
    model_id: str,
    published_by: str,
) -> dict[str, Any]:
    """Publish a validated asset model version (API4.13 / FR4.054)."""
    pub_uuid = _to_uuid(published_by)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch model
            cur.execute(
                """
                SELECT id, equipment_class, version, status, sha256_hash
                FROM field.asset_model
                WHERE tenant_id = %s AND id = %s;
                """,
                (tenant_id, model_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error_code": "FIELD-MOD-404",
                        "message": f"Asset model '{model_id}' not found",
                    },
                )

            eq_class, version, current_status, sha256_hex = row[1], row[2], row[3], row[4]

            if current_status == "published":
                return {
                    "status": "published",
                    "balloons_assigned": 0,
                    "balloons_kept": 0,
                    "message": "Model version is already published",
                }

            if current_status != "validated":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "FIELD-MOD-409-NOT-VALID",
                        "message": f"Model is in '{current_status}' state and has unresolved validation issues",
                    },
                )

            # 2. Assign stable balloon numbers
            assigned, kept = assign_model_balloons_in_db(tenant_id, model_id, cur=cur)

            # 3. Mark published
            cur.execute(
                """
                UPDATE field.asset_model
                SET status = 'published',
                    published_at = NOW(),
                    published_by = %s,
                    updated_at = NOW()
                WHERE tenant_id = %s AND id = %s;
                """,
                (pub_uuid, tenant_id, model_id),
            )

            # 4. Outbox event: asset_model.published
            cur.execute(
                """
                INSERT INTO field.outbox (
                    id, tenant_id, aggregate_id, event_type, payload
                ) VALUES (
                    %s, %s, %s, 'asset_model.published', %s
                );
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    model_id,
                    json.dumps(
                        {
                            "model_id": model_id,
                            "equipment_class": eq_class,
                            "version": version,
                            "sha256": sha256_hex,
                            "balloons_assigned": assigned,
                            "balloons_kept": kept,
                        }
                    ),
                ),
            )
            conn.commit()

    return {
        "status": "published",
        "balloons_assigned": assigned,
        "balloons_kept": kept,
    }


def get_model_bom(tenant_id: str, model_id: str) -> dict[str, Any]:
    """Retrieve BOM items with balloons, node mapping, and explode vectors (API4.14)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Check model exists
            cur.execute(
                "SELECT id, equipment_class, version FROM field.asset_model WHERE tenant_id = %s AND id = %s;",
                (tenant_id, model_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error_code": "FIELD-MOD-404",
                        "message": f"Asset model '{model_id}' not found",
                    },
                )

            cur.execute(
                """
                SELECT balloon_no, part_no, description, qty, is_serialised,
                       node_names, explode_vector_x, explode_vector_y, explode_vector_z,
                       parent_part_no, node_path
                FROM field.asset_model_bom
                WHERE tenant_id = %s AND model_id = %s
                ORDER BY balloon_no ASC NULLS LAST, part_no ASC;
                """,
                (tenant_id, model_id),
            )
            rows = cur.fetchall()

    items = [
        {
            "balloon_no": r[0],
            "part_no": r[1],
            "description": r[2],
            "qty": r[3],
            "serialised": r[4],
            "node_names": r[5] or [],
            "explode_vector": [float(r[6]), float(r[7]), float(r[8])],
            "parent_part_no": r[9],
            "node_path": r[10],
        }
        for r in rows
    ]

    return {"model_id": model_id, "items": items}


def update_model_bom(
    tenant_id: str,
    model_id: str,
    bom_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Update draft model BOM; blocks updates to published versions (TC4.146)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                "SELECT status, version FROM field.asset_model WHERE tenant_id = %s AND id = %s;",
                (tenant_id, model_id),
            )
            m_row = cur.fetchone()
            if not m_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error_code": "FIELD-MOD-404",
                        "message": f"Asset model '{model_id}' not found",
                    },
                )

            if m_row[0] == "published":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "FIELD-MOD-409-PUBLISHED",
                        "message": f"Published version '{m_row[1]}' is immutable. Create a new semantic version (e.g. 1.3.1) to modify BOM.",
                    },
                )

            # Apply updates for draft
            for up in bom_updates:
                p_no = up.get("part_no")
                desc = up.get("description")
                if p_no and desc:
                    cur.execute(
                        """
                        UPDATE field.asset_model_bom
                        SET description = %s
                        WHERE tenant_id = %s AND model_id = %s AND part_no = %s;
                        """,
                        (desc, tenant_id, model_id, p_no),
                    )
            conn.commit()

    return {"status": "updated", "model_id": model_id}


def pin_equipment_to_model_version(
    tenant_id: str,
    equipment_serial_no: str,
    model_version_id: str,
    cur: Any | None = None,
) -> None:
    """Pin equipment installed record to a specific model version (FR4.054 / TC4.146)."""

    def _execute(c: Any) -> None:
        c.execute(
            """
            UPDATE field.equipment
            SET pinned_model_version_id = %s,
                pinned_model_version = (SELECT version FROM field.asset_model WHERE id = %s)
            WHERE tenant_id = %s AND serial_no = %s;
            """,
            (model_version_id, model_version_id, tenant_id, equipment_serial_no),
        )

    if cur is not None:
        _execute(cur)
    else:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                _execute(cursor)
                conn.commit()
