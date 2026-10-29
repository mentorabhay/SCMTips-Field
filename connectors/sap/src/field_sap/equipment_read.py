"""SAP Installed Equipment Reader (Task T4.005 / FR4.005 / TC4.102).

Reads API_EQUIPMENT fields (Equipment, SerialNumber, Material, ManufacturerPartNmbr,
FunctionalLocation, EquipInstallationDate) and detects duplicate serial numbers.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_ERP_SIM_URL = os.environ.get("ERPSIM_URL", "http://127.0.0.1:8001")


class EquipmentReader:
    """Reader for SAP S/4HANA API_EQUIPMENT OData service."""

    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url or DEFAULT_ERP_SIM_URL).rstrip("/")
        self.endpoint = f"{self.base_url}/sap/opu/odata/sap/API_EQUIPMENT/Equipment"
        self._client = client

    def read_equipment(
        self,
        fl_prefix: str | None = None,
        page_size: int = 1000,
        max_rows: int = 50000,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Page through API_EQUIPMENT and return (equipment_list, duplicate_serials_report).

        Returns:
            Tuple containing:
            1. List of standardized equipment dicts with 6 key fields.
            2. List of duplicate serial reports.
        """
        filter_expr = f"startswith(FunctionalLocation, '{fl_prefix}')" if fl_prefix else None

        all_results: list[dict[str, Any]] = []
        skip = 0

        client = self._client or httpx.Client(timeout=30.0)
        try:
            while len(all_results) < max_rows:
                params: dict[str, Any] = {
                    "$top": page_size,
                    "$skip": skip,
                }
                if filter_expr:
                    params["$filter"] = filter_expr

                resp = client.get(
                    self.endpoint,
                    params=params,
                    headers={"Accept": "application/json", "sap-client": "100"},
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("d", {}).get("results", [])
                if not results:
                    break

                for r in results:
                    all_results.append({
                        "equipment_no": r.get("Equipment"),
                        "serial_no": r.get("SerialNumber"),
                        "material_no": r.get("Material"),
                        "mfr_part_no": r.get("ManufacturerPartNmbr"),
                        "functional_location": r.get("FunctionalLocation"),
                        "install_date": r.get("EquipInstallationDate"),
                    })

                if len(results) < page_size:
                    break
                skip += len(results)

        finally:
            if self._client is None:
                client.close()

        # Check for serial number duplicates
        serial_to_equip = defaultdict(list)
        for eq in all_results:
            sn = eq.get("serial_no")
            if sn:
                serial_to_equip[sn].append(eq["equipment_no"])

        duplicates = [
            {"serial_no": sn, "equipment_nos": eq_list, "count": len(eq_list)}
            for sn, eq_list in serial_to_equip.items()
            if len(eq_list) > 1
        ]

        if duplicates:
            logger.warn("equipment_read.duplicate_serials_found", duplicates=duplicates)

        return all_results, duplicates
