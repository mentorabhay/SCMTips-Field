"""Where field-api finds the SCMTIPS core (M4 contract section 2, F7; handover 01a).

Settings are read from the environment at call time (names only; values live in .env.local, A-02):

- ``FIELD_CORE_BASE_URL``: the core, default ``http://127.0.0.1:8011`` (the dev stack's stand-in core in
  tools/fake-core, a dev double). The real core API keeps port 8000 on the owner's PC (its reply TO_FIELD, 31 Oct):
  with ``FIELD_CORE_TARGET=core`` this is ``http://<the PC's LAN address>:8000``.
- ``FIELD_CORE_JWKS_URL``: default ``{FIELD_CORE_BASE_URL}/v1/core/jwks.json`` (the core's path, 01a).
- ``FIELD_CORE_DEVICE_STATUS_URL``: a template with ``{device_id}`` and ``{tenant_id}``, e.g.
  ``http://<LAN address>:8000/v1/core/devices/{device_id}/status?tenant_id={tenant_id}``. ``tenant_id`` comes from
  the token. Unset: today's behaviour, i.e. fake-core's ``{CORE_API_URL}/api/v1/devices/{device_id}/status``
  when ``CORE_API_URL`` is set, and no core device check when it is not.
"""

from __future__ import annotations

import os
from urllib.parse import quote

DEFAULT_CORE_BASE_URL = "http://127.0.0.1:8011"
# Sent on every call Field makes to the core: the core answers 403 on its state-changing routes and on the brief
# check without it (TO_FIELD section 1 item 6 and section 3). Harmless on the reads (JWKS, device status).
CORE_HEADERS: tuple[tuple[str, str], ...] = (("X-Requested-With", "lr"),)
CORE_JWKS_PATH = "/v1/core/jwks.json"
LEGACY_DEVICE_STATUS_PATH = "/api/v1/devices/{device_id}/status"  # tools/fake-core (P10 dev contract)


def core_base_url() -> str:
    return (os.getenv("FIELD_CORE_BASE_URL") or DEFAULT_CORE_BASE_URL).rstrip("/")


def core_jwks_url() -> str:
    return os.getenv("FIELD_CORE_JWKS_URL") or f"{core_base_url()}{CORE_JWKS_PATH}"


def device_status_template() -> tuple[str, bool] | None:
    """(template, is_core_template) or None when no core device check is configured.

    ``is_core_template`` is True for FIELD_CORE_DEVICE_STATUS_URL (the core's CS-04 path, which knows only the
    core device ids it bound to its tokens) and False for the legacy CORE_API_URL path of fake-core.
    """
    tpl = os.getenv("FIELD_CORE_DEVICE_STATUS_URL")
    if tpl:
        return tpl, True
    legacy = os.getenv("CORE_API_URL")
    if legacy:
        return legacy.rstrip("/") + LEGACY_DEVICE_STATUS_PATH, False
    return None


def render_device_status_url(template: str, device_id: str, tenant_id: str) -> str:
    """Fill the template; both values are URL-quoted. A template without ``{device_id}`` is a config error."""
    if "{device_id}" not in template:
        raise ValueError("FIELD_CORE_DEVICE_STATUS_URL must contain {device_id}")
    return template.replace("{device_id}", quote(device_id, safe="")).replace("{tenant_id}", quote(tenant_id, safe=""))
