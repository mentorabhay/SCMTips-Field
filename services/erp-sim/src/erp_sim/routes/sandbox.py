"""Sandbox administration (M3 contract section 3): what a home / training site may do in the simulator.

These are NOT SAP capabilities and have no OData shape on purpose; a real S/4 system is never asked for
them (the S/4 adapter refuses them). Every call needs X-Sim-Admin-Token (ERPSIM_ADMIN_TOKEN).

POST /_sim/sandbox/materials                          {Plant, Description, BaseUnit?, Barcode}
     -> 201 a new material HOME-nnnn of that plant with the barcode (MEAN), or 200 the material the
        barcode already belongs to (idempotent on the barcode).
POST /_sim/sandbox/inbound-deliveries                 {Plant, StorageLocation, Supplier?, Simulated?}
     -> 201 an open inbound delivery with no items, header ``sandbox: true``.
POST /_sim/sandbox/inbound-deliveries/{doc}/items     {Material, DeliveryQuantity?, DeliveryQuantityUnit?}
     (Idempotency-Key) -> 201 the next item (10, 20, ...); the same key returns the first item.
POST /_sim/sandbox/plants                             {Plant, Name, StorageLocations: [{StorageLocation, Name}]}
     (M5-H01, the hosted sandbox seed) -> 201 when the plant or a storage location was added, 200 when all of them
        were there already. Existing rows are never renamed or removed; each one says whether it was Created.
"""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from erp_sim.db import get_conn
from erp_sim.dedupe import check_dedupe, compute_request_hash, record_dedupe
from erp_sim.numbering import allocate_number

router = APIRouter(prefix="/_sim/sandbox", tags=["Simulator sandbox (M3)"])

SANDBOX_PREFIX = "HOME-"


def _sap_error(status: int, code: str, text: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": {"lang": "en", "value": text}}})


def _one(cur: Any) -> tuple[Any, ...]:
    row = cur.fetchone()
    if row is None:
        raise _sap_error(500, "ZSIM/DB", "the database returned no row")
    return tuple(row)


def verify_admin(token: str | None) -> None:
    if token != os.getenv("ERPSIM_ADMIN_TOKEN", "dev-sim-admin-token"):
        raise _sap_error(401, "ZSIM/ADMIN", "Invalid X-Sim-Admin-Token")


class SandboxMaterialIn(BaseModel):
    Plant: str = Field(min_length=1, max_length=4)
    Description: str = Field(min_length=1, max_length=40)
    BaseUnit: str = Field(default="EA", min_length=1, max_length=3)
    Barcode: str = Field(min_length=1, max_length=128)


class SandboxDeliveryIn(BaseModel):
    Plant: str = Field(min_length=1, max_length=4)
    StorageLocation: str = Field(min_length=1, max_length=4)
    Supplier: str = "HOME"
    Simulated: bool = False


class SandboxItemIn(BaseModel):
    Material: str = Field(min_length=1, max_length=40)
    DeliveryQuantity: Decimal = Field(default=Decimal(0), ge=0)
    DeliveryQuantityUnit: str = "EA"


class SandboxStorageLocationIn(BaseModel):
    StorageLocation: str = Field(min_length=1, max_length=4)
    Name: str = Field(default="", max_length=40)


class SandboxPlantIn(BaseModel):
    Plant: str = Field(min_length=1, max_length=4)
    Name: str = Field(min_length=1, max_length=40)
    StorageLocations: list[SandboxStorageLocationIn] = Field(default_factory=list, max_length=20)


def _material_out(cur: Any, client: str, material_no: str, barcode: str, created: bool) -> dict[str, Any]:
    cur.execute("SELECT description, base_uom, sandbox_plant FROM erpsim.material WHERE client = %s AND material_no = %s",
                (client, material_no))
    row = cur.fetchone()
    return {"Product": material_no, "ProductDescription": row[0], "BaseUnit": row[1], "Plant": row[2],
            "ProductStandardID": barcode, "Created": created}


@router.post("/materials", status_code=201)
async def create_sandbox_material(
    body: SandboxMaterialIn,
    response: Response,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    verify_admin(x_sim_admin_token)
    code = body.Barcode.strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM erpsim.plant WHERE client = %s AND plant = %s", (sap_client, body.Plant))
        if cur.fetchone() is None:
            raise _sap_error(404, "ZSIM/NOT-FOUND", f"Plant {body.Plant} does not exist")
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"sbx-barcode:{sap_client}:{code}",))
        cur.execute("SELECT material_no FROM erpsim.material_barcode WHERE client = %s AND barcode = %s",
                    (sap_client, code))
        row = cur.fetchone()
        if row:
            response.status_code = 200
            return {"d": _material_out(cur, sap_client, str(row[0]), code, False)}
        while True:  # a number left over from before a reset may still be taken
            material_no = f"{SANDBOX_PREFIX}{allocate_number(cur, sap_client, 'SANDBOX_MATERIAL'):04d}"
            cur.execute("SELECT 1 FROM erpsim.material WHERE client = %s AND material_no = %s", (sap_client, material_no))
            if cur.fetchone() is None:
                break
        cur.execute(
            "INSERT INTO erpsim.material (client, material_no, description, base_uom, sandbox_plant)"
            " VALUES (%s, %s, %s, %s, %s)",
            (sap_client, material_no, body.Description.strip(), body.BaseUnit, body.Plant),
        )
        cur.execute(
            "INSERT INTO erpsim.material_barcode (client, material_no, barcode, uom, is_main) VALUES (%s, %s, %s, %s, true)",
            (sap_client, material_no, code, body.BaseUnit),
        )
        out = _material_out(cur, sap_client, material_no, code, True)
        conn.commit()
    return {"d": out}


