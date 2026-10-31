"""Seams to track S (M3 contract §7): code lookup, sandbox items and (M4) new sandbox receipts and counts,
received by injection.

Track S owns ``field_api.codes`` and ``field_api.sandbox``; only ``get_ports`` imports them. Track S
implements exactly these signatures (``field_api.codes.resolve.resolve_code`` and
``field_api.sandbox.service.add_item``); they are wired in ``get_ports`` (integration, 31 Oct 2026). A port left
``None`` (tests) means: "what is this" answers from the task lines only and no sandbox add is offered.

M4 (owner's field test, 31 Oct 2026: after the home receipt and count the site had no open jobs and nothing
offered new work): ``create_receipt`` and ``create_count`` are ``field_api.sandbox.service.create_receipt`` and
``create_count`` with the signatures below (they raise FieldError FIELD-SBX-403-PRODUCTION on a production site).
Left ``None``, the assistant does not offer "new home receipt" / "count a shelf".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypedDict

from field_api.auth.jwt import Principal
from field_api.codes.resolve import resolve_code
from field_api.sandbox.service import add_item, create_count, create_receipt


class MaterialRef(TypedDict):
    material: str
    description: str | None
    uom: str | None


class CodeLookup(TypedDict):
    code: str
    kind: str  # 'material' | 'bin' | 'serial' | 'unknown'
    material: MaterialRef | None
    bin: str | None
    site_mode: str  # 'production' | 'sandbox'


class SandboxItemResult(TypedDict):
    line_id: str
    material: str
    created_material: bool


class CodeResolver(Protocol):
    def __call__(self, principal: Principal, site_id: str, code: str) -> CodeLookup: ...


class SandboxItems(Protocol):
    """Adds an item line to a sandbox receive or count task. Raises FieldError FIELD-SBX-403-PRODUCTION on a
    production site."""

    def __call__(self, principal: Principal, task_id: str, code: str, description: str,
                 qty: Decimal | None, idempotency_key: str) -> SandboxItemResult: ...


class SandboxTaskResult(TypedDict):
    task_id: str
    ref_doc_no: str


class SandboxReceipts(Protocol):
    """Creates an open, empty home receipt (an inbound delivery in the ERP and its receive task)."""

    def __call__(self, principal: Principal, site_id: str) -> SandboxTaskResult: ...


class SandboxCounts(Protocol):
    """Creates an empty blind count of one bin of a sandbox site (scanned boxes become its lines)."""

    def __call__(self, principal: Principal, site_id: str, storage_bin: str) -> SandboxTaskResult: ...


@dataclass(frozen=True)
class AssistantPorts:
    resolve_code: CodeResolver | None = None
    add_item: SandboxItems | None = None
    create_receipt: SandboxReceipts | None = None
    create_count: SandboxCounts | None = None


def get_ports() -> AssistantPorts:
    """FastAPI dependency: track S's code lookup and sandbox service (M3 contract section 7, M4 new tasks)."""
    return AssistantPorts(resolve_code=_resolve_code, add_item=add_item, create_receipt=_create_receipt,
                          create_count=_create_count)


def _create_receipt(principal: Principal, site_id: str) -> SandboxTaskResult:
    r = create_receipt(principal, site_id)
    return {"task_id": r["task_id"], "ref_doc_no": r["ref_doc_no"]}


def _create_count(principal: Principal, site_id: str, storage_bin: str) -> SandboxTaskResult:
    r = create_count(principal, site_id, storage_bin)
    return {"task_id": r["task_id"], "ref_doc_no": r["ref_doc_no"]}


def _resolve_code(principal: Principal, site_id: str, code: str) -> CodeLookup:
    """Track S's lookup, copied field by field into this module's CodeLookup (same shape, separate types)."""
    r = resolve_code(principal, site_id, code)
    m = r["material"]
    material: MaterialRef | None = (
        None if m is None else {"material": m["material"], "description": m["description"], "uom": m["uom"]}
    )
    return {"code": r["code"], "kind": r["kind"], "material": material, "bin": r["bin"], "site_mode": r["site_mode"]}
