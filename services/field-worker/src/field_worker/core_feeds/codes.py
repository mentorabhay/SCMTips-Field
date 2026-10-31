"""ERP codes -> the core's codes for the feed rows (M4 F4; handover 01a "Codes").

The core expects its own item codes (e.g. ``RM-307``) and location codes (e.g. ``PLANT-GOA``), upper case
(exchange contract "Values"). When erp-sim is seeded from the core's export (``stack seed-core-export``) the ERP
already uses the core's codes and no mapping is needed. Until then, FIELD_CORE_CODE_MAP names a JSON file:

    {"materials": {"SAMPLE-MAT-0001": "RM-307"},
     "locations": {"1010": "PLANT-GOA", "1010/101A": "PLANT-GOA-RM"}}

A location key ``<plant>/<storage location>`` wins over ``<plant>``; with a storage-location key the on-hand sent is
that storage location's, otherwise the plant total. Codes without an entry are sent as the ERP has them, upper-cased.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CodeMap:
    materials: MappingProxyType[str, str] = field(default_factory=lambda: MappingProxyType({}))
    locations: MappingProxyType[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def item(self, material: str) -> str:
        return self.materials.get(material, material).upper()

    def location(self, plant: str, storage_location: str) -> tuple[str, bool]:
        """(core location code, True when it names one storage location rather than the plant)."""
        key = f"{plant}/{storage_location}"
        if storage_location and key in self.locations:
            return self.locations[key].upper(), True
        return self.locations.get(plant, plant).upper(), False


def _str_map(raw: Any, what: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in raw.items()):
        raise ValueError(f"FIELD_CORE_CODE_MAP: '{what}' must map codes to non-empty codes")
    return {str(k): str(v) for k, v in raw.items()}


def load_code_map(path: str) -> CodeMap:
    """The mapping file, or the identity map when ``path`` is empty. A broken file is an error (fail loudly)."""
    if not path:
        return CodeMap()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("FIELD_CORE_CODE_MAP must hold a JSON object")
    return CodeMap(MappingProxyType(_str_map(data.get("materials"), "materials")),
                   MappingProxyType(_str_map(data.get("locations"), "locations")))
