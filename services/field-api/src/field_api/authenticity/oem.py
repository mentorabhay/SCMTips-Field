"""The OEM port field-api uses, chosen by config (FIELD_OEM_ADAPTER), as sandbox/erp.py chooses the ERP adapter.

``sim`` (default): the OEM simulator at FIELD_OEM_SIM_URL (default FIELD_ERP_SIM_URL + "/_oem") through
field_oem's simulator adapter. ``oem``: the real-maker adapter, which refuses every call (no maker signs seals or
opens a registry for this build, rule 2.4) so every check answers CANNOT_VERIFY ``oem:not_configured``.

One adapter per process and configuration (``functools.lru_cache``) so its public-key cache is shared by requests;
the cache is only a cache of the maker's published keys (TTL FIELD_OEM_KEYS_TTL_S), never business state.

``checker_ref``: the pseudonymous checker id sent to the maker: the first 32 hex of HMAC-SHA256 with
FIELD_EVIDENCE_SECRET over CHECKER_DOMAIN + tenant + principal. The maker never sees a name, e-mail or device.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import os

from field_oem.ports.oem_port import OemPort

from field_api.secrets import required_secret

CHECKER_DOMAIN = b"scmtips-field/oem-checker/v1\n"
ADAPTER_ENV = "FIELD_OEM_ADAPTER"
SIM_URL_ENV = "FIELD_OEM_SIM_URL"


def sim_url() -> str:
    explicit = os.getenv(SIM_URL_ENV, "").strip()
    if explicit:
        return explicit.rstrip("/")
    return os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002").rstrip("/") + "/_oem"


@functools.lru_cache(maxsize=4)
def _port(kind: str, url: str) -> OemPort:
    if kind == "sim":
        from field_oem.sim.adapter import SimOemAdapter

        return SimOemAdapter(url)
    from field_oem.real.adapter import RealOemAdapter

    return RealOemAdapter()


def get_oem_port() -> OemPort:
    """FastAPI dependency: the configured OEM port (tests override it with field_oem_testing's double)."""
    kind = os.getenv(ADAPTER_ENV, "sim").strip().lower() or "sim"
    return _port("sim" if kind == "sim" else "oem", sim_url() if kind == "sim" else "")


def checker_ref(tenant_id: str, principal_id: str) -> str:
    key = required_secret("FIELD_EVIDENCE_SECRET").encode("utf-8")
    msg = CHECKER_DOMAIN + tenant_id.encode("utf-8") + b"\n" + principal_id.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]
