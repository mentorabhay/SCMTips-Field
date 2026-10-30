"""Per-Tenant Feature Flags Architecture (Task T1.077 / ADR-0004 / TC1.164).

Resolves flags in order:
1. Core P13a (via CS-03 when available)
2. Process Environment Overrides (FIELD_FLAG_OVERRIDES JSON)
3. Tenant Allowlist (FIELD_TENANT_ALLOWLIST)
4. Default off (False)
"""

import json
import os
from collections.abc import Callable

from fastapi import Depends

from field_api.auth.jwt import Principal
from field_api.deps import require_principal
from field_api.errors import FieldError

FLAG_ADDON_ENABLED = "field.addon.enabled"
FLAG_GLASSES_ENABLED = "field.glasses.enabled"
FLAG_ERP_LIVE_POSTING = "field.erp.live_posting"
FLAG_CONSOLE_ENABLED = "field.console.enabled"

KNOWN_FLAGS = frozenset({
    FLAG_ADDON_ENABLED,
    FLAG_GLASSES_ENABLED,
    FLAG_ERP_LIVE_POSTING,
    FLAG_CONSOLE_ENABLED,
})


def is_flag_enabled(tenant_id: str, flag_key: str) -> bool:
    """Evaluate whether a feature flag is enabled for the specified tenant."""
    # 1. Environment Overrides (e.g. FIELD_FLAG_OVERRIDES='{"field.addon.enabled": true}'
    # or nested '{"<tenant_id>": {"field.addon.enabled": true}}')
    overrides_raw = os.getenv("FIELD_FLAG_OVERRIDES")
    if overrides_raw:
        try:
            overrides = json.loads(overrides_raw)
            if isinstance(overrides, dict):
                # Tenant-specific override
                if (
                    tenant_id in overrides
                    and isinstance(overrides[tenant_id], dict)
                    and flag_key in overrides[tenant_id]
                ):
                    return bool(overrides[tenant_id][flag_key])
                # Global override
                if flag_key in overrides:
                    return bool(overrides[flag_key])
        except Exception:
            pass

    # 2. Tenant Allowlist (e.g. FIELD_TENANT_ALLOWLIST="tenant-1,tenant-2,*")
    allowlist_raw = os.getenv("FIELD_TENANT_ALLOWLIST", "").strip()
    if allowlist_raw:
        allowed = [t.strip() for t in allowlist_raw.split(",") if t.strip()]
        if ("*" in allowed or tenant_id in allowed) and flag_key in (
            FLAG_ADDON_ENABLED,
            FLAG_CONSOLE_ENABLED,
        ):
            return True

    # 3. Default off
    return False


def require_flag(flag_key: str) -> Callable[[Principal], Principal]:
    """FastAPI dependency requiring a feature flag to be active for the caller's tenant."""

    def dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if not is_flag_enabled(principal.tenant_id, flag_key):
            raise FieldError(
                code="FIELD-FLAG-403-DISABLED",
                status=403,
                title="Feature Flag Disabled",
                detail=f"Feature flag '{flag_key}' is disabled for tenant '{principal.tenant_id}'.",
            )
        return principal

    return dependency
