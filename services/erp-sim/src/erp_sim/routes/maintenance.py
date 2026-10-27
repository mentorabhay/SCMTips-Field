"""Plant Maintenance Documents Implementation (Task T1.050).

API_MAINTENANCEORDER, API_MAINTNOTIFICATION, measurement documents (illustrative).
"""

from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel

from erp_sim.db import get_conn
from erp_sim.numbering import allocate_number

router = APIRouter(prefix="/sap/opu/odata/sap", tags=["Plant Maintenance"])


class OrderCreate(BaseModel):
    OrderDescription: str
    Equipment: str | None = None
    FunctionalLocation: str | None = None


class NotifCreate(BaseModel):
    NotificationText: str
    Equipment: str | None = None


class MeasDocCreate(BaseModel):
    MeasuringPoint: str
    CharacteristicValue: str
    MeasurementReading: str
    MeasurementReadingUnit: str = "CEL"


@router.post("/API_MAINTENANCEORDER/MaintenanceOrder")
async def create_maintenance_order(
    body: OrderCreate,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        order_no = str(allocate_number(cur, sap_client, "MAINT_ORDER"))
        conn.commit()
    return {"d": {"MaintenanceOrder": order_no, "OrderDescription": body.OrderDescription}}


@router.post("/API_MAINTNOTIFICATION/MaintenanceNotification")
async def create_maintenance_notification(
    body: NotifCreate,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        notif_no = str(allocate_number(cur, sap_client, "MAINT_NOTIF"))
        conn.commit()
    return {"d": {"MaintenanceNotification": notif_no, "NotificationText": body.NotificationText}}


@router.post("/API_MEASUREMENTDOCUMENT_SRV/MeasurementDocument")
async def create_measurement_doc(
    body: MeasDocCreate,
    sap_client: str = Header("100", alias="sap-client"),
) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        meas_no = str(allocate_number(cur, sap_client, "MEASUREMENT_DOC"))
        conn.commit()
    return {
        "d": {
            "MeasurementDocument": meas_no,
            "MeasuringPoint": body.MeasuringPoint,
            "Reading": body.MeasurementReading,
        }
    }
