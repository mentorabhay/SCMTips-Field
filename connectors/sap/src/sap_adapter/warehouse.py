"""SAP Warehouse Adapter Implementation (Task T3.007 / FR3.041, FR3.044).

Implements:
- CSRF token fetching and caching
- sap-client header injection
- If-Match header handling on PATCH operations
- Function import invocation: PostGoodsReceipt, PostGoodsIssue, ReverseGoodsIssue, PostDifferences, Cancel
- Pre-post probe via document flow status check
- SAP error response parsing and classification into retryable vs non-retryable classes
- Golden payload rendering for deterministic contract parity
"""

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = float(os.getenv("FIELD_SAP_TIMEOUT_S", "10.0"))


@dataclass(frozen=True)
class SapErrorClassification:
    is_retryable: bool
    code: str
    message: str
    status_code: int


def classify_sap_error(status_code: int, response_data: dict[str, Any] | str | None) -> SapErrorClassification:
    """Classify SAP OData error response into retryable or non-retryable categories."""
    code = "UNKNOWN"
    message = "Unknown error"

    if isinstance(response_data, dict):
        err_obj = response_data.get("error", {})
        code = err_obj.get("code", "UNKNOWN")
        msg_val = err_obj.get("message", {})
        if isinstance(msg_val, dict):
            message = msg_val.get("value", str(msg_val))
        elif isinstance(msg_val, str):
            message = msg_val
    elif isinstance(response_data, str) and response_data:
        message = response_data

    # Retryable: Locks (423), Rate limit (429), Server unavailable/timeout (502, 503, 504), transient lock
    if status_code in (423, 429, 502, 503, 504) or "LOCK" in code or "LOCKED" in code:
        return SapErrorClassification(
            is_retryable=True,
            code=code,
            message=message,
            status_code=status_code,
        )

    # Non-retryable: Bad Request (400), Not Found (404), Conflict (409), Precondition Failed (412), Unprocessable (422)
    return SapErrorClassification(
        is_retryable=False,
        code=code,
        message=message,
        status_code=status_code,
    )


class SapCsrfError(RuntimeError):
    """SAP did not issue a CSRF token; posting must not proceed with a fabricated one."""


def _odata_d(res: httpx.Response) -> dict[str, Any]:
    """Return the OData V2 ``d`` object of a response, validating its shape."""
    body = res.json()
    if not isinstance(body, dict):
        raise ValueError(f"SAP response is not a JSON object (HTTP {res.status_code})")
    d = body.get("d", {})
    if not isinstance(d, dict):
        raise ValueError(f"SAP response 'd' is not an object (HTTP {res.status_code})")
    return d


