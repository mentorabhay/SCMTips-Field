"""Mismatch Queue API Implementation (Task T4.017 / FR4.064 / API4.16).

Provides GET /v1/mismatches with filters for site_id, class, age, and verify_status,
with cursor pagination, crop URLs, OCR text, and ERP record linkage.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


def list_mismatches(
    tenant_id: str,
    site_id: str | None = None,
    finding_class: str | None = None,
    verify_status: str | None = None,
    min_age_h: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List mismatch queue findings with filtering and cursor pagination (API4.16)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            query = """
                SELECT
                    af.id,
                    af.site_id,
                    af.class,
                    af.expected_serial,
                    af.found_serial,
                    af.status,
                    af.reason,
                    af.created_at,
                    COALESCE(c.verify_status, 'verified') AS verify_status,
                    ce.crop_s3_uri AS crop_ref,
                    c.raw_text,
                    c.confidence,
                    e.material,
                    e.equipment_class,
                    s.code AS site_code
                FROM field.audit_finding af
                JOIN field.site s ON af.site_id = s.id
                LEFT JOIN field.capture c ON af.capture_id = c.id
                LEFT JOIN field.capture_evidence ce ON ce.capture_id = c.id
                LEFT JOIN field.equipment e ON (e.serial_no = af.expected_serial OR e.serial_no = af.found_serial) AND e.tenant_id = af.tenant_id
                WHERE af.tenant_id = %s
                  AND af.class IN ('serial_mismatch', 'tower_only', 'erp_only', 'misplaced')
                  AND af.status <> 'resolved'
            """
            params: list[Any] = [tenant_id]

            if site_id:
                query += " AND af.site_id = %s"
                params.append(site_id)

            if finding_class:
                query += " AND af.class = %s"
                params.append(finding_class)

            if verify_status:
                query += " AND COALESCE(c.verify_status, 'verified') = %s"
                params.append(verify_status)

            if min_age_h is not None and min_age_h > 0:
                cutoff = datetime.now(UTC) - timedelta(hours=min_age_h)
                query += " AND af.created_at <= %s"
                params.append(cutoff)

            if cursor:
                try:
                    cursor_created_at = datetime.fromisoformat(base64.b64decode(cursor).decode("utf-8"))
                    query += " AND af.created_at < %s"
                    params.append(cursor_created_at)
                except Exception:
                    pass

            query += " ORDER BY af.created_at DESC LIMIT %s"
            params.append(limit + 1)

            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            now = datetime.now(UTC)
            items = []
            has_more = len(rows) > limit
            fetch_rows = rows[:limit]

            for r in fetch_rows:
                f_id = str(r[0])
                s_id = str(r[1])
                f_class = r[2]
                exp_s = r[3]
                found_s = r[4]
                f_status = r[5]
                reason = r[6]
                created_at = r[7]
                v_status = r[8]
                crop_ref = r[9]
                raw_text = r[10]
                conf = float(r[11]) if r[11] is not None else None
                mat = r[12]
                eq_class = r[13]
                s_code = r[14]

                age_hours = max(0, int((now - created_at).total_seconds() / 3600))
                crop_url = f"https://scmtips-evidence.s3.amazonaws.com/{crop_ref}" if crop_ref else None

                items.append({
                    "id": f_id,
                    "site_id": s_id,
                    "site_code": s_code,
                    "class": f_class,
                    "expected_serial": exp_s,
                    "found_serial": found_s,
                    "status": f_status,
                    "reason": reason,
                    "verify_status": v_status,
                    "crop_url": crop_url,
                    "raw_ocr_text": raw_text,
                    "confidence": conf,
                    "material": mat,
                    "equipment_class": eq_class,
                    "age_h": age_hours,
                    "created_at": created_at.isoformat(),
                })

            next_cursor = None
            if has_more and fetch_rows:
                last_created = fetch_rows[-1][7].isoformat()
                next_cursor = base64.b64encode(last_created.encode("utf-8")).decode("utf-8")

    return {
        "items": items,
        "next_cursor": next_cursor,
        "count": len(items),
    }
