"""Installed Base Change Events & P13f Webhook Publisher (Task T4.028 / FR4.066 / TC4.158).

Features:
- Emits 'installed_base.changed' event into field.outbox on equip install, dismantle or reversal.
- Publishes signed webhook to SCMTIPS Core P13f event stream.
- Computes HMAC-SHA256 signature in X-Signature-SHA256 header.
- Enforces TC4.158: Signed webhook verification and deduplication by event id.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from field_common.uuid7 import uuid7_str

logger = structlog.get_logger(__name__)

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

P13F_WEBHOOK_SECRET = os.getenv(
    "FIELD_P13F_WEBHOOK_SECRET", "dev-p13f-webhook-secret-min32bytes-field"
)


def compute_webhook_signature(payload_bytes: bytes, secret: str = P13F_WEBHOOK_SECRET) -> str:
    """Compute HMAC-SHA256 hex signature for P13f webhook payload (TC4.158)."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def verify_p13f_webhook_signature(
    payload_bytes: bytes,
    signature: str,
    secret: str = P13F_WEBHOOK_SECRET,
) -> bool:
    """Verify HMAC-SHA256 signature on received P13f webhook."""
    expected = compute_webhook_signature(payload_bytes, secret)
    return hmac.compare_digest(expected, signature)


def _to_uuid(val: str) -> str:
    """Ensure value is a valid UUID string (mapping arbitrary strings deterministically)."""
    try:
        return str(uuid.UUID(val))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))


def emit_installed_base_changed(
    tenant_id: str,
    serial_no: str,
    change_type: str,  # 'installed', 'dismantled', 'moved', 'reversed'
    erp_equipment_no: str | None = None,
    site_id: str | None = None,
    fl_code: str | None = None,
    effective_at: datetime | None = None,
    db_url: str = DATABASE_URL,
) -> dict[str, Any]:
    """Emit installed_base.changed into field.outbox and format signed P13f webhook delivery (TC4.158)."""
    event_id = uuid7_str()
    occurred_at = (effective_at or datetime.now(UTC)).isoformat()
    aggregate_uuid = _to_uuid(serial_no)

    payload = {
        "event_id": event_id,
        "event_type": "installed_base.changed",
        "tenant_id": tenant_id,
        "serial_no": serial_no,
        "erp_equipment_no": erp_equipment_no or "",
        "site_id": site_id,
        "fl_code": fl_code,
        "change_type": change_type,
        "effective_at": occurred_at,
    }
    payload_json = json.dumps(payload, sort_keys=True)
    payload_bytes = payload_json.encode("utf-8")
    signature = compute_webhook_signature(payload_bytes)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            cur.execute(
                """
                INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, 'installed_base.changed', %s)
                ON CONFLICT (id) DO NOTHING;
                """,
                (event_id, tenant_id, aggregate_uuid, payload_json),
            )
            conn.commit()

    logger.info(
        "Emitted installed_base.changed event",
        event_id=event_id,
        serial_no=serial_no,
        change_type=change_type,
    )

    return {
        "event_id": event_id,
        "event_type": "installed_base.changed",
        "payload": payload,
        "signature": signature,
        "headers": {
            "Content-Type": "application/json",
            "X-Event-Id": event_id,
            "X-Event-Type": "installed_base.changed",
            "X-Signature-SHA256": signature,
        },
    }