class SapWarehouseAdapter:
    """OData client adapter for SAP warehouse logistics services."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        sap_client: str = "100",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sap_client = sap_client
        self.timeout_s = timeout_s
        self.client = http_client or httpx.Client(timeout=timeout_s)
        self.csrf_token: str | None = None
        self.session_cookie: str | None = None

    def fetch_csrf_token(self) -> str:
        """Fetch CSRF token via GET with x-csrf-token: fetch."""
        headers = {
            "x-csrf-token": "fetch",
            "sap-client": self.sap_client,
            "Accept": "application/json",
        }
        res = self.client.get(
            f"{self.base_url}/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/$metadata",
            headers=headers,
        )
        token = res.headers.get("x-csrf-token")
        if token and token.lower() != "fetch":
            self.csrf_token = token
            # Capture cookies if any
            if "set-cookie" in res.headers:
                self.session_cookie = res.headers.get("set-cookie")
            return str(token)
        # Never fabricate a CSRF token (C1, review 3.13): a real S/4 rejects it with 403 and
        # the failure would surface far from its cause.
        raise SapCsrfError(f"SAP did not return x-csrf-token (HTTP {res.status_code})")

    def _get_headers(self, require_csrf: bool = False, etag: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "sap-client": self.sap_client,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if require_csrf:
            if not self.csrf_token:
                self.fetch_csrf_token()
            if self.csrf_token:
                headers["x-csrf-token"] = self.csrf_token
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        if etag:
            headers["If-Match"] = etag
        return headers

    def probe_document_status(self, doc_type: str, doc_key: str) -> dict[str, Any]:
        """Pre-post probe via document flow to verify if document is already posted."""
        if doc_type in ("IBD", "inbound_delivery"):
            endpoint = f"{self.base_url}/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader('{doc_key}')"
        elif doc_type in ("OBD", "outbound_delivery"):
            endpoint = f"{self.base_url}/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/A_OutbDeliveryHeader('{doc_key}')"
        elif doc_type in ("PI", "physinv"):
            endpoint = f"{self.base_url}/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/A_PhysInventoryDocHeader('{doc_key}')"
        else:
            endpoint = f"{self.base_url}/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader('{doc_key}')"

        res = self.client.get(endpoint, headers=self._get_headers())
        if res.status_code == 200:
            return _odata_d(res)
        return {}

    def patch_delivery_item(
        self,
        service_name: str,
        delivery_document: str,
        item_no: str,
        data: dict[str, Any],
        etag: str,
    ) -> dict[str, Any]:
        """Execute PATCH with mandatory If-Match ETag check."""
        entity = "A_InbDeliveryItem" if "INBOUND" in service_name else "A_OutbDeliveryItem"
        url = f"{self.base_url}/sap/opu/odata/sap/{service_name}/{entity}(DeliveryDocument='{delivery_document}',DeliveryDocumentItem='{item_no}')"
        headers = self._get_headers(require_csrf=True, etag=etag)
        res = self.client.patch(url, headers=headers, json=data)
        if res.status_code in (200, 204):
            return _odata_d(res) if res.content else {"status": "ok"}

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"SAP PATCH failed [{classification.code}]: {classification.message} (status={res.status_code})")

    def post_goods_receipt(self, delivery_document: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Execute PostGoodsReceipt function import."""
        url = f"{self.base_url}/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt"
        headers = self._get_headers(require_csrf=True)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        res = self.client.post(url, headers=headers, params={"DeliveryDocument": delivery_document})
        if res.status_code == 200:
            return _odata_d(res)

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"PostGoodsReceipt failed [{classification.code}]: {classification.message} (status={res.status_code})")

    def post_goods_issue(
        self, delivery_document: str, allow_partial: bool = False, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Execute PostGoodsIssue function import."""
        url = f"{self.base_url}/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/PostGoodsIssue"
        headers = self._get_headers(require_csrf=True)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        res = self.client.post(
            url,
            headers=headers,
            params={"DeliveryDocument": delivery_document, "AllowPartial": allow_partial},
        )
        if res.status_code == 200:
            return _odata_d(res)

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"PostGoodsIssue failed [{classification.code}]: {classification.message} (status={res.status_code})")

    def reverse_goods_issue(self, delivery_document: str) -> dict[str, Any]:
        """Execute ReverseGoodsIssue function import."""
        url = f"{self.base_url}/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/ReverseGoodsIssue"
        headers = self._get_headers(require_csrf=True)
        res = self.client.post(url, headers=headers, params={"DeliveryDocument": delivery_document})
        if res.status_code == 200:
            return _odata_d(res)

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"ReverseGoodsIssue failed [{classification.code}]: {classification.message} (status={res.status_code})")

    def post_differences(
        self, pi_document: str, fiscal_year: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Execute PostDifferences function import."""
        url = f"{self.base_url}/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/PostDifferences"
        headers = self._get_headers(require_csrf=True)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        res = self.client.post(
            url,
            headers=headers,
            params={"PhysicalInventoryDocument": pi_document, "FiscalYear": fiscal_year},
        )
        if res.status_code == 200:
            return _odata_d(res)

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"PostDifferences failed [{classification.code}]: {classification.message} (status={res.status_code})")

    def cancel_material_document(
        self, material_document: str, fiscal_year: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Execute Cancel material document function import."""
        url = f"{self.base_url}/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel"
        headers = self._get_headers(require_csrf=True)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        res = self.client.post(
            url,
            headers=headers,
            params={"MaterialDocument": material_document, "MaterialDocumentYear": fiscal_year},
        )
        if res.status_code == 200:
            return _odata_d(res)

        classification = classify_sap_error(res.status_code, res.json() if res.content else None)
        raise RuntimeError(f"Cancel failed [{classification.code}]: {classification.message} (status={res.status_code})")

    @staticmethod
    def render_golden_payload(command_name: str, **kwargs: Any) -> str:
        """Render deterministic JSON payload for golden contract verification."""
        canonical_dict = {"command": command_name, "params": kwargs}
        return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
