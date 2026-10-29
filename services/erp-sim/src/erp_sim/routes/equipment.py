"""API_EQUIPMENT Implementation (Task T1.049).

Create equipment (10000000-19999999) with serial and material,
install at functional location with date-time, dismantle;
install history kept in equipment_install; installing installed equipment fails ZSIM/EQ-INSTALLED.
"""

import json
from pathlib import Path
from typing import Any, cast

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
                data = json.load(f)
                return cast(list[dict[str, Any]], data.get("equipment", []))
        return []
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        data = json.load(f)
        return cast(list[dict[str, Any]], data.get("equipment", []))


@router.get("/Equipment")
@router.get("/A_Equipment")
async def list_equipment(
    filter_expr: str | None = Query(None, alias="$filter"),
    top: int | None = Query(1000, alias="$top"),
    skip: int | None = Query(0, alias="$skip"),
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
    FunctionalLocation: str | None = None
    Equipment: str | None = None
    LongText: str | None = None


class DismantleRequest(BaseModel):
    Equipment: str | None = None
    FunctionalLocation: str | None = None
    LongText: str | None = None


@router.get("/Equipment('{equipment}')/TimeSegments")
@router.get("/Equipment/{equipment}/time-segments")
@router.get("/A_Equipment('{equipment}')/TimeSegments")
async def get_equipment_time_segments(
    equipment: str,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """Retrieve historical equipment installation time segments (T4.020 / FR4.030)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT func_loc, action, timestamp, change_doc
                FROM erpsim.equipment_install
                WHERE client = %s AND equipment_no = %s
                ORDER BY timestamp ASC;
                """,
                (sap_client, equipment),
            )
            rows = cur.fetchall()

            segments: list[dict[str, Any]] = []
            curr_segment: dict[str, Any] | None = None

            for r in rows:
                func_loc, action, ts, change_doc = r[0], r[1], r[2], r[3]
                ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

                if action == "install":
                    if curr_segment:
                        curr_segment["valid_to"] = ts_iso
                        segments.append(curr_segment)
                    curr_segment = {
                        "Equipment": equipment,
                        "FunctionalLocation": func_loc,
                        "valid_from": ts_iso,
                        "valid_to": "9999-12-31T23:59:59Z",
                        "status": "installed",
                        "change_doc": change_doc,
                    }
                elif action == "dismantle":
                    if curr_segment:
                        curr_segment["valid_to"] = ts_iso
                        segments.append(curr_segment)
                        curr_segment = None
                    segments.append({
                        "Equipment": equipment,
                        "FunctionalLocation": func_loc,
                        "valid_from": ts_iso,
                        "valid_to": ts_iso,
                        "status": "dismantled",
                        "change_doc": change_doc,
                    })

            if curr_segment:
                segments.append(curr_segment)

            return {
                "d": {
                    "results": segments,
                    "__count": len(segments),
                }
            }


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


@router.post("/Install")
@router.post("/Install?Equipment={equipment}")
@router.post("/Equipment('{equipment}')/Install")
@router.post("/A_Equipment('{equipment}')/Install")
async def install_equipment(
    equipment: str | None = None,
    Equipment: str | None = Query(None),
    body: InstallRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    sim_fault_profile: str | None = Header(None, alias="X-Sim-Fault-Profile"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """Install equipment at functional location with change document, dedupe, and fault checks (T4.020)."""
    eq_target = equipment or Equipment or (body.Equipment if body else None)
    if not eq_target:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "ZSIM/PARAM-MISSING", "message": {"lang": "en", "value": "Equipment parameter required"}}},
        )
    fl_target = body.FunctionalLocation if body else None
    if not fl_target:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "ZSIM/PARAM-MISSING", "message": {"lang": "en", "value": "FunctionalLocation parameter required"}}},
        )

    # Extract idempotency key from header or long text
    idem_key = idempotency_key
    if not idem_key and body and body.LongText:
        import re
        m = re.search(r"\[IDEM:([^\]]+)\]", body.LongText)
        if m:
            idem_key = m.group(1)

    req_data = {"action": "install", "equipment": eq_target, "func_loc": fl_target}
    from erp_sim.dedupe import check_dedupe, compute_request_hash, record_dedupe
    req_hash = compute_request_hash(req_data)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Fault injection check
            from erp_sim.faults import evaluate_faults
            await evaluate_faults(cur, sap_client, "API_EQUIPMENT", "Install", eq_target)

            # Dedupe check
            if idem_key:
                is_dup, doc_no, _ = check_dedupe(cur, sap_client, idem_key, req_hash)
                if is_dup:
                    return {
                        "d": {
                            "Equipment": eq_target,
                            "FunctionalLocation": fl_target,
                            "Status": "installed",
                            "ChangeDocument": doc_no,
                        },
                        "sap-message": "ZSIM/DUP",
                    }

            cur.execute(
                "SELECT func_loc, status FROM erpsim.equipment WHERE client = %s AND equipment_no = %s FOR UPDATE;",
                (sap_client, eq_target),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "code": "ZSIM/NOT-FOUND",
                            "message": {"lang": "en", "value": f"Equipment {eq_target} not found"},
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
                                "value": f"Equipment {eq_target} already installed at {row[0]}",
                            },
                        }
                    },
                )

            change_doc = str(allocate_number(cur, sap_client, "CHANGE_DOC"))

            cur.execute(
                "UPDATE erpsim.equipment SET func_loc = %s, status = 'installed' WHERE client = %s AND equipment_no = %s;",
                (fl_target, sap_client, eq_target),
            )
            cur.execute(
                """
                INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action, change_doc)
                VALUES (%s, %s, %s, 'install', %s);
                """,
                (sap_client, eq_target, fl_target, change_doc),
            )

            if idem_key:
                record_dedupe(cur, sap_client, idem_key, req_hash, change_doc, "2026")

            conn.commit()

    return {
        "d": {
            "Equipment": eq_target,
            "FunctionalLocation": fl_target,
            "Status": "installed",
            "ChangeDocument": change_doc,
        }
    }


