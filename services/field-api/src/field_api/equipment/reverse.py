"""Equipment Event Reversal / Compensating Operations (Task T4.024 / FR4.035 / PR4.13 / API4.09).

Implements POST /v1/equipment-events/{id}/reverse creating compensating operation
with ref_doc_no and marking the original erp_document reversed.
Enforces invertibility invariant: f^{-1}(f(S)) = S (PR4.13).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn
from field_api.equipment.history import append_serial_event

logger = structlog.get_logger(__name__)


class EquipmentAlreadyReversedError(Exception):
    """Raised when attempting to reverse an already reversed operation."""

    def __init__(self, doc_no: str):
        super().__init__(
            f"Equipment event / document '{doc_no}' is already reversed [FIELD-EQ-409-ALREADY-REVERSED]"
        )
        self.code = "FIELD-EQ-409-ALREADY-REVERSED"
        self.doc_no = doc_no


def reverse_equipment_event(
    tenant_id: str,
    event_ref: str,  # event_id or doc_number
    reversed_by: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Execute compensating operation to undo a previously posted equipment event (API4.09)."""
    now = datetime.now(UTC)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Look up original erp_document by id, doc_number, or payload event_id
            cur.execute(
                """
                SELECT id, site_id, doc_type, doc_number, status, payload
                FROM field.erp_document
                WHERE tenant_id = %s
                  AND (id::text = %s OR doc_number = %s OR payload->>'event_id' = %s);
                """,
                (tenant_id, event_ref, event_ref, event_ref),
            )
            doc_row = cur.fetchone()
            if not doc_row:
                raise ValueError(
                    f"Equipment event '{event_ref}' not found [FIELD-EQ-404-NOT-FOUND]"
                )

            doc_id, site_id, doc_type, doc_number, doc_status, raw_payload = doc_row
            if doc_status == "reversed":
                raise EquipmentAlreadyReversedError(doc_number)

            payload = (
                raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload or "{}")
            )
            serial_no = str(payload.get("serial_no") or "")
            location_id = payload.get("location_id") or payload.get("previous_location_id")
            old_serial_no = str(payload.get("old_serial_no") or "")

            compensating_doc_no = f"REV-{doc_number}"
            compensating_id = str(uuid.uuid4())

            # 2. Compensating logic based on doc_type / movement_type
            if doc_type == "EQ_INSTALL":
                # Compensate install -> dismantle
                cur.execute(
                    """
                    UPDATE field.equipment
                    SET current_location_id = NULL,
                        status = 'dismantled',
                        updated_at = NOW()
                    WHERE tenant_id = %s AND serial_no = %s;
                    """,
                    (tenant_id, serial_no),
                )
                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="dismantle",
                    location_id=location_id,
                    details={"reversal_of": doc_number, "reason": reason},
                    created_by=reversed_by,
                    cur=cur,
                )

            elif doc_type == "EQ_DISMANTLE":
                # Compensate dismantle -> install
                cur.execute(
                    """
                    UPDATE field.equipment
                    SET current_location_id = %s,
                        status = 'installed',
                        updated_at = NOW()
                    WHERE tenant_id = %s AND serial_no = %s;
                    """,
                    (location_id, tenant_id, serial_no),
                )
                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="install",
                    location_id=location_id,
                    details={"reversal_of": doc_number, "reason": reason},
                    created_by=reversed_by,
                    cur=cur,
                )

            elif doc_type == "EQ_REPLACE":
                # Compensate replace -> swap back
                # Old serial back to location
                if old_serial_no:
                    cur.execute(
                        """
                        UPDATE field.equipment
                        SET current_location_id = %s,
                            status = 'installed',
                            updated_at = NOW()
                        WHERE tenant_id = %s AND serial_no = %s;
                        """,
                        (location_id, tenant_id, old_serial_no),
                    )
                    append_serial_event(
                        tenant_id=tenant_id,
                        serial_no=old_serial_no,
                        event_type="install",
                        location_id=location_id,
                        details={"reversal_of": doc_number, "reinstated": True},
                        created_by=reversed_by,
                        cur=cur,
                    )
                # New serial dismantled
                if serial_no:
                    cur.execute(
                        """
                        UPDATE field.equipment
                        SET current_location_id = NULL,
                            status = 'dismantled',
                            updated_at = NOW()
                        WHERE tenant_id = %s AND serial_no = %s;
                        """,
                        (tenant_id, serial_no),
                    )
                    append_serial_event(
                        tenant_id=tenant_id,
                        serial_no=serial_no,
                        event_type="dismantle",
                        location_id=location_id,
                        details={"reversal_of": doc_number, "undone": True},
                        created_by=reversed_by,
                        cur=cur,
                    )

            # 3. Mark original document as reversed
            cur.execute(
                """
                UPDATE field.erp_document
                SET status = 'reversed',
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (doc_id,),
            )

            # 4. Insert compensating erp_document
            comp_payload = {
                "reversal_of": doc_number,
                "ref_doc_no": doc_number,
                "serial_no": serial_no,
                "reason": reason,
                "reversed_by": reversed_by,
            }
            cur.execute(
                """
                INSERT INTO field.erp_document (
                    id, tenant_id, site_id, doc_type, doc_number, fiscal_year,
                    movement_type, reversal_of_id, payload, status
                ) VALUES (
                    %s, %s, %s, %s, %s, '2026',
                    'REVERSAL', %s, %s, 'posted'
                );
                """,
                (
                    compensating_id,
                    tenant_id,
                    site_id,
                    f"REV_{doc_type}",
                    compensating_doc_no,
                    doc_id,
                    json.dumps(comp_payload),
                ),
            )

            # 5. Emit outbox equipment.reversed event
            event_payload = {
                "compensating_doc_no": compensating_doc_no,
                "original_doc_number": doc_number,
                "serial_no": serial_no,
                "reversed_by": reversed_by,
                "reversed_at": now.isoformat(),
            }
            cur.execute(
                """
                INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, 'equipment.reversed', %s);
                """,
                (str(uuid.uuid4()), tenant_id, compensating_id, json.dumps(event_payload)),
            )

        conn.commit()

    return {
        "status": "reversed",
        "original_doc_number": doc_number,
        "compensating_doc_no": compensating_doc_no,
        "ref_doc_no": doc_number,
        "serial_no": serial_no,
        "reversed_at": now.isoformat(),
    }
