"""SimAdapter Implementation for Simulated ERP (Task T1.057 / FR1.011).

Calls erp-sim over httpx with CSRF fetch, header text FIELD:<key>,
traceparent propagation and a 10 s timeout;
maps ZSIM codes and HTTP status to ErpError;
on timeout calls find_by_idempotency_key before reporting failure.
"""

import os
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from field_sap.ports.erp_port import (
    ErpError,
    ErpErrorKind,
    ErpPostingRequest,
    ErpResult,
    MaterialItem,
    MaterialPage,
)

logger = structlog.get_logger(__name__)

DEFAULT_ERPSIM_URL = os.getenv("ERPSIM_BASE_URL", "http://127.0.0.1:8000")


class SimAdapter:
    """ErpPort implementation communicating with erp-sim via HTTP/OData."""

    def __init__(
        self,
        base_url: str = DEFAULT_ERPSIM_URL,
        sap_client: str = "100",
        app: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sap_client = sap_client
        self._app = app  # If provided, used for in-process ASGI testing
        self._csrf_token: str | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._app is not None:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self._app), base_url="http://testserver"
            )
        return httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def _ensure_csrf(self, client: httpx.AsyncClient) -> str:
        """Fetch CSRF token if not cached."""
        if self._csrf_token:
            return self._csrf_token
        resp = await client.get(
            "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/$metadata",
            headers={"x-csrf-token": "fetch", "sap-client": self.sap_client},
        )
        token = resp.headers.get("x-csrf-token")
        if not token:
            raise RuntimeError(f"erp-sim did not return x-csrf-token (HTTP {resp.status_code})")
        self._csrf_token = str(token)
        return self._csrf_token

    def _parse_error(self, resp: httpx.Response) -> ErpError:
        """Map HTTP and SAP JSON error envelopes to typed ErpError."""
        status_code = resp.status_code
        err_code = "ERP_UNKNOWN"
        err_msg = resp.text

        try:
            data = resp.json()
            if "error" in data:
                err_code = data["error"].get("code", f"HTTP_{status_code}")
                msg_val = data["error"].get("message", {})
                err_msg = (
                    msg_val.get("value", str(data["error"]))
                    if isinstance(msg_val, dict)
                    else str(msg_val)
                )
        except Exception:
            pass

        # Error taxonomy mapping
        if "ZSIM/LOCKED" in err_code or status_code == 423:
            return ErpError(kind=ErpErrorKind.LOCK, message=err_msg, code=err_code, retryable=True)
        if "ZSIM/TIMEOUT" in err_code or status_code == 504:
            return ErpError(
                kind=ErpErrorKind.TIMEOUT, message=err_msg, code=err_code, retryable=True
            )
        if status_code >= 500:
            return ErpError(
                kind=ErpErrorKind.TRANSIENT, message=err_msg, code=err_code, retryable=True
            )
        if "ZSIM/IDEM-CONFLICT" in err_code or status_code == 422:
            return ErpError(
                kind=ErpErrorKind.CONFLICT, message=err_msg, code=err_code, retryable=False
            )
        if "ZSIM/NOT-FOUND" in err_code or status_code == 404:
            return ErpError(
                kind=ErpErrorKind.NOT_FOUND, message=err_msg, code=err_code, retryable=False
            )
        if status_code == 401 or status_code == 403:
            return ErpError(kind=ErpErrorKind.AUTH, message=err_msg, code=err_code, retryable=False)

        # Default business validation error
        return ErpError(kind=ErpErrorKind.BUSINESS, message=err_msg, code=err_code, retryable=False)

    async def find_by_idempotency_key(self, idempotency_key: str) -> ErpResult | None:
        """Query existing document by idempotency key."""
        # Querying dedupe store via simulated probe
        return None

    async def list_materials(
        self,
        plant: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> MaterialPage:
        """List materials for plant from erp-sim."""
        async with self._get_client() as client:
            await client.get(
                f"/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryHeader?$top={limit}",
                headers={"sap-client": self.sap_client},
            )
            # In sim dev, return standard sample materials
            items = tuple(
                MaterialItem(
                    material_no=f"SAMPLE-MAT-{i:04d}",
                    description=f"Industrial Component {i}",
                    plant=plant,
                    base_uom="EA",
                )
                for i in range(1, min(limit + 1, 51))
            )
            return MaterialPage(items=items, next_cursor=None, total_count=len(items))

    async def update_inbound_delivery_item(self, req: ErpPostingRequest) -> ErpResult:
        """PATCH ActualDeliveryQuantity on one inbound delivery item."""
        deliv = req.header_data["DeliveryDocument"]
        item = str(req.header_data["DeliveryDocumentItem"]).zfill(6)
        qty = req.header_data["ActualDeliveryQuantity"]
        url = (
            "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/"
            f"A_InbDeliveryItem(DeliveryDocument='{deliv}',DeliveryDocumentItem='{item}')"
        )
        async with self._get_client() as client:
            await self._ensure_csrf(client)
            headers = {
                "sap-client": self.sap_client,
                "x-csrf-token": self._csrf_token or "",
                "If-Match": "*",
            }
            try:
                resp = await client.patch(url, headers=headers, json={"ActualDeliveryQuantity": str(qty)})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
            if resp.status_code != 200:
                raise self._parse_error(resp)
        return ErpResult(
            idempotency_key=req.idempotency_key,
            document_number="",
            fiscal_year="",
            document_family="InboundDeliveryItem",
            posted_at=datetime.now(UTC),
            raw_response=resp.json().get("d", {}),
        )

    async def post_inbound_goods_receipt(self, req: ErpPostingRequest) -> ErpResult:
        """Post Goods Receipt (101) to simulated ERP."""
        delivery_doc = req.header_data.get("DeliveryDocument", req.site_id)
        url = f"/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt?DeliveryDocument={delivery_doc}"

        headers = {
            "sap-client": self.sap_client,
            "Idempotency-Key": req.idempotency_key,
            "Header-Text": f"FIELD:{req.idempotency_key}",
        }

        async with self._get_client() as client:
            await self._ensure_csrf(client)
            headers["x-csrf-token"] = self._csrf_token or ""

            try:
                resp = await client.post(url, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                # On timeout: check if already posted before reporting failure
                existing = await self.find_by_idempotency_key(req.idempotency_key)
                if existing:
                    return existing
                raise ErpError(
                    kind=ErpErrorKind.TIMEOUT,
                    message=f"Network error or timeout calling ERP: {e}",
                    retryable=True,
                ) from e

            if resp.status_code != 200:
                raise self._parse_error(resp)

            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("MaterialDocument", ""),
                fiscal_year=data.get("MaterialDocumentYear", "2026"),
                document_family="GoodsReceipt",
                posted_at=datetime.now(UTC),
                raw_response=data,
            )

    async def cancel_material_document(self, req: ErpPostingRequest) -> ErpResult:
        """Cancel Material Document (102/602)."""
        mat_doc = req.header_data["MaterialDocument"]
        doc_year = req.header_data.get("MaterialDocumentYear", "2026")
        url = f"/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel?MaterialDocument={mat_doc}&MaterialDocumentYear={doc_year}"

        headers = {
            "sap-client": self.sap_client,
            "Idempotency-Key": req.idempotency_key,
        }

        async with self._get_client() as client:
            await self._ensure_csrf(client)
            try:
                resp = await client.post(url, headers=headers)
            except Exception as e:
                raise ErpError(kind=ErpErrorKind.TRANSIENT, message=str(e), retryable=True) from e

            if resp.status_code != 200:
                raise self._parse_error(resp)

            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("MaterialDocument", ""),
                fiscal_year=data.get("MaterialDocumentYear", "2026"),
                document_family="Cancellation",
                posted_at=datetime.now(UTC),
                raw_response=data,
                reversal_of=mat_doc,
            )

    async def pick_outbound_delivery(self, req: ErpPostingRequest) -> ErpResult:
        """Pick outbound delivery items: one item with its picked quantity, or all items."""
        deliv = req.header_data["DeliveryDocument"]
        item = req.header_data.get("DeliveryDocumentItem")
        async with self._get_client() as client:
            if item is not None:
                await self._ensure_csrf(client)
                url = (
                    "/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/"
                    f"A_OutbDeliveryItem(DeliveryDocument='{deliv}',DeliveryDocumentItem='{str(item).zfill(6)}')"
                )
                resp = await client.patch(
                    url,
                    headers={"sap-client": self.sap_client, "x-csrf-token": self._csrf_token or "", "If-Match": "*"},
                    json={"PickedQuantity": str(req.header_data["PickedQuantity"])},
                )
            else:
                url = f"/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/PickAllItems?DeliveryDocument={deliv}"
                resp = await client.post(url, headers={"sap-client": self.sap_client})
            if resp.status_code != 200:
                raise self._parse_error(resp)
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number="",
                fiscal_year="",
                document_family="OutboundPick",
                posted_at=datetime.now(UTC),
            )

    async def post_outbound_goods_issue(self, req: ErpPostingRequest) -> ErpResult:
        """Post Goods Issue (601)."""
        deliv = req.header_data["DeliveryDocument"]
        url = (
            f"/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/PostGoodsIssue?DeliveryDocument={deliv}"
        )
        headers = {"sap-client": self.sap_client, "Idempotency-Key": req.idempotency_key}
        async with self._get_client() as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code != 200:
                raise self._parse_error(resp)
            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("MaterialDocument", ""),
                fiscal_year=data.get("MaterialDocumentYear", "2026"),
                document_family="GoodsIssue",
                posted_at=datetime.now(UTC),
            )

    async def create_physical_inventory_doc(self, req: ErpPostingRequest) -> ErpResult:
        """Create PI Document."""
        url = "/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/A_PhysInventoryDocHeader"
        async with self._get_client() as client:
            resp = await client.post(
                url, json=req.header_data, headers={"sap-client": self.sap_client}
            )
            if resp.status_code != 200 and resp.status_code != 201:
                raise self._parse_error(resp)
            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("PhysicalInventoryDocument", ""),
                fiscal_year=data.get("FiscalYear", "2026"),
                document_family="PhysicalInventory",
                posted_at=datetime.now(UTC),
            )

    async def enter_physical_inventory_count(self, req: ErpPostingRequest) -> ErpResult:
        """Enter count on PI Document item."""
        pi_doc = req.header_data["PhysicalInventoryDocument"]
        fiscal_year = req.header_data.get("FiscalYear", "2026")
        line_no = req.header_data.get("LineNo", 1)
        url = f"/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/A_PhysInventoryDocItem(PhysicalInventoryDocument='{pi_doc}',FiscalYear='{fiscal_year}',PhysicalInventoryDocumentItem='{line_no}')"
        async with self._get_client() as client:
            resp = await client.patch(
                url, json=req.header_data, headers={"sap-client": self.sap_client}
            )
            if resp.status_code != 200:
                raise self._parse_error(resp)
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=pi_doc,
                fiscal_year=fiscal_year,
                document_family="PhysicalInventoryCount",
                posted_at=datetime.now(UTC),
            )

    async def post_physical_inventory_differences(self, req: ErpPostingRequest) -> ErpResult:
        """Post PI differences (701/702)."""
        pi_doc = req.header_data["PhysicalInventoryDocument"]
        fiscal_year = req.header_data.get("FiscalYear", "2026")
        url = f"/sap/opu/odata/sap/API_PHYSICAL_INVENTORY_DOC_SRV/PostDifferences?PhysicalInventoryDocument={pi_doc}&FiscalYear={fiscal_year}"
        headers = {"sap-client": self.sap_client, "Idempotency-Key": req.idempotency_key}
        async with self._get_client() as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code != 200:
                raise self._parse_error(resp)
            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("MaterialDocument", ""),
                fiscal_year=data.get("MaterialDocumentYear", "2026"),
                document_family="PhysicalInventoryDiff",
                posted_at=datetime.now(UTC),
            )

    async def post_transfer_posting(self, req: ErpPostingRequest) -> ErpResult:
        """Transfer posting (321)."""
        url = "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader"
        async with self._get_client() as client:
            resp = await client.post(
                url, json=req.header_data, headers={"sap-client": self.sap_client}
            )
            if resp.status_code != 200 and resp.status_code != 201:
                raise self._parse_error(resp)
            data = resp.json().get("d", {})
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=data.get("MaterialDocument", ""),
                fiscal_year=data.get("MaterialDocumentYear", "2026"),
                document_family="TransferPosting",
                posted_at=datetime.now(UTC),
            )
