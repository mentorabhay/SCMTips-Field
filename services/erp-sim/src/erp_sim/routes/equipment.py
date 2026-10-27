"""API_EQUIPMENT Implementation (Task T1.049).

Create equipment (10000000-19999999) with serial and material,
install at functional location with date-time, dismantle;
install history kept in equipment_install; installing installed equipment fails ZSIM/EQ-INSTALLED.
"""

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from erp_sim.db import get_conn
from erp_sim.numbering import allocate_number

router = APIRouter(prefix="/sap/opu/odata/sap/API_EQUIPMENT", tags=["Equipment"])

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "towers.json"


def load_equipment_fixtures() -> list[dict[str, Any]]:
    if not FIXTURE_PATH.exists():
        alt_path = Path("services/erp-sim/src/erp_sim/fixtures/towers.json")
        if alt_path.exists():
            with open(alt_path, encoding="utf-8") as f:
                return json.load(f).get("equipment", [])
        return []
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f).get("equipment", [])


@router.get("/Equipment")
@router.get("/A_Equipment")
async def list_equipment(
    filter_expr: Optional[str] = Query(None, alias="$filter"),
    top: Optional[int] = Query(1000, alias="$top"),
    skip: Optional[int] = Query(0, alias="$skip"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """OData v2 endpoint to list installed equipment with details."""
    fixtures = load_equipment_fixtures()

    # Also include any dynamically created equipment in DB
    results = list(fixtures)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT equipment_no, material_no, serial_no, func_loc, created_at FROM erpsim.equipment WHERE client = %s;",
                    (sap_client,),
                )
                db_rows = cur.fetchall()
                existing_nos = {r["Equipment"] for r in results}
                for r in db_rows:
                    if r[0] not in existing_nos:
                        results.append({
                            "Equipment": r[0],
                            "Material": r[1],
                            "SerialNumber": r[2],
                            "ManufacturerPartNmbr": "OEM-PART-GENERIC",
                            "FunctionalLocation": r[3],
                            "EquipInstallationDate": str(r[4].date()) if r[4] else "2026-01-01",
                        })
    except Exception:
        pass

    # Filter
    if filter_expr:
        filter_expr = filter_expr.strip()
        if "FunctionalLocation eq" in filter_expr:
            import re
            m = re.search(r"FunctionalLocation eq '([^']+)'", filter_expr)
            if m:
                fl = m.group(1)
                results = [e for e in results if e.get("FunctionalLocation") == fl]
        elif "startswith(FunctionalLocation" in filter_expr:
            import re
            m = re.search(r"startswith\(FunctionalLocation,\s*'([^']+)'\)", filter_expr)
            if m:
                fl_pre = m.group(1)
                results = [e for e in results if (e.get("FunctionalLocation") or "").startswith(fl_pre)]

    skip_val = skip or 0
    top_val = top or 1000
    paged = results[skip_val : skip_val + top_val]

    return {
        "d": {
            "results": paged,
            "__count": len(results),
        }
    }


class EquipmentCreate(BaseModel):
    Material: str
    SerialNumber: str
    FunctionalLocation: str | None = None


class InstallRequest(BaseModel):
    FunctionalLocation: str


@router.post("/A_Equipment")
async def create_equipment(
    eq_in: EquipmentCreate,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            eq_num = str(allocate_number(cur, sap_client, "EQUIPMENT"))
            cur.execute(
                """
                INSERT INTO erpsim.equipment (client, equipment_no, material_no, serial_no, func_loc, status)
                VALUES (%s, %s, %s, %s, %s, %s);
            """,
                (
                    sap_client,
                    eq_num,
                    eq_in.Material,
                    eq_in.SerialNumber,
                    eq_in.FunctionalLocation,
                    "installed" if eq_in.FunctionalLocation else "available",
                ),
            )
            if eq_in.FunctionalLocation:
                cur.execute(
                    """
                    INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action)
                    VALUES (%s, %s, %s, 'install');
                """,
                    (sap_client, eq_num, eq_in.FunctionalLocation),
                )
            conn.commit()

            return {
                "d": {
                    "Equipment": eq_num,
                    "Material": eq_in.Material,
                    "SerialNumber": eq_in.SerialNumber,
                    "FunctionalLocation": eq_in.FunctionalLocation,
                }
            }


@router.post("/Install?Equipment={equipment}")
async def install_equipment(
    equipment: str,
    body: InstallRequest,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT func_loc, status FROM erpsim.equipment WHERE client = %s AND equipment_no = %s;",
                (sap_client, equipment),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "code": "ZSIM/NOT-FOUND",
                            "message": {"lang": "en", "value": f"Equipment {equipment} not found"},
                        }
                    },
                )
            if row[0] is not None or row[1] == "installed":
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "code": "ZSIM/EQ-INSTALLED",
                            "message": {
                                "lang": "en",
                                "value": f"Equipment {equipment} already installed at {row[0]}",
                            },
                        }
                    },
                )

            cur.execute(
                "UPDATE erpsim.equipment SET func_loc = %s, status = 'installed' WHERE client = %s AND equipment_no = %s;",
                (body.FunctionalLocation, sap_client, equipment),
            )
            cur.execute(
                "INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action) VALUES (%s, %s, %s, 'install');",
                (sap_client, equipment, body.FunctionalLocation),
            )
            conn.commit()
    return {
        "d": {
            "Equipment": equipment,
            "FunctionalLocation": body.FunctionalLocation,
            "Status": "installed",
        }
    }


@router.post("/Dismantle?Equipment={equipment}")
async def dismantle_equipment(
    equipment: str,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT func_loc FROM erpsim.equipment WHERE client = %s AND equipment_no = %s;",
                (sap_client, equipment),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "code": "ZSIM/NOT-INSTALLED",
                            "message": {
                                "lang": "en",
                                "value": f"Equipment {equipment} is not installed",
                            },
                        }
                    },
                )

            old_loc = row[0]
            cur.execute(
                "UPDATE erpsim.equipment SET func_loc = NULL, status = 'available' WHERE client = %s AND equipment_no = %s;",
                (sap_client, equipment),
            )
            cur.execute(
                "INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action) VALUES (%s, %s, %s, 'dismantle');",
                (sap_client, equipment, old_loc),
            )
            conn.commit()
    return {"d": {"Equipment": equipment, "Status": "available"}}