@router.post("/Dismantle")
@router.post("/Dismantle?Equipment={equipment}")
@router.post("/Equipment('{equipment}')/Dismantle")
@router.post("/A_Equipment('{equipment}')/Dismantle")
async def dismantle_equipment(
    equipment: str | None = None,
    Equipment: str | None = Query(None),
    body: DismantleRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    sim_fault_profile: str | None = Header(None, alias="X-Sim-Fault-Profile"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """Dismantle equipment from functional location with change document and dedupe (T4.020)."""
    eq_target = equipment or Equipment or (body.Equipment if body else None)
    if not eq_target:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "ZSIM/PARAM-MISSING", "message": {"lang": "en", "value": "Equipment parameter required"}}},
        )

    idem_key = idempotency_key
    if not idem_key and body and body.LongText:
        import re
        m = re.search(r"\[IDEM:([^\]]+)\]", body.LongText)
        if m:
            idem_key = m.group(1)

    req_data = {"action": "dismantle", "equipment": eq_target}
    from erp_sim.dedupe import check_dedupe, compute_request_hash, record_dedupe
    req_hash = compute_request_hash(req_data)

    with get_conn() as conn:
        with conn.cursor() as cur:
            from erp_sim.faults import evaluate_faults
            await evaluate_faults(cur, sap_client, "API_EQUIPMENT", "Dismantle", eq_target)

            if idem_key:
                is_dup, doc_no, _ = check_dedupe(cur, sap_client, idem_key, req_hash)
                if is_dup:
                    return {
                        "d": {
                            "Equipment": eq_target,
                            "Status": "available",
                            "ChangeDocument": doc_no,
                        },
                        "sap-message": "ZSIM/DUP",
                    }

            cur.execute(
                "SELECT func_loc, status FROM erpsim.equipment WHERE client = %s AND equipment_no = %s FOR UPDATE;",
                (sap_client, eq_target),
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
                                "value": f"Equipment {eq_target} is not installed",
                            },
                        }
                    },
                )

            old_loc = row[0]
            change_doc = str(allocate_number(cur, sap_client, "CHANGE_DOC"))

            cur.execute(
                "UPDATE erpsim.equipment SET func_loc = NULL, status = 'available' WHERE client = %s AND equipment_no = %s;",
                (sap_client, eq_target),
            )
            cur.execute(
                """
                INSERT INTO erpsim.equipment_install (client, equipment_no, func_loc, action, change_doc)
                VALUES (%s, %s, %s, 'dismantle', %s);
                """,
                (sap_client, eq_target, old_loc, change_doc),
            )

            if idem_key:
                record_dedupe(cur, sap_client, idem_key, req_hash, change_doc, "2026")

            conn.commit()

    return {
        "d": {
            "Equipment": eq_target,
            "FunctionalLocation": old_loc,
            "Status": "available",
            "ChangeDocument": change_doc,
        }
    }
