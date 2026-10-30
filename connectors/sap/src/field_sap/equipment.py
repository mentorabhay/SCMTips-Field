"""SAP Adapter Equipment Operations (Task T4.021 / FR4.029 / FR4.030).

Implements install, dismantle, create, and time-segment operations against SAP S/4HANA
API_EQUIPMENT OData service (or erp-sim emulation).
Carries idempotency key in long-text marker [IDEM:{key}].
Maps SAP messages to FIELD domain error codes.
Gated by FIELD_SAP_EQUIPMENT_LIVE environment variable (UNVERIFIED for live SAP).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_ERP_SIM_URL = os.environ.get("ERPSIM_URL", "http://127.0.0.1:8001")
FIELD_SAP_EQUIPMENT_LIVE = os.environ.get("FIELD_SAP_EQUIPMENT_LIVE", "false").lower() in ("true", "1", "yes")


class SAPEquipmentError(Exception):
    """Base exception for SAP equipment operations."""

    def __init__(self, message: str, code: str = "FIELD-EQ-500-SAP-ERROR", raw_error: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.raw_error = raw_error or {}


class SAPEquipmentNotFoundError(SAPEquipmentError):
    def __init__(self, message: str, raw_error: dict[str, Any] | None = None):
        super().__init__(message, code="FIELD-EQ-404-NOT-FOUND", raw_error=raw_error)


class SAPEquipmentAlreadyInstalledError(SAPEquipmentError):
    def __init__(self, message: str, raw_error: dict[str, Any] | None = None):
        super().__init__(message, code="FIELD-EQ-409-ALREADY-INSTALLED", raw_error=raw_error)


class SAPEquipmentNotInstalledError(SAPEquipmentError):
    def __init__(self, message: str, raw_error: dict[str, Any] | None = None):
        super().__init__(message, code="FIELD-EQ-400-NOT-INSTALLED", raw_error=raw_error)


class SAPIdempotencyConflictError(SAPEquipmentError):
    def __init__(self, message: str, raw_error: dict[str, Any] | None = None):
        super().__init__(message, code="FIELD-IDEM-422-KEY-REUSED", raw_error=raw_error)


def map_sap_error_to_field_exception(status_code: int, detail: Any) -> SAPEquipmentError:
    """Map SAP OData error payload to typed FIELD domain exception."""
    error_dict = detail if isinstance(detail, dict) else {}
    if "error" in error_dict:
        inner = error_dict["error"]
        sap_code = inner.get("code", "")
        message = inner.get("message", {}).get("value", str(detail))
    else:
        sap_code = error_dict.get("code", "")
        message = error_dict.get("message", str(detail))

    if sap_code == "ZSIM/NOT-FOUND" or status_code == 404:
        return SAPEquipmentNotFoundError(message, raw_error=error_dict)
    if sap_code == "ZSIM/EQ-INSTALLED":
        return SAPEquipmentAlreadyInstalledError(message, raw_error=error_dict)
    if sap_code == "ZSIM/NOT-INSTALLED":
        return SAPEquipmentNotInstalledError(message, raw_error=error_dict)
    if sap_code in ("ZSIM/IDEM-CONFLICT", "FIELD-IDEM-422-KEY-REUSED"):
        return SAPIdempotencyConflictError(message, raw_error=error_dict)

    return SAPEquipmentError(f"SAP operation failed: {message}", code=f"FIELD-SAP-{status_code}-ERROR", raw_error=error_dict)


class SAPEquipmentAdapter:
    """Adapter for SAP S/4HANA API_EQUIPMENT operations."""

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        live_mode: bool | None = None,
        sap_client: str = "100",
    ):
        self.base_url = (base_url or DEFAULT_ERP_SIM_URL).rstrip("/")
        self.api_root = f"{self.base_url}/sap/opu/odata/sap/API_EQUIPMENT"
        self._client = client
        self.live_mode = FIELD_SAP_EQUIPMENT_LIVE if live_mode is None else live_mode
        self.sap_client = sap_client

        if self.live_mode:
            logger.info("sap_adapter_equipment_live_mode_enabled", target=self.base_url)
        else:
            logger.info("sap_adapter_equipment_sim_mode_enabled", target=self.base_url)

    def _get_client(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=30.0)

    def create_equipment(
        self,
        material: str,
        serial_no: str,
        func_loc: str | None = None,
    ) -> dict[str, Any]:
        """Create new equipment master in SAP (A_Equipment)."""
        payload = {
            "Material": material,
            "SerialNumber": serial_no,
            "FunctionalLocation": func_loc,
        }
        client = self._get_client()
        resp = client.post(
            f"{self.api_root}/A_Equipment",
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "sap-client": self.sap_client,
            },
        )
        if resp.is_error:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise map_sap_error_to_field_exception(resp.status_code, err_body)

        data = resp.json().get("d", {})
        return {
            "equipment_no": data.get("Equipment"),
            "material": data.get("Material"),
            "serial_no": data.get("SerialNumber"),
            "func_loc": data.get("FunctionalLocation"),
        }

    def install_equipment(
        self,
        equipment_no: str,
        func_loc: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Install equipment at functional location with long-text idempotency marker."""
        long_text = f"[IDEM:{idempotency_key}]" if idempotency_key else None
        payload = {
            "FunctionalLocation": func_loc,
            "Equipment": equipment_no,
            "LongText": long_text,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "sap-client": self.sap_client,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        client = self._get_client()
        resp = client.post(
            f"{self.api_root}/Install",
            json=payload,
            headers=headers,
        )
        if resp.is_error:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise map_sap_error_to_field_exception(resp.status_code, err_body)

        res_json = resp.json()
        data = res_json.get("d", {})
        is_dup = res_json.get("sap-message") == "ZSIM/DUP" or resp.headers.get("sap-message") == "ZSIM/DUP"

        return {
            "equipment_no": data.get("Equipment", equipment_no),
            "func_loc": data.get("FunctionalLocation", func_loc),
            "status": data.get("Status", "installed"),
            "change_document": data.get("ChangeDocument"),
            "is_duplicate": is_dup,
        }

    def dismantle_equipment(
        self,
        equipment_no: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Dismantle equipment from its current functional location."""
        long_text = f"[IDEM:{idempotency_key}]" if idempotency_key else None
        payload = {
            "Equipment": equipment_no,
            "LongText": long_text,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "sap-client": self.sap_client,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        client = self._get_client()
        resp = client.post(
            f"{self.api_root}/Dismantle",
            json=payload,
            headers=headers,
        )
        if resp.is_error:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise map_sap_error_to_field_exception(resp.status_code, err_body)

        res_json = resp.json()
        data = res_json.get("d", {})
        is_dup = res_json.get("sap-message") == "ZSIM/DUP" or resp.headers.get("sap-message") == "ZSIM/DUP"

        return {
            "equipment_no": data.get("Equipment", equipment_no),
            "func_loc": data.get("FunctionalLocation"),
            "status": data.get("Status", "available"),
            "change_document": data.get("ChangeDocument"),
            "is_duplicate": is_dup,
        }

    def get_time_segments(self, equipment_no: str) -> list[dict[str, Any]]:
        """Query historical time segments for equipment."""
        client = self._get_client()
        resp = client.get(
            f"{self.api_root}/Equipment('{equipment_no}')/TimeSegments",
            headers={"Accept": "application/json", "sap-client": self.sap_client},
        )
        if resp.is_error:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise map_sap_error_to_field_exception(resp.status_code, err_body)

        data = resp.json().get("d", {})
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise ValueError("SAP equipment response 'results' is not a list")
        return [r for r in results if isinstance(r, dict)]
