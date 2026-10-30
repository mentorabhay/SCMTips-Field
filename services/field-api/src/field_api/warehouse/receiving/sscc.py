"""SSCC Validation and Handling Unit Attachment for Receiving (Task T3.018 / FR3.004 / PR3.12).

Validates:
1. 18-digit numeric structure.
2. GS1 Mod-10 check digit calculation.
3. Delivery duplicate prevention (unique per tenant_id, delivery_ref, sscc).
   Duplicate returns 409 FIELD-RCV-409-SSCC-DUPLICATE with MSG3.03.
4. Attaches handling_unit to task_line.
"""

import os
from typing import Any

import psycopg
from field_api.errors import FieldError
from field_common.uuid7 import uuid7_str

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

ERR_SSCC_INVALID_FORMAT = FieldError(
    status=400,
    code="FIELD-RCV-400-SSCC-FORMAT",
    title="Invalid SSCC Format",
    detail="SSCC must be exactly 18 numeric digits with a valid GS1 check digit.",
)

ERR_SSCC_DUPLICATE = FieldError(
    status=409,
    code="FIELD-RCV-409-SSCC-DUPLICATE",
    title="Duplicate SSCC",
    detail="SSCC has already been captured on this delivery.",  # MSG3.03
)


def compute_gs1_mod10_check_digit(digits17: str) -> int:
    """Calculate GS1 standard mod-10 check digit for the first 17 digits.

    Standard GS1 weighting from right to left (positions 17 down to 1):
    Position 17 has weight 3, pos 16 weight 1, pos 15 weight 3, etc.
    """
    total = 0
    # From rightmost (index 16) to leftmost (index 0)
    for i, char in enumerate(reversed(digits17)):
        weight = 3 if i % 2 == 0 else 1
        total += int(char) * weight
    remainder = total % 10
    return (10 - remainder) % 10


def validate_sscc_checksum(sscc: str) -> bool:
    """Verify that an 18-digit string passes the GS1 mod-10 check digit."""
    if not sscc or len(sscc) != 18 or not sscc.isdigit():
        return False
    expected_check = compute_gs1_mod10_check_digit(sscc[:17])
    return int(sscc[17]) == expected_check


def validate_and_record_sscc(
    tenant_id: str,
    delivery_ref: str,
    sscc: str,
    task_line_id: str | None = None,
    material_id: str | None = None,
    quantity: float = 1.0,
    uom: str = "EA",
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Validate SSCC and create handling unit attached to task_line.

    Raises:
        FieldError(400) if format or check digit is invalid.
        FieldError(409) if duplicate SSCC within the same delivery.
    """
    cleaned_sscc = sscc.strip()
    if not validate_sscc_checksum(cleaned_sscc):
        raise ERR_SSCC_INVALID_FORMAT

    hu_id = uuid7_str()

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

        # Check for duplicate within this delivery (PR3.12 / MSG3.03)
        cur.execute(
            """
            SELECT id FROM field.handling_unit
            WHERE tenant_id = %s AND delivery_ref = %s AND sscc = %s;
            """,
            (tenant_id, delivery_ref, cleaned_sscc),
        )
        if cur.fetchone():
            raise ERR_SSCC_DUPLICATE

        try:
            cur.execute(
                """
                INSERT INTO field.handling_unit (
                    id, tenant_id, sscc, delivery_ref, task_line_id,
                    material_id, quantity, uom, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', NOW(), NOW());
                """,
                (
                    hu_id,
                    tenant_id,
                    cleaned_sscc,
                    delivery_ref,
                    task_line_id,
                    material_id,
                    quantity,
                    uom,
                ),
            )
        except psycopg.errors.UniqueViolation:
            raise ERR_SSCC_DUPLICATE from None

        # If attached to task_line, update task_line sscc / captured_qty
        if task_line_id:
            cur.execute(
                """
                UPDATE field.task_line
                SET sscc = %s, updated_at = NOW()
                WHERE tenant_id = %s AND id = %s;
                """,
                (cleaned_sscc, tenant_id, task_line_id),
            )

    return {
        "hu_id": hu_id,
        "sscc": cleaned_sscc,
        "delivery_ref": delivery_ref,
        "task_line_id": task_line_id,
        "quantity": quantity,
        "uom": uom,
        "status": "active",
    }
