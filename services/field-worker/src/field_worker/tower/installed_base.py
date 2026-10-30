"""Import one tower's functional locations and installed equipment from SAP (T4.004 / T4.005 / FR4.014).

Reads API_FUNCTIONALLOCATION and API_EQUIPMENT through the connectors' readers (erp-sim or S/4 by URL)
and mirrors them into field.location (kind, sector, height, fl_code; erp_ref = the FL) and
field.equipment (erp_equipment_no, serial, material, current location). Equipment that SAP no longer
shows under the tower is marked dismantled. The audit and swap tasks are generated from this mirror.

Runs on the caller's cursor with the tenant set (worker role, RLS applies).
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
from field_sap.equipment_read import EquipmentReader
from field_sap.fl_import import FunctionalLocationReader

KINDS = frozenset({"tower", "sector", "tower_site", "shelter", "rack", "rack_slot", "position", "level"})


def equipment_class(material: str | None) -> str:
    """MAT-RRU-01 -> RRU; anything else UNKNOWN (classes as in field_api.serials)."""
    parts = (material or "").split("-")
    return parts[1] if len(parts) >= 3 and parts[0] == "MAT" else "UNKNOWN"


def mirror_tower(
    cur: psycopg.Cursor[Any], tenant_id: str, site_id: str, tower_fl: str,
    fls: list[dict[str, Any]], equipment: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert the tower tree and its installed equipment; returns counts."""
    ids: dict[str, tuple[str, str, int]] = {}  # fl -> (location id, path, depth)
    for fl in sorted((f for f in fls if f.get("fl_code")), key=lambda f: len(str(f["fl_code"]))):
        code_fl = str(fl["fl_code"])
        parent = fl.get("parent_fl_code")
        parent_row = ids.get(str(parent)) if parent else None
        if code_fl != tower_fl and parent_row is None:
            continue  # outside this tower's tree
        if parent_row is None:
            code, path, depth, parent_id = code_fl, code_fl, 1, None
        else:
            code = code_fl[len(str(parent)) + 1:] if code_fl.startswith(f"{parent}-") else code_fl
            path, depth, parent_id = f"{parent_row[1]}/{code}", parent_row[2] + 1, parent_row[0]
        kind = fl.get("kind") if fl.get("kind") in KINDS else ("tower_site" if parent_row is None else "position")
        cur.execute(
            """
            INSERT INTO field.location (tenant_id, site_id, parent_id, kind, code, path, depth, erp_ref, erp_ref_type,
                   fl_code, sector_code, height_m, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'functional_location', %s, %s, %s, 'active')
            ON CONFLICT (tenant_id, erp_ref) WHERE erp_ref IS NOT NULL DO UPDATE SET
                   parent_id = EXCLUDED.parent_id, kind = EXCLUDED.kind, code = EXCLUDED.code, path = EXCLUDED.path,
                   depth = EXCLUDED.depth, sector_code = EXCLUDED.sector_code, height_m = EXCLUDED.height_m,
                   status = 'active', version = field.location.version + 1, updated_at = NOW()
            RETURNING id
            """,
            (tenant_id, site_id, parent_id, kind, code.upper(), path.upper(), depth, code_fl, code_fl,
             fl.get("sector_code"), fl.get("height_m")),
        )
        row = cur.fetchone()
        if row:
            ids[code_fl] = (str(row[0]), path.upper(), depth)
    seen: set[str] = set()
    for eq in equipment:
        loc = ids.get(str(eq.get("functional_location") or ""))
        serial, material = eq.get("serial_no"), eq.get("material_no")
        if not loc or not serial or not material:
            continue
        seen.add(str(serial))
        cur.execute(
            """
            INSERT INTO field.equipment (tenant_id, erp_equipment_no, serial_no, material, part_no, equipment_class,
                   current_location_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'installed')
            ON CONFLICT (tenant_id, material, serial_no) DO UPDATE SET erp_equipment_no = EXCLUDED.erp_equipment_no,
                   part_no = EXCLUDED.part_no, equipment_class = EXCLUDED.equipment_class,
                   current_location_id = EXCLUDED.current_location_id, status = 'installed', updated_at = NOW()
            """,
            (tenant_id, eq.get("equipment_no"), serial, material, eq.get("mfr_part_no"), equipment_class(material),
             loc[0]),
        )
    loc_ids = [v[0] for v in ids.values()]
    if loc_ids:
        cur.execute(
            "UPDATE field.equipment SET status = 'dismantled', current_location_id = NULL, updated_at = NOW()"
            " WHERE current_location_id = ANY(%s::uuid[]) AND status = 'installed' AND NOT (serial_no = ANY(%s))",
            (loc_ids, sorted(seen)),
        )
    return {"locations": len(ids), "equipment": len(seen)}


def sync_tower_installed_base(
    tenant_id: str, site_id: str, tower_fl: str, erp_url: str, db_url: str, client: httpx.Client | None = None
) -> dict[str, int]:
    """Read the tower from SAP and mirror it (one transaction). ``client``: an HTTP client to reuse."""
    fls = FunctionalLocationReader(base_url=erp_url, client=client).read_functional_locations(prefix=tower_fl)
    equipment, _duplicates = EquipmentReader(base_url=erp_url, client=client).read_equipment(fl_prefix=tower_fl)
    with psycopg.connect(db_url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (tenant_id,))
        out = mirror_tower(cur, tenant_id, site_id, tower_fl, fls, equipment)
        conn.commit()
    return out
