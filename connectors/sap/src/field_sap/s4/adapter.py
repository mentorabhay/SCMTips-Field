"""S/4HANA OData v2 Adapter Stub (Task T1.058 / FR1.011).

Implements ErpPort signatures, CSRF token handling and error parsing skeleton;
operations raise NotImplementedError('S4 adapter: <op> not implemented in F0').
Config schema for base URL, client, auth method documented.

M3: the sandbox operations (ErpSandboxPort) are not SAP capabilities. This adapter refuses them with
ErpError(BUSINESS, FIELD_SANDBOX_NOT_SAP): a sandbox site never creates materials or deliveries in S/4.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import structlog

from field_sap.ports.erp_port import (
    SANDBOX_NOT_SAP,
    ErpError,
    ErpErrorKind,
    ErpPostingRequest,
    ErpResult,
    MaterialDocument,
    MaterialPage,
    PurchaseOrderLine,
    SandboxDelivery,
    SandboxDeliveryItem,
    SandboxMaterial,
    SandboxPlant,
    StockLine,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class S4Config:
    """Configuration schema for live SAP S/4HANA connectivity."""

    base_url: str
    client: str = "100"
    auth_method: str = "basic"  # 'basic', 'x509', or 'oauth2_saml_bearer'
    username: str | None = None
    password_secret_ref: str | None = None
    client_certificate_ref: str | None = None
    timeout_seconds: float = 30.0
    verify_ssl: bool = True


class S4ODataAdapter:
    """S/4HANA production adapter stub for Phase 1."""

    def __init__(self, config: S4Config) -> None:
        self.config = config
        self._csrf_token: str | None = None

    async def list_materials(
        self,
        plant: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> MaterialPage:
        raise NotImplementedError("S4 adapter: list_materials not implemented in F0")

    async def find_by_idempotency_key(self, idempotency_key: str) -> ErpResult | None:
        raise NotImplementedError("S4 adapter: find_by_idempotency_key not implemented in F0")

    async def update_inbound_delivery_item(self, req: ErpPostingRequest) -> ErpResult:
        # M5 (UNVERIFIED): a receipt with flagged units carries QualityQuantity / QualityStorageLocation. A real S/4
        # system has no such item fields: it would need a delivery item split (one item per storage location) or
        # the item's stock type quality inspection (A_InbDeliveryItem.StockType / InspectionLot), to be designed
        # and proven on a real system before this adapter posts them. erp-sim's shape: erp_sim/services/inbound.py.
        raise NotImplementedError("S4 adapter: update_inbound_delivery_item not implemented in F0")

    async def post_inbound_goods_receipt(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: post_inbound_goods_receipt not implemented in F0")

    async def cancel_material_document(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: cancel_material_document not implemented in F0")

    async def pick_outbound_delivery(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: pick_outbound_delivery not implemented in F0")

    async def post_outbound_goods_issue(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: post_outbound_goods_issue not implemented in F0")

    async def create_physical_inventory_doc(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: create_physical_inventory_doc not implemented in F0")

    async def enter_physical_inventory_count(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError(
            "S4 adapter: enter_physical_inventory_count not implemented in F0"
        )

    async def post_physical_inventory_differences(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError(
            "S4 adapter: post_physical_inventory_differences not implemented in F0"
        )

    async def post_transfer_posting(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: post_transfer_posting not implemented in F0")

    async def post_initial_stock_entry(self, req: ErpPostingRequest) -> ErpResult:
        raise NotImplementedError("S4 adapter: post_initial_stock_entry not implemented in F0")

    # --- ErpReadPort (M4 F4): UNVERIFIED, no S/4 system reachable --------------------------------------
    async def read_material_document(self, document_number: str, fiscal_year: str) -> MaterialDocument:
        raise NotImplementedError("S4 adapter: read_material_document not implemented in F0")

    async def read_stock(self, material: str, plant: str, storage_location: str | None = None) -> Decimal:
        raise NotImplementedError("S4 adapter: read_stock not implemented in F0")

    async def list_stock(self, plant: str) -> list[StockLine]:
        raise NotImplementedError("S4 adapter: list_stock not implemented (UNVERIFIED, M4 Q10)")

    async def list_purchase_order_items(self, plant: str) -> list[PurchaseOrderLine]:
        raise NotImplementedError("S4 adapter: list_purchase_order_items not implemented (UNVERIFIED, M4 Q10)")

    # --- ErpSandboxPort: refused, these are not SAP capabilities (M3 contract section 3) --------------
    @staticmethod
    def _not_sap(op: str) -> ErpError:
        return ErpError(kind=ErpErrorKind.BUSINESS, code=SANDBOX_NOT_SAP, retryable=False,
                        message=f"{op} is a sandbox (simulator) operation, not an SAP capability")

    async def create_sandbox_material(self, plant: str, description: str, base_uom: str,
                                      barcode: str) -> SandboxMaterial:
        raise self._not_sap("create_sandbox_material")

    async def create_sandbox_inbound_delivery(self, plant: str, storage_location: str, supplier: str,
                                              simulated: bool = False) -> SandboxDelivery:
        raise self._not_sap("create_sandbox_inbound_delivery")

    async def add_sandbox_inbound_delivery_item(self, delivery_document: str, material: str, quantity: str,
                                                uom: str, idempotency_key: str) -> SandboxDeliveryItem:
        raise self._not_sap("add_sandbox_inbound_delivery_item")

    async def ensure_sandbox_plant(self, plant: str, name: str,
                                   storage_locations: Sequence[tuple[str, str]]) -> SandboxPlant:
        raise self._not_sap("ensure_sandbox_plant")
