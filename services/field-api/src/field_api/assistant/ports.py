"""Seams to track S (M3 contract §7): code lookup and sandbox items, received by injection.

Track S owns ``field_api.codes`` and ``field_api.sandbox``; only ``get_ports`` imports them. Track S
implements exactly these signatures (``field_api.codes.resolve.resolve_code`` and
``field_api.sandbox.service.add_item``); they are wired in ``get_ports`` (integration, 31 Oct 2026). A port left
``None`` (tests) means: "what is this" answers from the task lines only and no sandbox add is offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypedDict

from field_api.auth.jwt import Principal
from field_api.codes.resolve import resolve_code
from field_api.sandbox.service import add_item


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


@dataclass(frozen=True)
class AssistantPorts:
    resolve_code: CodeResolver | None = None
    add_item: SandboxItems | None = None


def get_ports() -> AssistantPorts:
    """FastAPI dependency: track S's code lookup and sandbox item service (M3 contract section 7)."""
    return AssistantPorts(resolve_code=_resolve_code, add_item=add_item)


def _resolve_code(principal: Principal, site_id: str, code: str) -> CodeLookup:
    """Track S's lookup, copied field by field into this module's CodeLookup (same shape, separate types)."""
    r = resolve_code(principal, site_id, code)
    m = r["material"]
    material: MaterialRef | None = (
        None if m is None else {"material": m["material"], "description": m["description"], "uom": m["uom"]}
    )
    return {"code": r["code"], "kind": r["kind"], "material": material, "bin": r["bin"], "site_mode": r["site_mode"]}
