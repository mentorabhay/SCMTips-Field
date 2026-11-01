"""OemPort for a real maker (FIELD_OEM_ADAPTER=oem).

No real maker signs its seals or opens its registry for this build, so there is nothing to call: every method
refuses with OemNotConfigured and Field answers CANNOT_VERIFY ``oem:not_configured`` (rule 2.4: an unavailable
third-party service sits behind the port and is never pretended). A maker integration replaces this class.
"""

from __future__ import annotations

from field_oem.ports.oem_port import OemKeySet, OemNotConfigured, UnitCheck

REFUSAL = "No maker is configured: a real OEM must sign its seals and open its registry (M5_C3_CONTRACT.md 9)."


class RealOemAdapter:
    def knows(self, oem: str) -> bool:
        return True  # any maker id: the refusal below is the honest answer for all of them

    def keys(self, oem: str, *, refresh: bool = False) -> OemKeySet:
        raise OemNotConfigured(REFUSAL)

    def check_unit(self, oem: str, serial: str, checker: str, area: str | None) -> UnitCheck:
        raise OemNotConfigured(REFUSAL)
