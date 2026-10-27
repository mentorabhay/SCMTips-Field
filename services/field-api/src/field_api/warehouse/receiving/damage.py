"""Damaged Carton Handling for Receiving (Task T3.021 / FR3.009 / TC3.108).

Implements:
- 'Mark damaged' workflow: requires crop/photo evidence.
- Dual site modes (D3.01):
  1. 'reject': Exclude damaged quantity from goods receipt.
  2. 'blocked': Post damaged quantity to SAP blocked stock (StockType 'S').
"""

import os
from typing import Any

import psycopg
from field_api.errors import FieldError

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

ERR_DAMAGE_PHOTO_REQUIRED = FieldError(
    status=422,
    code="FIELD-RCV-422-PHOTO-REQUIRED",
    title="Damage Photo Required",
    detail="Marking a carton or handling unit as damaged requires crop / photo evidence.",
)


def mark_handling_unit_damaged(
    tenant_id: str,
    hu_id: str,
    evidence_crop_id: str,
    damage_description: str | None = None,
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Flag a handling unit as damaged with mandatory photo evidence."""
    if not evidence_crop_id:
        raise ERR_DAMAGE_PHOTO_REQUIRED

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")
        cur.execute(
            """
            UPDATE field.handling_unit
            SET is_damaged = TRUE,
                damage_evidence_crop_id = %s,
                updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            RETURNING id, sscc, quantity, delivery_ref, is_damaged;
            """,
            (evidence_crop_id, tenant_id, hu_id),
        )
        row = cur.fetchone()
        if not row:
            raise FieldError(
                status=404,
                code="FIELD-RCV-404-HU-NOT-FOUND",
                title="Handling Unit Not Found",
                detail=f"Handling unit {hu_id} was not found.",
            )

    return {
        "hu_id": str(row[0]),
        "sscc": row[1],
        "quantity": float(row[2]),
        "delivery_ref": row[3],
        "is_damaged": row[4],
        "evidence_crop_id": evidence_crop_id,
        "description": damage_description,
    }


def resolve_damaged_carton_posting(
    site_damaged_mode: str,  # 'reject' | 'blocked'
    total_counted_qty: float,
    damaged_qty: float,
) -> dict[str, Any]:
    """Compute postings for unrestricted vs blocked stock based on site mode (D3.01 / TC3.108).

    Modes:
    - 'reject': Exclude damaged quantity entirely from goods receipt (unrestricted = total - damaged).
    - 'blocked': Post damaged quantity to blocked stock (unrestricted = total - damaged, blocked = damaged).
    """
    mode = site_damaged_mode.lower()
    valid_damaged = min(damaged_qty, total_counted_qty)
    unrestricted_qty = max(0.0, total_counted_qty - valid_damaged)

    if mode == "reject":
        return {
            "mode": "reject",
            "unrestricted_qty": unrestricted_qty,
            "blocked_qty": 0.0,
            "rejected_qty": valid_damaged,
        }
    elif mode == "blocked":
        return {
            "mode": "blocked",
            "unrestricted_qty": unrestricted_qty,
            "blocked_qty": valid_damaged,
            "rejected_qty": 0.0,
        }
    else:
        # Default to reject
        return {
            "mode": "reject",
            "unrestricted_qty": unrestricted_qty,
            "blocked_qty": 0.0,
            "rejected_qty": valid_damaged,
        }
