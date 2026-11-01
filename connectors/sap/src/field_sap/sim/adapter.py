"""SimAdapter Implementation for Simulated ERP (Task T1.057 / FR1.011).

Calls erp-sim over httpx with CSRF fetch, header text FIELD:<key>,
traceparent propagation and a 10 s timeout;
maps ZSIM codes and HTTP status to ErpError;
on timeout calls find_by_idempotency_key before reporting failure.
"""

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog

from field_sap.ports.erp_port import (
    ErpError,
    ErpErrorKind,
    ErpPostingRequest,
    ErpResult,
    MaterialBarcode,
    MaterialDocument,
    MaterialDocumentItem,
    MaterialItem,
    MaterialPage,
    PurchaseOrderLine,
    SandboxDelivery,
    SandboxDeliveryItem,
    SandboxMaterial,
    SandboxPlant,
    SandboxStorageLocation,
    StockLine,
)

logger = structlog.get_logger(__name__)

DEFAULT_ERPSIM_URL = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")
# The simulator's admin token for its /_sim/sandbox routes (M3). Read by name; erp-sim has the same dev default.
SIM_ADMIN_TOKEN_ENV = "ERPSIM_ADMIN_TOKEN"


def _odata_d(resp: httpx.Response) -> dict[str, Any]:
    """OData V2 ``d`` object of an erp-sim response; a malformed body is a hard error, never empty data."""
    body = resp.json()
    d = body.get("d") if isinstance(body, dict) else None
    if not isinstance(d, dict):
        raise ErpError(kind=ErpErrorKind.BUSINESS, code="ZSIM_BAD_RESPONSE",
                       message=f"erp-sim response has no OData 'd' object (HTTP {resp.status_code})")
    return d


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
        """Look the key up by header text FIELD:<key> (used after a timeout before reporting failure)."""
        url = "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader"
        params = {"$filter": f"MaterialDocumentHeaderText eq 'FIELD:{idempotency_key}'"}
        async with self._get_client() as client:
            try:
                resp = await client.get(url, params=params, headers={"sap-client": self.sap_client})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
        if resp.status_code != 200:
            raise self._parse_error(resp)
        results = _odata_d(resp).get("results") or []
        if not results:
            return None
        doc = results[0]
        return ErpResult(
            idempotency_key=idempotency_key,
            document_number=str(doc["MaterialDocument"]),
            fiscal_year=str(doc["MaterialDocumentYear"]),
            document_family="MaterialDocument",
            posted_at=datetime.now(UTC),
            raw_response=doc,
        )

    async def list_materials(
        self,
        plant: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> MaterialPage:
        """Page A_ProductPlant for a plant; the cursor is the $skip offset of the next page."""
        skip = int(cursor) if cursor else 0
        url = "/sap/opu/odata/sap/API_PRODUCT_SRV/A_ProductPlant"
        params = {"$filter": f"Plant eq '{plant}'", "$top": str(limit), "$skip": str(skip), "$inlinecount": "allpages",
                  "$expand": "to_ProductUnitsOfMeasureEAN"}
        async with self._get_client() as client:
            try:
                resp = await client.get(url, params=params, headers={"sap-client": self.sap_client})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
        if resp.status_code != 200:
            raise self._parse_error(resp)
        d = _odata_d(resp)
        rows = d.get("results") or []
        total = int(d.get("__count") or 0)
        items = tuple(
            MaterialItem(
                material_no=str(r["Product"]),
                description=str(r.get("ProductDescription") or ""),
                plant=str(r.get("Plant") or plant),
                base_uom=str(r.get("BaseUnit") or "EA"),
                barcodes=tuple(
                    MaterialBarcode(barcode=str(e["ProductStandardID"]), uom=str(e.get("AlternativeUnit") or "EA"),
                                    is_main=bool(e.get("IsMainGlobalTradeItemNumber")))
                    for e in (r.get("to_ProductUnitsOfMeasureEAN") or {}).get("results") or []
                    if e.get("ProductStandardID")
                ),
            )
            for r in rows
        )
        nxt = skip + len(items)
        return MaterialPage(items=items, next_cursor=str(nxt) if items and nxt < total else None, total_count=total)

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
            body: dict[str, str] = {"ActualDeliveryQuantity": str(qty)}
            if req.header_data.get("SoftPegging"):  # M3 sandbox: the delivery quantity becomes the counted one
                body["OriginalDeliveryQuantity"] = str(qty)
            if req.header_data.get("QualityQuantity"):  # M5: flagged units of this item go to the quality area
                # erp-sim's YY1_ extension fields (erp_sim/services/inbound.py docstring): S/4 would split the item or
                # post stock type quality inspection instead; UNVERIFIED against a real system.
                body["YY1_QualityQuantity"] = str(req.header_data["QualityQuantity"])
                body["YY1_QualityStorageLocation"] = str(req.header_data.get("QualityStorageLocation") or "")
            try:
                resp = await client.patch(url, headers=headers, json=body)
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

    async def post_initial_stock_entry(self, req: ErpPostingRequest) -> ErpResult:
        """Movement 561 (initial entry of stock balances) as an API_MATERIAL_DOCUMENT_SRV deep insert."""
        sloc = str(req.header_data.get("StorageLocation") or "")
        body = {
            "GoodsMovementCode": "05",
            "PostingDate": req.posting_date,
            "MaterialDocumentHeaderText": f"FIELD:{req.idempotency_key}",
            "YY1_FieldSandbox": bool(req.header_data.get("Sandbox")),
            "YY1_FieldSimulated": bool(req.header_data.get("Simulated")),
            "to_MaterialDocumentItem": [
                {"Material": it["Material"], "Plant": req.plant, "StorageLocation": sloc, "GoodsMovementType": "561",
                 "QuantityInEntryUnit": str(it["QuantityInEntryUnit"]), "EntryUnit": it.get("EntryUnit", "EA")}
                for it in req.items
            ],
        }
        url = "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader"
        async with self._get_client() as client:
            try:
                resp = await client.post(url, json=body, headers={"sap-client": self.sap_client,
                                                                   "Idempotency-Key": req.idempotency_key})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                existing = await self.find_by_idempotency_key(req.idempotency_key)
                if existing:
                    return existing
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
            if resp.status_code not in (200, 201):
                raise self._parse_error(resp)
            data = _odata_d(resp)
            return ErpResult(
                idempotency_key=req.idempotency_key,
                document_number=str(data.get("MaterialDocument", "")),
                fiscal_year=str(data.get("MaterialDocumentYear", "")),
                document_family="InitialStockEntry",
                posted_at=datetime.now(UTC),
                raw_response=data,
            )

    # --- ErpSandboxPort (M3 contract section 3): erp-sim admin routes, not SAP capabilities ------------
    def _admin_headers(self) -> dict[str, str]:
        return {"sap-client": self.sap_client,
                "X-Sim-Admin-Token": os.getenv(SIM_ADMIN_TOKEN_ENV, "dev-sim-admin-token")}

    async def _sandbox_post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        headers = self._admin_headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with self._get_client() as client:
            try:
                resp = await client.post(f"/_sim/sandbox/{path}", json=body, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
        if resp.status_code not in (200, 201):
            raise self._parse_error(resp)
        return _odata_d(resp)

    async def create_sandbox_material(self, plant: str, description: str, base_uom: str,
                                      barcode: str) -> SandboxMaterial:
        d = await self._sandbox_post("materials", {"Plant": plant, "Description": description[:40],
                                                   "BaseUnit": base_uom, "Barcode": barcode})
        return SandboxMaterial(material_no=str(d["Product"]), description=str(d.get("ProductDescription") or ""),
                               base_uom=str(d.get("BaseUnit") or base_uom), barcode=str(d.get("ProductStandardID") or barcode),
                               created=bool(d.get("Created")))

    async def create_sandbox_inbound_delivery(self, plant: str, storage_location: str, supplier: str,
                                              simulated: bool = False) -> SandboxDelivery:
        d = await self._sandbox_post("inbound-deliveries", {"Plant": plant, "StorageLocation": storage_location,
                                                            "Supplier": supplier, "Simulated": simulated})
        return SandboxDelivery(delivery_document=str(d["DeliveryDocument"]), last_change=d.get("LastChangeDateTime"))

    async def add_sandbox_inbound_delivery_item(self, delivery_document: str, material: str, quantity: str,
                                                uom: str, idempotency_key: str) -> SandboxDeliveryItem:
        d = await self._sandbox_post(f"inbound-deliveries/{delivery_document}/items",
                                     {"Material": material, "DeliveryQuantity": quantity, "DeliveryQuantityUnit": uom},
                                     idempotency_key)
        return SandboxDeliveryItem(delivery_document=str(d["DeliveryDocument"]), item_no=str(d["DeliveryDocumentItem"]),
                                   last_change=d.get("LastChangeDateTime"))

    async def ensure_sandbox_plant(self, plant: str, name: str,
                                   storage_locations: Sequence[tuple[str, str]]) -> SandboxPlant:
        d = await self._sandbox_post("plants", {"Plant": plant, "Name": name[:40], "StorageLocations": [
            {"StorageLocation": code, "Name": sl_name[:40]} for code, sl_name in storage_locations]})
        return SandboxPlant(plant=str(d["Plant"]), name=str(d.get("Name") or ""), created=bool(d.get("Created")),
                            storage_locations=tuple(
                                SandboxStorageLocation(storage_location=str(s["StorageLocation"]),
                                                       name=str(s.get("Name") or ""), created=bool(s.get("Created")))
                                for s in d.get("StorageLocations") or []))

    # --- ErpReadPort (M4 F4): what the goods-receipt feed rows are read from ----------------------------
    async def _get_d(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        async with self._get_client() as client:
            try:
                resp = await client.get(url, params=params, headers={"sap-client": self.sap_client})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ErpError(kind=ErpErrorKind.TIMEOUT, message=f"ERP timeout: {e}", retryable=True) from e
        if resp.status_code != 200:
            raise self._parse_error(resp)
        return _odata_d(resp)

    async def read_material_document(self, document_number: str, fiscal_year: str) -> MaterialDocument:
        """A_MaterialDocumentHeader(...)?$expand=to_MaterialDocumentItem, as S/4 serves it."""
        d = await self._get_d(
            "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/"
            f"A_MaterialDocumentHeader(MaterialDocument='{document_number}',MaterialDocumentYear='{fiscal_year}')",
            {"$expand": "to_MaterialDocumentItem"},
        )
        items = tuple(
            MaterialDocumentItem(
                item=str(it.get("MaterialDocumentItem") or ""),
                material=str(it["Material"]),
                plant=str(it.get("Plant") or ""),
                storage_location=str(it.get("StorageLocation") or ""),
                quantity=Decimal(str(it.get("QuantityInEntryUnit") or "0")),
                unit=str(it.get("EntryUnit") or "EA"),
                movement_type=str(it.get("GoodsMovementType") or ""),
                purchase_order=str(it.get("PurchaseOrder") or ""),
                purchase_order_item=str(it.get("PurchaseOrderItem") or ""),
            )
            for it in (d.get("to_MaterialDocumentItem") or {}).get("results") or []
        )
        return MaterialDocument(
            document_number=str(d.get("MaterialDocument") or document_number),
            fiscal_year=str(d.get("MaterialDocumentYear") or fiscal_year),
            posting_date=str(d.get("PostingDate") or "")[:10],
            items=items,
            sandbox=bool(d.get("YY1_FieldSandbox")),
            simulated=bool(d.get("YY1_FieldSimulated")),
        )

    async def read_stock(self, material: str, plant: str, storage_location: str | None = None) -> Decimal:
        """Sum of unrestricted stock (InventoryStockType 01) in API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod."""
        flt = f"Material eq '{material}' and Plant eq '{plant}'"
        if storage_location:
            flt += f" and StorageLocation eq '{storage_location}'"
        d = await self._get_d("/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod", {"$filter": flt})
        return sum(
            (Decimal(str(r.get("MatlWrhsStkQtyInMatlBaseUnit") or "0")) for r in d.get("results") or []
             if str(r.get("InventoryStockType") or "01") == "01"),
            Decimal("0"),
        )

    async def _pages(self, url: str, flt: str, page: int = 500) -> list[dict[str, Any]]:
        """Every result of a paged list read ($top / $skip), in the ERP's order."""
        out: list[dict[str, Any]] = []
        skip = 0
        while True:
            d = await self._get_d(url, {"$filter": flt, "$top": str(page), "$skip": str(skip)})
            rows = [r for r in d.get("results") or [] if isinstance(r, dict)]
            out += rows
            if len(rows) < page:
                return out
            skip += page

    async def list_stock(self, plant: str) -> list[StockLine]:
        """A_MatlStkInAcctMod, Plant and stock type 01: unrestricted stock per material and storage location."""
        rows = await self._pages("/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
                                 f"Plant eq '{plant}' and InventoryStockType eq '01'")
        return [
            StockLine(material=str(r["Material"]), plant=str(r.get("Plant") or plant),
                      storage_location=str(r.get("StorageLocation") or ""),
                      quantity=Decimal(str(r.get("MatlWrhsStkQtyInMatlBaseUnit") or "0")),
                      unit=str(r.get("MaterialBaseUnit") or "EA"))
            for r in rows if str(r.get("InventoryStockType") or "01") == "01"
        ]

    async def list_purchase_order_items(self, plant: str) -> list[PurchaseOrderLine]:
        """A_PurchaseOrderItem?$filter=Plant eq '<p>' (erp-sim: with Supplier, the schedule line's date and YY1_
        received quantity, last receipt date, supply status and lane)."""
        rows = await self._pages("/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderItem",
                                 f"Plant eq '{plant}'")
        return [
            PurchaseOrderLine(
                purchase_order=str(r["PurchaseOrder"]), item=str(r.get("PurchaseOrderItem") or ""),
                material=str(r["Material"]), plant=str(r.get("Plant") or plant),
                storage_location=str(r.get("StorageLocation") or ""),
                order_qty=Decimal(str(r.get("OrderQuantity") or "0")),
                received_qty=Decimal(str(r.get("YY1_ReceivedQuantity") or "0")),
                unit=str(r.get("PurchaseOrderQuantityUnit") or "EA"),
                delivery_date=str(r.get("ScheduleLineDeliveryDate") or "")[:10], supplier=str(r.get("Supplier") or ""),
                status=str(r.get("YY1_SupplyStatus") or "open"), lane=str(r.get("YY1_LaneCode") or ""),
                last_receipt_date=str(r.get("YY1_LastGoodsReceiptDate") or "")[:10],
            )
            for r in rows
        ]
