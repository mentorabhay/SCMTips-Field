"""Core role keys -> Field roles (M4 F7; the core's reply TO_FIELD section 2, decision (b)).

The core's app token carries the core's own role keys in ``roles`` (it keeps one role vocabulary and never issues
Field role names). /v1/auth/exchange maps them to Field roles with this table:

=========================  ======================
core role                  Field role
=========================  ======================
``approver``               ``field.supervisor``   (holds field.assistant.use, so spoken briefs work)
``procurement``            ``field.operator``     (the core has no "warehouse operator" role)
``ops_lead``, ``team_lead`` ``field.supervisor``
``org_admin``              ``field.admin``
``integration``            ``field.integration``
``planner``, ``analyst``   ``field.viewer``       (the other core roles known today)
=========================  ======================

Setting ``FIELD_CORE_ROLE_MAP`` (optional): a JSON object, or the path of a JSON file holding one, that maps a core
role key to a Field role or a list of Field roles. It is laid over the default table: a key given replaces that
key's entry, ``[]`` removes it, and keys not given keep the default. Every value must be a Field role
(field_api.auth.permissions.ROLE_PERMISSIONS); a broken setting is a configuration error and refuses every core
sign-in (fail closed, logged by name only).

Field role names in ``roles`` keep working unchanged (fake-core dev tokens, QR pairing). A role that is neither a
Field role nor in the table is ignored; when nothing maps, the exchange refuses with FIELD-AUTH-403-NO-FIELD-ROLE.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from field_api.auth.permissions import ROLE_PERMISSIONS

ENV_VAR = "FIELD_CORE_ROLE_MAP"

DEFAULT_CORE_ROLE_MAP: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "approver": ("field.supervisor",),
    "procurement": ("field.operator",),
    "ops_lead": ("field.supervisor",),
    "team_lead": ("field.supervisor",),
    "org_admin": ("field.admin",),
    "integration": ("field.integration",),
    "planner": ("field.viewer",),
    "analyst": ("field.viewer",),
})


class RoleMapError(ValueError):
    """FIELD_CORE_ROLE_MAP is not a valid mapping (the message names the problem, never a secret)."""


@dataclass(frozen=True)
class MappedRoles:
    field_roles: list[str]  # in token order, de-duplicated
    core_roles: list[str]  # the core role keys that mapped, in token order
    ignored: list[str]  # neither a Field role nor in the table


def _values(key: str, raw: Any) -> tuple[str, ...]:
    vals = [raw] if isinstance(raw, str) else raw
    if not isinstance(vals, list) or not all(isinstance(v, str) for v in vals):
        raise RoleMapError(f"{ENV_VAR}: '{key}' must map to a Field role or a list of Field roles")
    bad = [v for v in vals if v not in ROLE_PERMISSIONS]
    if bad:
        raise RoleMapError(f"{ENV_VAR}: '{key}' maps to unknown Field role(s) {bad}")
    return tuple(dict.fromkeys(str(v) for v in vals))


def parse_core_role_map(raw: str | None) -> Mapping[str, tuple[str, ...]]:
    """The effective table for a setting value: empty -> the default; ``{...}`` -> JSON; else a file path."""
    text = (raw or "").strip()
    if not text:
        return DEFAULT_CORE_ROLE_MAP
    if not text.startswith("{"):
        try:
            text = Path(text).read_text(encoding="utf-8")
        except OSError as e:
            raise RoleMapError(f"{ENV_VAR}: cannot read the file it names ({type(e).__name__})") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise RoleMapError(f"{ENV_VAR}: not valid JSON") from None
    if not isinstance(data, dict):
        raise RoleMapError(f"{ENV_VAR}: must be a JSON object of core role -> Field role")
    table = dict(DEFAULT_CORE_ROLE_MAP)
    for key, val in data.items():
        if not isinstance(key, str) or not key.strip():
            raise RoleMapError(f"{ENV_VAR}: core role keys must be non-empty strings")
        vals = _values(key, val)
        if vals:
            table[key] = vals
        else:
            table.pop(key, None)
    return MappingProxyType(table)


def core_role_map() -> Mapping[str, tuple[str, ...]]:
    """The table from the environment, read at call time (so a changed .env.local applies on restart)."""
    return parse_core_role_map(os.getenv(ENV_VAR))


def map_roles(roles: list[str], table: Mapping[str, tuple[str, ...]]) -> MappedRoles:
    field: dict[str, None] = {}
    core: list[str] = []
    ignored: list[str] = []
    for r in roles:
        if r in ROLE_PERMISSIONS:
            field[r] = None
        elif r in table:
            field.update(dict.fromkeys(table[r]))
            core.append(r)
        else:
            ignored.append(r)
    return MappedRoles(list(field), core, ignored)