def _free_delivery_number(cur: Any, client: str) -> str:
    """A 10-digit sandbox delivery number 19xxxxxxxx from the clock, so it is not reused after a simulator reset
    (the INBOUND_DELIVERY range restarts at a reset, while the field still holds tasks for the old numbers)."""
    base = time.time_ns() // 100_000_000  # tenths of a second
    for n in range(1000):
        cand = f"19{(base + n) % 10**8:08d}"
        cur.execute("SELECT 1 FROM erpsim.inbound_delivery WHERE client = %s AND delivery_document = %s", (client, cand))
        if cur.fetchone() is None:
            return cand
    raise _sap_error(500, "ZSIM/NUMBER-RANGE", "no free inbound delivery number")


@router.post("/inbound-deliveries", status_code=201)
async def create_sandbox_delivery(
    body: SandboxDeliveryIn,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    verify_admin(x_sim_admin_token)
    head: dict[str, Any] = {"Vendor": body.Supplier, "sandbox": True}
    if body.Simulated:
        head["simulated"] = True
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM erpsim.plant WHERE client = %s AND plant = %s", (sap_client, body.Plant))
        if cur.fetchone() is None:
            raise _sap_error(404, "ZSIM/NOT-FOUND", f"Plant {body.Plant} does not exist")
        deliv = _free_delivery_number(cur, sap_client)
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)"
            " VALUES (%s, %s, %s, %s, 'open', %s) RETURNING last_change_date_time",
            (sap_client, deliv, body.Plant, body.StorageLocation, json.dumps(head)),
        )
        changed = _one(cur)[0]
        conn.commit()
    return {"d": {"DeliveryDocument": deliv, "ReceivingPlant": body.Plant, "StorageLocation": body.StorageLocation,
                  "Supplier": body.Supplier, "LastChangeDateTime": changed.isoformat(), "Sandbox": True}}


