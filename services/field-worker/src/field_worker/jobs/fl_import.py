"""Scheduled Delta Functional Location Import Worker (Task T4.007 / FR4.006 / TC4.103).

Periodically queries SAP for functional location modifications since last watermark,
stages delta imports, and applies upserts with idempotency protection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from field_api.db import get_conn
from field_api.sites.import_service import apply_fl_import_job, stage_fl_import
from field_sap.fl_import import FunctionalLocationReader

logger = structlog.get_logger(__name__)


def get_latest_watermark(tenant_id: str, connection_id: str, filter_prefix: str) -> str | None:
    """Retrieve the latest applied watermark timestamp for this connection."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT watermark_from, applied_at
                FROM field.fl_import_job
                WHERE tenant_id = %s::uuid AND connection_id = %s::uuid
                  AND filter_prefix = %s AND status = 'applied'
                ORDER BY applied_at DESC
                LIMIT 1;
                """,
                (tenant_id, connection_id, filter_prefix),
            )
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0].isoformat())
            elif row and row[1]:
                return str(row[1].isoformat())
            return None


def run_fl_delta_import(
    tenant_id: str,
    connection_id: str,
    filter_prefix: str,
    base_url: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Execute delta import job for given prefix.

    Returns summary dictionary with counts of new, changed, and applied locations.
    """
    watermark = get_latest_watermark(tenant_id, connection_id, filter_prefix)
    reader = FunctionalLocationReader(base_url=base_url, client=client)

    # Fetch changes from SAP
    changes = reader.read_functional_locations(prefix=filter_prefix, watermark_from=watermark)
    if not changes:
        logger.info("fl_delta_import.no_changes", prefix=filter_prefix, watermark=watermark)
        return {
            "status": "unchanged",
            "changes_detected": 0,
            "watermark": watermark,
        }

    # Find the latest change timestamp among fetched rows to advance watermark
    latest_ts = None
    for c in changes:
        ts = c.get("last_change")
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts
    if latest_ts is None:
        latest_ts = watermark or datetime.now(UTC).isoformat()

    # Stage delta job
    stage_res = stage_fl_import(
        tenant_id=tenant_id,
        connection_id=connection_id,
        filter_prefix=filter_prefix,
        fl_rows=changes,
        mode="delta",
        watermark_from=latest_ts,
    )

    counts = stage_res["counts"]
    job_id = stage_res["job_id"]
    total_mods = counts.get("new", 0) + counts.get("changed", 0) + counts.get("moved", 0)

    if total_mods == 0:
        logger.info("fl_delta_import.identical_data", prefix=filter_prefix, job_id=job_id)
        return {
            "status": "unchanged",
            "changes_detected": 0,
            "counts": counts,
            "job_id": job_id,
            "watermark": latest_ts,
        }

    # Apply changes
    apply_res = apply_fl_import_job(tenant_id=tenant_id, job_id=job_id)

    return {
        "status": "applied",
        "job_id": job_id,
        "changes_detected": total_mods,
        "counts": counts,
        "applied_locations_count": apply_res.get("applied_locations_count", 0),
        "watermark": latest_ts,
    }
