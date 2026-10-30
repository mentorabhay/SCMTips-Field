"""Equipment Events Business Logic (Task T4.023 / FR4.029 / FR4.030 / FR4.031 / FR4.033 / PR4.14 / PR4.15).

Supports install, dismantle, replace (staged swap), and move operations with
single-location invariant checks, append-only serial event recording, and idempotency.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn
from field_api.equipment.history import (
    SingleLocationViolationError,
    append_serial_event,
    check_single_location_invariant,
)

logger = structlog.get_logger(__name__)


def record_equipment_event(
    tenant_id: str,
    event_type: str,  # 'install', 'dismantle', 'replace', 'move', 'issue'
    serial_no: str,
    site_id: str,
    location_id: str | None = None,
    material: str | None = None,
    old_serial_no: str | None = None,
    task_id: str | None = None,
    created_by: str | None = None,
    evidence_crop_ref: str | None = None,
    notes: str | None = None,
    idempotency_key: str | None = None,
    source_plant: str | None = None,
    source_storage_location: str | None = None,
    occurred_at: datetime | None = None,
    model_version_id: str | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    """Execute equipment lifecycle event with single-location invariant and staging flow."""
    now = datetime.now(UTC)
    event_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # 1. Fetch location fl_code if location_id given
            fl_code = None
            if location_id:
                cur.execute(
                    "SELECT fl_code FROM field.location WHERE tenant_id = %s AND id = %s;",
                    (tenant_id, location_id),
                )
                fl_row = cur.fetchone()
                if fl_row:
                    fl_code = fl_row[0]

            # 2. Process based on event_type
            if event_type == "install":
                if not location_id:
                    raise ValueError("location_id is required for install operation")

                # Single-location invariant check (PR4.14 / FR4.034)
                allowed, curr_loc, curr_fl = check_single_location_invariant(
                    tenant_id, serial_no, location_id, cur=cur
                )
                if not allowed:
                    raise SingleLocationViolationError(serial_no, curr_loc or "", curr_fl)

                # Upsert equipment master
                mat_name = material or "GENERIC-EQUIPMENT"
                cur.execute(
                    """
                    INSERT INTO field.equipment (
                        tenant_id, serial_no, material, current_location_id, status,
                        pinned_model_version_id, pinned_model_version, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, 'installed',
                        %s, %s, NOW()
                    )
                    ON CONFLICT (tenant_id, material, serial_no)
                    DO UPDATE SET
                        current_location_id = EXCLUDED.current_location_id,
                        status = 'installed',
                        pinned_model_version_id = COALESCE(EXCLUDED.pinned_model_version_id, field.equipment.pinned_model_version_id),
                        pinned_model_version = COALESCE(EXCLUDED.pinned_model_version, field.equipment.pinned_model_version),
                        updated_at = NOW()
                    RETURNING id;
                    """,
                    (tenant_id, serial_no, mat_name, location_id, model_version_id, model_version),
                )
                eq_row = cur.fetchone()
                eq_id = str(eq_row[0]) if eq_row else str(uuid.uuid4())

                # Append install serial_event
                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="install",
                    location_id=location_id,
                    equipment_id=eq_id,
                    details={
                        "material": mat_name,
                        "fl_code": fl_code,
                        "notes": notes,
                        "crop_ref": evidence_crop_ref,
                    },
                    created_by=created_by,
                    source_plant=source_plant,
                    source_storage_location=source_storage_location,
                    occurred_at=occurred_at,
                    cur=cur,
                )

                # Record ERP document entry
                doc_no = f"DOC-INS-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """
                    INSERT INTO field.erp_document (
                        tenant_id, site_id, doc_type, doc_number, fiscal_year,
                        movement_type, payload, status
                    ) VALUES (
                        %s, %s, 'EQ_INSTALL', %s, '2026',
                        'INSTALL', %s, 'posted'
                    );
                    """,
                    (
                        tenant_id,
                        site_id,
                        doc_no,
                        json.dumps(
                            {
                                "event_id": event_id,
                                "serial_no": serial_no,
                                "location_id": location_id,
                                "fl_code": fl_code,
                                "idempotency_key": idempotency_key,
                            }
                        ),
                    ),
                )

                return {
                    "event_id": event_id,
                    "event_type": "install",
                    "serial_no": serial_no,
                    "location_id": location_id,
                    "fl_code": fl_code,
                    "status": "completed",
                    "doc_number": doc_no,
                    "timestamp": now.isoformat(),
                }

            elif event_type == "dismantle":
                # Ensure equipment is currently installed
                cur.execute(
                    """
                    SELECT id, current_location_id, status
                    FROM field.equipment
                    WHERE tenant_id = %s AND serial_no = %s;
                    """,
                    (tenant_id, serial_no),
                )
                eq_row = cur.fetchone()
                if not eq_row or eq_row[2] != "installed":
                    raise ValueError(
                        f"Equipment '{serial_no}' is not currently installed [FIELD-EQ-400-NOT-INSTALLED]"
                    )

                eq_id = str(eq_row[0])
                old_loc_id = eq_row[1]

                # Update equipment status to dismantled
                cur.execute(
                    """
                    UPDATE field.equipment
                    SET current_location_id = NULL,
                        status = 'dismantled',
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (eq_id,),
                )

                # Append dismantle serial_event
                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="dismantle",
                    location_id=old_loc_id,
                    equipment_id=eq_id,
                    details={"notes": notes, "fl_code": fl_code},
                    created_by=created_by,
                    cur=cur,
                )

                doc_no = f"DOC-DIS-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """
                    INSERT INTO field.erp_document (
                        tenant_id, site_id, doc_type, doc_number, fiscal_year,
                        movement_type, payload, status
                    ) VALUES (
                        %s, %s, 'EQ_DISMANTLE', %s, '2026',
                        'DISMANTLE', %s, 'posted'
                    );
                    """,
                    (
                        tenant_id,
                        site_id,
                        doc_no,
                        json.dumps(
                            {
                                "event_id": event_id,
                                "serial_no": serial_no,
                                "previous_location_id": str(old_loc_id) if old_loc_id else None,
                                "idempotency_key": idempotency_key,
                            }
                        ),
                    ),
                )

                return {
                    "event_id": event_id,
                    "event_type": "dismantle",
                    "serial_no": serial_no,
                    "previous_location_id": str(old_loc_id) if old_loc_id else None,
                    "status": "completed",
                    "doc_number": doc_no,
                    "timestamp": now.isoformat(),
                }

            elif event_type == "replace":
                # Staged replacement: dismantle old serial, install new serial (FR4.031 / TC4.128)
                if not old_serial_no:
                    raise ValueError("old_serial_no is required for replace operation")
                if not location_id:
                    raise ValueError("location_id is required for replace operation")

                # Single-location check on new serial
                allowed, curr_loc, curr_fl = check_single_location_invariant(
                    tenant_id, serial_no, location_id, cur=cur
                )
                if not allowed:
                    raise SingleLocationViolationError(serial_no, curr_loc or "", curr_fl)

                # Step A: Dismantle old serial
                cur.execute(
                    """
                    UPDATE field.equipment
                    SET current_location_id = NULL,
                        status = 'dismantled',
                        updated_at = NOW()
                    WHERE tenant_id = %s AND serial_no = %s
                    RETURNING id;
                    """,
                    (tenant_id, old_serial_no),
                )
                old_row = cur.fetchone()
                old_eq_id = str(old_row[0]) if old_row else None

                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=old_serial_no,
                    event_type="dismantle",
                    location_id=location_id,
                    equipment_id=old_eq_id,
                    details={"replaced_by": serial_no, "fl_code": fl_code},
                    created_by=created_by,
                    cur=cur,
                )

                # Step B: Install new serial
                mat_name = material or "GENERIC-EQUIPMENT"
                cur.execute(
                    """
                    INSERT INTO field.equipment (
                        tenant_id, serial_no, material, current_location_id, status, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, 'installed', NOW()
                    )
                    ON CONFLICT (tenant_id, material, serial_no)
                    DO UPDATE SET
                        current_location_id = EXCLUDED.current_location_id,
                        status = 'installed',
                        updated_at = NOW()
                    RETURNING id;
                    """,
                    (tenant_id, serial_no, mat_name, location_id),
                )
                new_eq_row = cur.fetchone()
                new_eq_id = str(new_eq_row[0]) if new_eq_row else str(uuid.uuid4())

                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="install",
                    location_id=location_id,
                    equipment_id=new_eq_id,
                    details={
                        "replaces": old_serial_no,
                        "fl_code": fl_code,
                        "crop_ref": evidence_crop_ref,
                    },
                    created_by=created_by,
                    cur=cur,
                )

                doc_no = f"DOC-REP-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """
                    INSERT INTO field.erp_document (
                        tenant_id, site_id, doc_type, doc_number, fiscal_year,
                        movement_type, payload, status
                    ) VALUES (
                        %s, %s, 'EQ_REPLACE', %s, '2026',
                        'REPLACE', %s, 'posted'
                    );
                    """,
                    (
                        tenant_id,
                        site_id,
                        doc_no,
                        json.dumps(
                            {
                                "event_id": event_id,
                                "serial_no": serial_no,
                                "old_serial_no": old_serial_no,
                                "location_id": location_id,
                                "fl_code": fl_code,
                                "idempotency_key": idempotency_key,
                            }
                        ),
                    ),
                )

                return {
                    "event_id": event_id,
                    "event_type": "replace",
                    "serial_no": serial_no,
                    "old_serial_no": old_serial_no,
                    "location_id": location_id,
                    "fl_code": fl_code,
                    "status": "completed",
                    "doc_number": doc_no,
                    "timestamp": now.isoformat(),
                }

            elif event_type == "move":
                if not location_id:
                    raise ValueError("target location_id is required for move operation")

                # Move equipment to new location
                cur.execute(
                    """
                    UPDATE field.equipment
                    SET current_location_id = %s,
                        status = 'installed',
                        updated_at = NOW()
                    WHERE tenant_id = %s AND serial_no = %s
                    RETURNING id;
                    """,
                    (location_id, tenant_id, serial_no),
                )
                eq_row = cur.fetchone()
                if not eq_row:
                    raise ValueError(f"Equipment '{serial_no}' not found for move")

                eq_id = str(eq_row[0])
                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="move",
                    location_id=location_id,
                    equipment_id=eq_id,
                    details={"fl_code": fl_code, "notes": notes},
                    created_by=created_by,
                    cur=cur,
                )

                doc_no = f"DOC-MOV-{uuid.uuid4().hex[:8].upper()}"
                return {
                    "event_id": event_id,
                    "event_type": "move",
                    "serial_no": serial_no,
                    "location_id": location_id,
                    "fl_code": fl_code,
                    "status": "completed",
                    "doc_number": doc_no,
                    "timestamp": now.isoformat(),
                }

            elif event_type == "issue":
                # Issue equipment from store/warehouse (T4.029 / TC4.132 / FR4.037)
                mat_name = material or "GENERIC-EQUIPMENT"
                cur.execute(
                    """
                    INSERT INTO field.equipment (
                        tenant_id, serial_no, material, current_location_id, status, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, 'issued', NOW()
                    )
                    ON CONFLICT (tenant_id, material, serial_no)
                    DO UPDATE SET
                        status = 'issued',
                        updated_at = NOW()
                    RETURNING id;
                    """,
                    (tenant_id, serial_no, mat_name, location_id),
                )
                eq_row = cur.fetchone()
                eq_id = str(eq_row[0]) if eq_row else str(uuid.uuid4())

                append_serial_event(
                    tenant_id=tenant_id,
                    serial_no=serial_no,
                    event_type="issue",
                    location_id=location_id,
                    equipment_id=eq_id,
                    details={
                        "material": mat_name,
                        "notes": notes,
                        "source_plant": source_plant,
                        "source_sloc": source_storage_location,
                    },
                    created_by=created_by,
                    source_plant=source_plant,
                    source_storage_location=source_storage_location,
                    occurred_at=occurred_at,
                    cur=cur,
                )

                doc_no = f"DOC-ISS-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """
                    INSERT INTO field.erp_document (
                        tenant_id, site_id, doc_type, doc_number, fiscal_year,
                        movement_type, payload, status
                    ) VALUES (
                        %s, %s, 'EQ_ISSUE', %s, '2026',
                        'ISSUE', %s, 'posted'
                    );
                    """,
                    (
                        tenant_id,
                        site_id,
                        doc_no,
                        json.dumps(
                            {
                                "event_id": event_id,
                                "serial_no": serial_no,
                                "source_plant": source_plant,
                                "source_storage_location": source_storage_location,
                                "idempotency_key": idempotency_key,
                            }
                        ),
                    ),
                )

                return {
                    "event_id": event_id,
                    "event_type": "issue",
                    "serial_no": serial_no,
                    "source_plant": source_plant,
                    "source_storage_location": source_storage_location,
                    "status": "completed",
                    "doc_number": doc_no,
                    "timestamp": now.isoformat(),
                }

            else:
                raise ValueError(f"Unsupported event_type: {event_type}")
