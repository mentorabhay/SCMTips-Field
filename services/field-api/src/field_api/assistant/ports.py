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

M5 (docs/design/M5_CONTRACT.md §1): ``create_case`` is ``field_api.vision.cases.create_case`` ("new grocery delivery",
"new pharmacy delivery"); left ``None``, those starters are not offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypedDict

from field_api.assistant.model import build_router
from field_api.auth.jwt import Principal
from field_api.claims.looks import db_get_look
from field_api.claims.voice import ClaimsVoice
from field_api.codes.resolve import resolve_code
from field_api.sandbox.service import add_item, create_count, create_receipt
from field_api.vision.cases import create_case


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


class SandboxCaseResult(TypedDict):
    task_id: str
    ref_doc_no: str
    object: str
    expected_units: int
    expected_pieces_per_unit: int | None


class SandboxCases(Protocol):
    """Creates an M5 test-case receipt (case 'grocery' or 'pharmacy') on a sandbox site."""

    def __call__(self, principal: Principal, site_id: str, case: str) -> SandboxCaseResult: ...


class Claims(Protocol):
    """M5 stream X (``field_api.claims.voice.ClaimsVoice``): supplier claims by voice. Every call raises FieldError
    with a speakable title when the claims service refuses (no look, nothing to claim, wrong state, too late)."""

    def create(self, principal: Principal, look_id: str) -> dict[str, Any]: ...

    def drafts(self, principal: Principal) -> list[dict[str, Any]]: ...

    def decide(self, principal: Principal, claim_id: str, version: int, decision: str,
               reason: str | None) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def confirm(self, principal: Principal, claim_id: str, version: int,
                words: str | None) -> tuple[dict[str, Any], dict[str, Any]]: ...


@dataclass(frozen=True)
class AssistantPorts:
    resolve_code: CodeResolver | None = None
    add_item: SandboxItems | None = None
    create_receipt: SandboxReceipts | None = None
    create_count: SandboxCounts | None = None
    create_case: SandboxCases | None = None
    claims: Claims | None = None  # M5: left None, the assistant answers that claims are not available


def get_ports() -> AssistantPorts:
    """FastAPI dependency: track S's code lookup and sandbox service (M3 contract section 7, M4 new tasks) and the
    M5 claims (stream X: the database look port and the Meta model router through the budget guard)."""
    return AssistantPorts(resolve_code=_resolve_code, add_item=add_item, create_receipt=_create_receipt,
                          create_count=_create_count, create_case=_create_case,
                          claims=ClaimsVoice(looks=db_get_look, router=build_router()))


def _create_case(principal: Principal, site_id: str, case: str) -> SandboxCaseResult:
    r = create_case(principal, site_id, case)
    return {"task_id": r["task_id"], "ref_doc_no": r["ref_doc_no"], "object": r["object"],
            "expected_units": r["expected_units"], "expected_pieces_per_unit": r["expected_pieces_per_unit"]}


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
