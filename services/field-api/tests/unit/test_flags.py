"""Unit tests for feature flags resolution and dependency (Task T1.077 / TC1.164)."""

import pytest
from field_api.auth.jwt import Principal
from field_api.errors import FieldError
from field_api.flags import (
    FLAG_ADDON_ENABLED,
    FLAG_GLASSES_ENABLED,
    is_flag_enabled,
    require_flag,
)


@pytest.mark.unit
def test_flags_default_off():
    assert is_flag_enabled("tenant-unlisted", FLAG_ADDON_ENABLED) is False
    assert is_flag_enabled("tenant-unlisted", FLAG_GLASSES_ENABLED) is False


@pytest.mark.unit
def test_flags_tenant_allowlist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIELD_TENANT_ALLOWLIST", "tenant-alpha, tenant-beta")
    assert is_flag_enabled("tenant-alpha", FLAG_ADDON_ENABLED) is True
    assert is_flag_enabled("tenant-beta", FLAG_ADDON_ENABLED) is True
    assert is_flag_enabled("tenant-gamma", FLAG_ADDON_ENABLED) is False


@pytest.mark.unit
def test_flags_overrides(monkeypatch: pytest.MonkeyPatch):
    # Global override
    monkeypatch.setenv("FIELD_FLAG_OVERRIDES", '{"field.glasses.enabled": true}')
    assert is_flag_enabled("any-tenant", FLAG_GLASSES_ENABLED) is True

    # Tenant-specific override
    monkeypatch.setenv(
        "FIELD_FLAG_OVERRIDES",
        '{"tenant-vip": {"field.glasses.enabled": true}, "tenant-regular": {"field.glasses.enabled": false}}',
    )
    assert is_flag_enabled("tenant-vip", FLAG_GLASSES_ENABLED) is True
    assert is_flag_enabled("tenant-regular", FLAG_GLASSES_ENABLED) is False


@pytest.mark.unit
def test_require_flag_dependency(monkeypatch: pytest.MonkeyPatch):
    dep = require_flag(FLAG_ADDON_ENABLED)
    principal = Principal(
        id="usr-1",
        tenant_id="tenant-blocked",
        roles=["field.operator"],
        permissions=["field.read"],
        site_ids=["*"],
    )

    with pytest.raises(FieldError) as exc:
        dep(principal)

    assert exc.value.code == "FIELD-FLAG-403-DISABLED"
    assert exc.value.status == 403

    # Now allowlist
    monkeypatch.setenv("FIELD_TENANT_ALLOWLIST", "tenant-blocked")
    res = dep(principal)
    assert res == principal
