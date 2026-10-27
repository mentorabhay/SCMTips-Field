"""S/4HANA OData v2 Adapter Stub (Task T1.058 / FR1.011).

Implements ErpPort signatures, CSRF token handling and error parsing skeleton;
operations raise NotImplementedError('S4 adapter: <op> not implemented in F0').
Config schema for base URL, client, auth method documented.
"""

from dataclasses import dataclass

import structlog

from field_sap.ports.erp_port import (
    ErpPostingRequest,
    ErpResult,
    MaterialPage,
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
