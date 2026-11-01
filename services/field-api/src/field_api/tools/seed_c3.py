"""C3 scenario seed (M5-T06, docs/design/M5_C3_CONTRACT.md section 6): the five seal-label scenarios of the SAMPLE
maker Kestrel Optics (SAMPLE) in the OEM simulator, through the OEM port's seed capability (FIELD_OEM_ADAPTER=sim:
the simulator's admin API with ERPSIM_ADMIN_TOKEN; FIELD_OEM_ADAPTER=oem refuses, a real maker is never seeded).

| Label | Scenario | Registry |
| L1 | genuine new | manufactured, shipped_to_seller, delivered |
| L2 | returned, resold as new | + activated 12 Oct, returned 20 Oct, shipped_to_seller again 25 Oct |
| L3 | counterfeit | none: a code signed with a forger's key, on the label sheet only |
| L4 | cloned code | genuine new, printed twice (copies 2): the first check claims it |
| L5 | tampered seal | genuine new; the label is drawn taped over and the sheet asks for real tape |

Idempotent: units are upserted (their nonce, so every printed label, stays valid) and their first checks reset, so a
re-run restarts every scenario. ``--labels-out PATH`` also writes the printable label sheet (GET /_oem/labels).
Exit 0 when every scenario is seeded, 1 otherwise (the reason on stderr). Run where field-api runs::

    python -m field_api.tools.seed_c3 [--oem-url URL] [--labels-out var/c3_labels.html]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TextIO

from field_oem.ports.oem_port import OemError, OemSeedPort, SeedUnit, UnitEvent

from field_api.authenticity.oem import sim_url

D = date
SHIPPED = (UnitEvent("manufactured", D(2026, 9, 28)), UnitEvent("shipped_to_seller", D(2026, 10, 2)),
           UnitEvent("delivered", D(2026, 10, 8)))
UNITS = (
    SeedUnit("KSO-SAMPLE-0001", "KSO-BIN-842", D(2026, 9, 28), SHIPPED, "L1", "Genuine new"),
    SeedUnit("KSO-SAMPLE-0002", "KSO-BIN-842", D(2026, 9, 28),
             (*SHIPPED, UnitEvent("activated", D(2026, 10, 12)), UnitEvent("returned", D(2026, 10, 20)),
              UnitEvent("shipped_to_seller", D(2026, 10, 25))), "L2", "Returned, resold as new"),
    SeedUnit("KSO-SAMPLE-0004", "KSO-SCOPE-60", D(2026, 9, 29), SHIPPED, "L4", "Cloned code", copies=2),
    SeedUnit("KSO-SAMPLE-0005", "KSO-LENS-35", D(2026, 9, 30), SHIPPED, "L5", "Tampered seal"),
)
FORGERY = ("KSO-SAMPLE-0003", "KSO-BIN-842", D(2026, 9, 28), "L3", "Counterfeit (not in the registry)")
EXPECT = (("L1", "GENUINE_NEW"), ("L2", "RETURNED_REFURBISHED"), ("L3", "LIKELY_COUNTERFEIT"),
          ("L4", "GENUINE_NEW first, CANNOT_VERIFY for a second checker"), ("L5", "GENUINE_NEW, tamper true with a photo"))


@dataclass(frozen=True)
class Seeded:
    codes: dict[str, str]  # scenario -> its code


def get_seed_port(url: str | None = None) -> OemSeedPort:
    """The seed capability of the configured OEM port (FIELD_OEM_ADAPTER), as field_api.authenticity.oem chooses."""
    if (os.getenv("FIELD_OEM_ADAPTER", "sim").strip().lower() or "sim") == "sim":
        from field_oem.sim.adapter import SimOemAdapter

        return SimOemAdapter(url or sim_url())
    from field_oem.real.adapter import RealOemAdapter

    return RealOemAdapter()


def seed(port: OemSeedPort) -> Seeded:
    codes = {str(u.scenario): port.seed_unit(u) for u in UNITS}
    serial, sku, sealed, scenario, title = FORGERY
    codes[scenario] = port.seed_forgery(serial, sku, sealed, scenario, title)
    return Seeded(dict(sorted(codes.items())))


def main(argv: Sequence[str] | None = None, out: TextIO | None = None, port: OemSeedPort | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m field_api.tools.seed_c3", description=__doc__.split("\n")[0])
    ap.add_argument("--oem-url", default=None, help="the OEM simulator (default FIELD_OEM_SIM_URL / FIELD_ERP_SIM_URL)")
    ap.add_argument("--labels-out", default=None, help="write the printable label sheet here")
    a = ap.parse_args(argv)
    w = out or sys.stdout
    p = port or get_seed_port(a.oem_url)
    try:
        seeded = seed(p)
        page = p.labels_html() if a.labels_out else None
    except OemError as e:
        print(f"FAIL c3 seed: {e}", file=sys.stderr)
        return 1
    for scenario, expect in EXPECT:
        print(f"OK {scenario}: {expect} ({len(seeded.codes[scenario])}-character code)", file=w)
    if page is not None and a.labels_out:
        path = Path(a.labels_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8")
        print(f"OK labels: {path} (print at 100 %, cut along the dashed lines)", file=w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
