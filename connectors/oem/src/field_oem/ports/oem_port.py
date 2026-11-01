"""OemPort: a maker's public seal keys and its unit registry (docs/design/M5_C3_CONTRACT.md section 5).

- ``knows(oem)``: the maker ids this adapter can answer for (the payload's ``oem`` picks the maker).
- ``keys(oem, refresh=False)``: the maker's Ed25519 public keys; adapters may cache them (``refresh`` forces a fetch,
  used once when a code names an unknown ``kid``, for key rotation).
- ``check_unit(oem, serial, checker, area)``: the unit's history and the atomic first-check claim, in one call.
  ``checker`` is pseudonymous (32 hex); ``area`` is coarse (city level) or None.

Errors: ``OemNotConfigured`` (no maker is configured for this adapter: the real-OEM adapter of this build),
``OemUnavailable`` (the maker did not answer: network, timeout, 5xx, a malformed answer, no key published),
``UnitNotFound`` (the registry has no such serial). Field turns all of them into CANNOT_VERIFY, never an HTTP error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

EVENT_TYPES = ("manufactured", "shipped_to_seller", "delivered", "activated", "returned", "refurbished")


class OemError(Exception):
    code = "OEM_ERROR"


class OemNotConfigured(OemError):
    code = "not_configured"


class OemUnavailable(OemError):
    code = "unavailable"


class UnitNotFound(OemError):
    code = "unknown_unit"


@dataclass(frozen=True)
class OemKey:
    kid: str
    public: bytes  # raw 32-byte Ed25519 public key


@dataclass(frozen=True)
class OemKeySet:
    oem: str
    name: str
    keys: tuple[OemKey, ...]
    sample: bool = False

    def find(self, kid: str) -> OemKey | None:
        return next((k for k in self.keys if k.kid == kid), None)


@dataclass(frozen=True)
class UnitEvent:
    type: str
    at: date
    area: str | None = None


@dataclass(frozen=True)
class UnitHistory:
    oem: str
    serial: str
    sku: str
    events: tuple[UnitEvent, ...]


@dataclass(frozen=True)
class FirstCheck:
    first: bool  # this call made the first check of the serial
    at: datetime  # when the first check happened (this one or an earlier one)
    area: str | None
    same_checker: bool  # the first check was made by this checker


@dataclass(frozen=True)
class UnitCheck:
    unit: UnitHistory
    first_check: FirstCheck


@dataclass(frozen=True)
class SeedUnit:
    """A unit for the C3 scenarios (M5_C3_CONTRACT.md section 6): its history and the label sheet's caption."""

    serial: str
    sku: str
    sealed_at: date
    events: tuple[UnitEvent, ...]
    scenario: str | None = None
    title: str | None = None
    copies: int = 1


@runtime_checkable
class OemSeedPort(Protocol):
    """Seeding the C3 scenarios: a simulator capability, never a maker's (the real-OEM adapter refuses)."""

    def seed_unit(self, unit: SeedUnit) -> str: ...  # the unit's signed code

    def seed_forgery(self, serial: str, sku: str, sealed_at: date, scenario: str | None, title: str | None) -> str: ...

    def labels_html(self) -> str: ...


@runtime_checkable
class OemPort(Protocol):
    def knows(self, oem: str) -> bool: ...

    def keys(self, oem: str, *, refresh: bool = False) -> OemKeySet: ...

    def check_unit(self, oem: str, serial: str, checker: str, area: str | None) -> UnitCheck: ...
