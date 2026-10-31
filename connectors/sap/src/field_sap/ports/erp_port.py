"""ErpPort Protocol and Data Structures (Task T1.056 / FR1.011).

Defines typing.Protocol ErpPort with methods for the eight document families
plus find_by_idempotency_key and list_materials; frozen dataclasses for requests
and ErpResult; ErpError with kind LOCK, TRANSIENT, TIMEOUT, BUSINESS, AUTH,
NOT_FOUND, CONFLICT and retryable flag.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ErpErrorKind(StrEnum):
    LOCK = "LOCK"  # Enqueue lock contention
    TRANSIENT = "TRANSIENT"  # Network / connection reset
    TIMEOUT = "TIMEOUT"  # Gateway / server timeout
    BUSINESS = "BUSINESS"  # Validation / posting error (e.g. posting period closed)
    AUTH = "AUTH"  # Bad credentials / token expired
    NOT_FOUND = "NOT_FOUND"  # Document or material not found
    CONFLICT = "CONFLICT"  # Version mismatch / duplicate posting


@dataclass(frozen=True)
class ErpError(Exception):
    kind: ErpErrorKind
    message: str
    code: str = "ERP_ERROR"
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.kind.value}] {self.code}: {self.message} (retryable={self.retryable})"


@dataclass(frozen=True)
class MaterialBarcode:
    """One barcode of a material (SAP MEAN / A_ProductUnitsOfMeasureEAN), M3."""

    barcode: str
    uom: str = "EA"
    is_main: bool = False


@dataclass(frozen=True)
class MaterialItem:
    material_no: str
    description: str
    plant: str
    base_uom: str
    storage_locations: tuple[str, ...] = ()
    source_hash: str = ""
    deleted_in_erp: bool = False
    barcodes: tuple[MaterialBarcode, ...] = ()


@dataclass(frozen=True)
class MaterialPage:
    items: tuple[MaterialItem, ...]
    next_cursor: str | None = None
    total_count: int = 0


@dataclass(frozen=True)
class ErpPostingRequest:
    idempotency_key: str
    doc_family: str
    site_id: str
    plant: str
    posting_date: str
    header_data: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ErpResult:
    idempotency_key: str
    document_number: str
    fiscal_year: str
    document_family: str
    posted_at: datetime
    raw_response: dict[str, Any] = field(default_factory=dict)
    reversal_of: str | None = None


@dataclass(frozen=True)
class SandboxMaterial:
    """A material the sandbox created for a barcode (or the one the barcode already belongs to)."""

    material_no: str
    description: str
    base_uom: str
    barcode: str
    created: bool


@dataclass(frozen=True)
class SandboxDelivery:
    delivery_document: str
    last_change: str | None = None


@dataclass(frozen=True)
class SandboxDeliveryItem:
    delivery_document: str
    item_no: str
    last_change: str | None = None


SANDBOX_NOT_SAP = "FIELD_SANDBOX_NOT_SAP"


@runtime_checkable
class ErpSandboxPort(Protocol):
    """Sandbox (home / training) operations, M3 contract section 3.

    Not SAP capabilities: only the simulator adapter implements them. An S/4 adapter refuses every call
    with ErpError(kind=BUSINESS, code=SANDBOX_NOT_SAP).
    """

    async def create_sandbox_material(self, plant: str, description: str, base_uom: str,
                                      barcode: str) -> SandboxMaterial:
        """A new material for this barcode, or the material the barcode already belongs to."""
        ...

    async def create_sandbox_inbound_delivery(self, plant: str, storage_location: str, supplier: str,
                                              simulated: bool = False) -> SandboxDelivery:
        """An open inbound delivery with no items, marked sandbox."""
        ...

    async def add_sandbox_inbound_delivery_item(self, delivery_document: str, material: str, quantity: str,
                                                uom: str, idempotency_key: str) -> SandboxDeliveryItem:
        """The next item of a sandbox delivery; the same key returns the first item."""
        ...


@runtime_checkable
class ErpPort(Protocol):
    """Abstract port for all ERP interactions (SAP S/4HANA or erp-sim)."""

    async def list_materials(
        self,
        plant: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> MaterialPage:
        """Page materials for a given plant."""
        ...

    async def find_by_idempotency_key(self, idempotency_key: str) -> ErpResult | None:
        """Query existing posting by client idempotency key."""
        ...

    async def update_inbound_delivery_item(self, req: ErpPostingRequest) -> ErpResult:
        """Set ActualDeliveryQuantity on one inbound delivery item before goods receipt."""
        ...

    async def post_inbound_goods_receipt(self, req: ErpPostingRequest) -> ErpResult:
        """Post Goods Receipt for Inbound Delivery (Movement 101)."""
        ...

    async def cancel_material_document(self, req: ErpPostingRequest) -> ErpResult:
        """Cancel Material Document (Movement 102/602)."""
        ...

    async def pick_outbound_delivery(self, req: ErpPostingRequest) -> ErpResult:
        """Update picked quantities on outbound delivery."""
        ...

    async def post_outbound_goods_issue(self, req: ErpPostingRequest) -> ErpResult:
        """Post Goods Issue for Outbound Delivery (Movement 601)."""
        ...

    async def create_physical_inventory_doc(self, req: ErpPostingRequest) -> ErpResult:
        """Create Physical Inventory Document."""
        ...

    async def enter_physical_inventory_count(self, req: ErpPostingRequest) -> ErpResult:
        """Enter count results into Physical Inventory Document."""
        ...

    async def post_physical_inventory_differences(self, req: ErpPostingRequest) -> ErpResult:
        """Post PI differences (Movements 701/702)."""
        ...

    async def post_transfer_posting(self, req: ErpPostingRequest) -> ErpResult:
        """Transfer posting (Movement 321 / 301)."""
        ...

    async def post_initial_stock_entry(self, req: ErpPostingRequest) -> ErpResult:
        """Initial entry of stock balances (Movement 561, GoodsMovementCode 05). items: Material,
        QuantityInEntryUnit, EntryUnit; header_data: StorageLocation, Sandbox, Simulated (M3)."""
        ...