@router.post("/inbound-deliveries/{delivery_document}/items", status_code=201)
async def add_sandbox_delivery_item(
    delivery_document: str,
    body: SandboxItemIn,
    request: Request,
    response: Response,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    verify_admin(x_sim_admin_token)
    req_hash = compute_request_hash(await request.body())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, header_data FROM erpsim.inbound_delivery WHERE client = %s AND delivery_document = %s"
            " FOR UPDATE",
            (sap_client, delivery_document),
        )
        row = cur.fetchone()
        if row is None:
            raise _sap_error(404, "ZSIM/NOT-FOUND", f"Delivery {delivery_document} not found")
        if not (isinstance(row[1], dict) and row[1].get("sandbox")):
            raise _sap_error(400, "ZSIM/NOT-SANDBOX", f"Delivery {delivery_document} is not a sandbox delivery")
        if idempotency_key:
            is_dup, dup_doc, dup_item = check_dedupe(cur, sap_client, f"sbx-item:{idempotency_key}", req_hash)
            if is_dup:
                response.status_code = 200
                return {"d": {"DeliveryDocument": dup_doc, "DeliveryDocumentItem": dup_item, "Material": body.Material}}
        if row[0] != "open":
            raise _sap_error(400, "ZSIM/ALREADY-POSTED", f"Delivery {delivery_document} is {row[0]}")
        cur.execute("SELECT 1 FROM erpsim.material WHERE client = %s AND material_no = %s", (sap_client, body.Material))
        if cur.fetchone() is None:
            raise _sap_error(404, "ZSIM/NOT-FOUND", f"Material {body.Material} does not exist")
        cur.execute(
            "SELECT COALESCE(MAX(item_no::int), 0) FROM erpsim.inbound_delivery_item"
            " WHERE client = %s AND delivery_document = %s",
            (sap_client, delivery_document),
        )
        item_no = f"{(int(_one(cur)[0]) // 10 + 1) * 10:06d}"
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
            " actual_qty, uom, status) VALUES (%s, %s, %s, %s, %s, 0, %s, 'open')",
            (sap_client, delivery_document, item_no, body.Material, body.DeliveryQuantity, body.DeliveryQuantityUnit),
        )
        cur.execute(
            "UPDATE erpsim.inbound_delivery SET last_change_date_time = NOW() WHERE client = %s AND delivery_document = %s"
            " RETURNING last_change_date_time",
            (sap_client, delivery_document),
        )
        changed = _one(cur)[0]
        if idempotency_key:
            record_dedupe(cur, sap_client, f"sbx-item:{idempotency_key}", req_hash, delivery_document, item_no)
        conn.commit()
    return {"d": {"DeliveryDocument": delivery_document, "DeliveryDocumentItem": item_no, "Material": body.Material,
                  "ActualDeliveryQuantity": str(body.DeliveryQuantity), "DeliveryQuantityUnit": body.DeliveryQuantityUnit,
                  "LastChangeDateTime": changed.isoformat()}}


@router.post("/plants", status_code=201)
async def ensure_sandbox_plant(
    body: SandboxPlantIn,
    response: Response,
    x_sim_admin_token: str | None = Header(None, alias="X-Sim-Admin-Token"),
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    """A plant and its storage locations for a sandbox site, idempotent (M5-H01): what is missing is added."""
    verify_admin(x_sim_admin_token)
    slocs = list({s.StorageLocation: s for s in body.StorageLocations}.values())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"sbx-plant:{sap_client}:{body.Plant}",))
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"
                    " RETURNING plant", (sap_client, body.Plant, body.Name))
        plant_created = cur.fetchone() is not None
        out: list[dict[str, Any]] = []
        for sl in slocs:
            cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING storage_location",
                        (sap_client, body.Plant, sl.StorageLocation, sl.Name or sl.StorageLocation))
            created = cur.fetchone() is not None
            cur.execute("SELECT name FROM erpsim.storage_location WHERE client = %s AND plant = %s"
                        " AND storage_location = %s", (sap_client, body.Plant, sl.StorageLocation))
            out.append({"StorageLocation": sl.StorageLocation, "Name": str(_one(cur)[0] or ""), "Created": created})
        cur.execute("SELECT name FROM erpsim.plant WHERE client = %s AND plant = %s", (sap_client, body.Plant))
        name = str(_one(cur)[0] or "")
        conn.commit()
    if not plant_created and not any(o["Created"] for o in out):
        response.status_code = 200
    return {"d": {"Plant": body.Plant, "Name": name, "Created": plant_created, "StorageLocations": out}}
