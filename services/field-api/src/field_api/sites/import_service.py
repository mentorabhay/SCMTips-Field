"""SAP Functional Location Import Service (Task T4.006 / FR4.004 / FR4.006 / PR4.16 / TC4.101).

Implements staging, diff computation (new, changed, moved, removed, rejected),
preview generation, and atomic apply in one transaction per site.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional
import structlog

from field_api.db import get_conn
from field_api.sites.import_validate import validate_import_staging_rows

logger = structlog.get_logger(__name__)


def stage_fl_import(
    tenant_id: str,
    filter_prefix: str,
    fl_rows: list[dict[str, Any]],
    equipment_rows: Optional[list[dict[str, Any]]] = None,
    connection_id: Optional[str] = None,
    mode: str = "full",
    watermark_from: Optional[str] = None,
    allow_step_up: bool = False,
) -> dict[str, Any]:
    """Validate incoming SAP FL/Equipment rows, compute diff preview, and store staging job."""
    conn_id = connection_id or str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET app.tenant_id = '{tenant_id}';")
            cur.execute("SET app.site_ids = '*';")
            cur.execute(f"SET app.tenant_id = '{tenant_id}';")
            cur.execute("SET app.site_ids = '*';")
            # Query existing locations under this prefix for this tenant
            cur.execute(
                """
                SELECT id, code, erp_ref, parent_id, height_m, sector_code
                FROM field.location
                WHERE tenant_id = %s::uuid AND erp_ref LIKE %s;
                """,
                (tenant_id, f"{filter_prefix}%"),
            )
            existing_locs = {r[2]: {"id": str(r[0]), "code": r[1], "parent_id": str(r[3]) if r[3] else None, "height_m": float(r[4]) if r[4] is not None else None, "sector_code": r[5]} for r in cur.fetchall()}

            known_parents = set(existing_locs.keys())
            val_summary = validate_import_staging_rows(fl_rows, known_parent_codes=known_parents, allow_step_up=allow_step_up)

            # Compute diff
            new_rows = []
            changed_rows = []
            moved_rows = []
            valid_fl_codes = set()

            for r in val_summary.valid_rows:
                code = r["fl_code"]
                valid_fl_codes.add(code)
                parent = r.get("parent_fl_code")

                if code not in existing_locs:
                    new_rows.append(code)
                else:
                    curr = existing_locs[code]
                    is_changed = False
                    is_moved = False

                    # Check parent move
                    curr_parent_erp = None
                    if curr["parent_id"]:
                        # find parent erp
                        for erp, d in existing_locs.items():
                            if d["id"] == curr["parent_id"]:
                                curr_parent_erp = erp
                                break
                    if parent != curr_parent_erp:
                        moved_rows.append({"fl_code": code, "from": curr_parent_erp, "to": parent})
                        is_moved = True

                    # Check attributes change
                    if r.get("height_m") != curr.get("height_m") or r.get("sector_code") != curr.get("sector_code"):
                        if not is_moved:
                            changed_rows.append(code)

            removed_rows = []
            if mode == "full":
                for code in existing_locs:
                    if code not in valid_fl_codes:
                        removed_rows.append(code)

            counts = {
                "new": len(new_rows),
                "changed": len(changed_rows),
                "moved": len(moved_rows),
                "removed": len(removed_rows),
                "rejected": val_summary.rejected_count,
            }

            diff_preview = {
                "new_locations": new_rows,
                "changed_locations": changed_rows,
                "moved_locations": moved_rows,
                "removed_locations": removed_rows,
                "rejected_details": val_summary.rejected_rows,
            }

            cur.execute(
                """
                INSERT INTO field.fl_import_job (
                    id, tenant_id, connection_id, filter_prefix, mode,
                    watermark_from, status, counts, rejected_rows,
                    staging_data, diff_preview
                ) VALUES (
                    %s::uuid, %s::uuid, %s::uuid, %s, %s,
                    %s, 'preview', %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb
                ) RETURNING id, status, counts, created_at;
                """,
                (
                    job_id,
                    tenant_id,
                    conn_id,
                    filter_prefix,
                    mode,
                    watermark_from,
                    json.dumps(counts),
                    json.dumps(val_summary.rejected_rows),
                    json.dumps({"locations": val_summary.valid_rows, "equipment": equipment_rows or []}),
                    json.dumps(diff_preview),
                ),
            )
            res = cur.fetchone()
            conn.commit()

            return {
                "job_id": str(res[0]),
                "status": res[1],
                "counts": counts,
                "diff_preview": diff_preview,
                "blocked": val_summary.blocked,
                "rejection_pct": val_summary.rejection_pct,
            }


def apply_fl_import_job(
    tenant_id: str,
    job_id: str,
    allow_step_up: bool = False,
) -> dict[str, Any]:
    """Apply staged import job, upserting locations and equipment in one transaction per site."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET app.tenant_id = '{tenant_id}';")
            cur.execute("SET app.site_ids = '*';")
            cur.execute(
                """
                SELECT id, status, counts, staging_data
                FROM field.fl_import_job
                WHERE id = %s::uuid AND tenant_id = %s::uuid;
                """,
                (job_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Import job {job_id} not found")

            status = row[1]
            counts = row[2] if isinstance(row[2], dict) else json.loads(row[2])
            staging = row[3] if isinstance(row[3], dict) else json.loads(row[3])

            if status == "applied":
                return {"job_id": job_id, "status": "applied", "message": "Job already applied"}

            total = counts.get("new", 0) + counts.get("changed", 0) + counts.get("moved", 0) + counts.get("rejected", 0)
            if total > 0:
                rejection_pct = (counts.get("rejected", 0) / total) * 100.0
                if rejection_pct > 20.0 and not allow_step_up:
                    raise ValueError(f"FIELD-IMP-422-BLOCKED: Rejection percentage {rejection_pct:.1f}% exceeds 20%")

            locations = staging.get("locations", [])
            # Sort locations by depth so parents are inserted before children
            locations.sort(key=lambda x: x.get("depth", 1))

            # Group locations by site_code
            site_locations: dict[str, list[dict[str, Any]]] = {}
            for loc in locations:
                s_code = loc.get("site_code") or loc["fl_code"].split("-")[0]
                site_locations.setdefault(s_code, []).append(loc)

            applied_loc_count = 0
            for site_code, loc_list in site_locations.items():
                # Find or create field.site
                cur.execute(
                    """
                    SELECT id FROM field.site
                    WHERE tenant_id = %s::uuid AND code = %s;
                    """,
                    (tenant_id, site_code),
                )
                site_row = cur.fetchone()
                if site_row:
                    site_id = site_row[0]
                else:
                    site_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO field.site (id, tenant_id, code, name, kind, status)
                        VALUES (%s::uuid, %s::uuid, %s, %s, 'tower', 'active');
                        """,
                        (site_id, tenant_id, site_code, f"Tower Site {site_code}"),
                    )

                # Upsert locations
                code_to_id: dict[str, str] = {}
                for loc in loc_list:
                    fl = loc["fl_code"]
                    parent_fl = loc.get("parent_fl_code")
                    parent_id = code_to_id.get(parent_fl) if parent_fl else None

                    # If parent was in DB previously
                    if not parent_id and parent_fl:
                        cur.execute(
                            "SELECT id FROM field.location WHERE tenant_id = %s::uuid AND erp_ref = %s;",
                            (tenant_id, parent_fl),
                        )
                        p_row = cur.fetchone()
                        if p_row:
                            parent_id = str(p_row[0])

                    cur.execute(
                        """
                        INSERT INTO field.location (
                            id, tenant_id, site_id, parent_id, kind, code,
                            path, depth, erp_ref, height_m, sector_code, fl_code, status
                        ) VALUES (
                            field.uuid_generate_v7(), %s::uuid, %s::uuid, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, 'active'
                        )
                        ON CONFLICT (tenant_id, erp_ref) WHERE erp_ref IS NOT NULL
                        DO UPDATE SET
                            height_m = EXCLUDED.height_m,
                            sector_code = EXCLUDED.sector_code,
                            parent_id = EXCLUDED.parent_id,
                            updated_at = NOW()
                        RETURNING id;
                        """,
                        (
                            tenant_id,
                            site_id,
                            parent_id,
                            loc.get("kind", "position"),
                            loc.get("short_code", fl[-3:]),
                            fl,
                            loc.get("depth", 1),
                            fl,
                            loc.get("height_m"),
                            loc.get("sector_code"),
                            fl,
                        ),
                    )
                    inserted_id = str(cur.fetchone()[0])
                    code_to_id[fl] = inserted_id
                    applied_loc_count += 1

            # Mark job applied
            cur.execute(
                """
                UPDATE field.fl_import_job
                SET status = 'applied', applied_at = NOW(), updated_at = NOW()
                WHERE id = %s::uuid;
                """,
                (job_id,),
            )
            conn.commit()

            return {
                "job_id": job_id,
                "status": "applied",
                "applied_locations_count": applied_loc_count,
            }
