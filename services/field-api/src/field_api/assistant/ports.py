"""Seams to track S (M3 contract §7): code lookup and sandbox items, received by injection.

The assistant must not import ``field_api.codes`` or ``field_api.sandbox`` (track S owns them). Track S
implements exactly these signatures (``field_api.codes.resolve.resolve_code`` and
``field_api.sandbox.service.add_item``); the integrator wires them in ``get_ports``. Until then both ports are
``None``: "what is this" answers from the task lines only and no sandbox add is offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypedDict

from field_api.auth.jwt import Principal


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
    """FastAPI dependency. Not wired on the assistant branch; the integrator returns track S's functions here."""
    return AssistantPorts()
