"""SAP Functional Location Reader (Task T4.004 / FR4.004 / TC4.101).

Paginates OData service API_FUNCTIONALLOCATION with $filter on prefix and LastChangeDateTime,
mapping remote entities to local staging dictionaries.
Service status: UNVERIFIED (Phase 4).
"""

from __future__ import annotations

import os
from typing import Any, Optional
import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_ERP_SIM_URL = os.environ.get("ERPSIM_URL", "http://127.0.0.1:8001")


class FunctionalLocationReader:
    """Reader for SAP S/4HANA API_FUNCTIONALLOCATION OData service."""

    def __init__(self, base_url: Optional[str] = None, client: Optional[httpx.Client] = None):
        self.base_url = (base_url or DEFAULT_ERP_SIM_URL).rstrip("/")
        self.endpoint = f"{self.base_url}/sap/opu/odata/sap/API_FUNCTIONALLOCATION/FunctionalLocation"
        self._client = client

    def read_functional_locations(
        self,
        prefix: Optional[str] = None,
        watermark_from: Optional[str] = None,
        page_size: int = 1000,
        max_rows: int = 50000,
    ) -> list[dict[str, Any]]:
        """Page through API_FUNCTIONALLOCATION and fetch all matching functional locations."""
        filter_parts = []
        if prefix:
            filter_parts.append(f"startswith(FunctionalLocation, '{prefix}')")
        if watermark_from:
            filter_parts.append(f"LastChangeDateTime gt datetime'{watermark_from}'")

        filter_expr = " and ".join(filter_parts) if filter_parts else None

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
                        "fl_code": r.get("FunctionalLocation"),
                        "parent_fl_code": r.get("SuperiorFunctionalLocation") or None,
                        "name": r.get("FunctionalLocationName", ""),
                        "plant": r.get("MaintenancePlant", ""),
                        "last_change": r.get("LastChangeDateTime"),
                        "kind": r.get("Kind"),
                        "height_m": r.get("HeightM"),
                        "sector_code": r.get("SectorCode"),
                    })

                if len(results) < page_size:
                    break
                skip += len(results)

        finally:
            if self._client is None:
                client.close()

        logger.info("fl_import.read_complete", count=len(all_results), prefix=prefix)
        return all_results
