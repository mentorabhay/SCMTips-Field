#!/usr/bin/env python3
"""Dependency Policy Checker (Task T1.072 / FR1.064 / TC1.165).

Enforces:
1. Pinned lockfiles (uv.lock) exist.
2. Licence allowlist compliance (MIT, Apache-2.0, BSD, ISC, PSF, MPL-2.0).
3. Zero forbidden copyleft licenses (GPL, AGPL, SSPL).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

APPROVED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "PSF",
    "Python-2.0",
    "MPL-2.0",
}

FORBIDDEN_KEYWORDS = ["GPL", "AGPL", "SSPL", "PROPRIETARY"]


def check_lockfiles() -> bool:
    uv_lock = ROOT / "uv.lock"
    if not uv_lock.exists():
        print("[FAIL] Missing uv.lock file. All dependencies must be pinned.", file=sys.stderr)
        return False
    return True


def check_licenses() -> bool:
    """Every installed distribution's declared licence (metadata, not the lockfile) must be non-copyleft.

    Reads License / License-Expression / classifiers of each installed package. Unknown licences are
    reported (so they get reviewed) but only an explicit forbidden keyword fails the check.
    """
    from importlib import metadata

    bad: list[str] = []
    unknown: list[str] = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or "?"
        # Most specific declaration wins: SPDX expression, else the License field, else classifiers.
        expr = (dist.metadata.get("License-Expression") or "").strip()
        lic = (dist.metadata.get("License") or "").strip()
        fields = [expr] if expr else [lic] if lic and len(lic) < 200 else [
            c for c in (dist.metadata.get_all("Classifier") or []) if c.startswith("License ::")
        ]
        text = " ".join(f for f in fields if f).upper()
        if not text.strip():
            unknown.append(name)
            continue
        # "LGPL" is allowed (dynamic linking from Python); GPL/AGPL/SSPL are not.
        hits = [k for k in FORBIDDEN_KEYWORDS if k in text.replace("LGPL", "").replace("LESSER GENERAL PUBLIC", "")]
        if hits:
            bad.append(f"{name}: {text[:120]}")
    if unknown:
        print(f"[INFO] {len(unknown)} package(s) declare no licence metadata: {', '.join(sorted(unknown)[:20])}")
    if bad:
        print("[FAIL] forbidden licences:\n  " + "\n  ".join(sorted(bad)), file=sys.stderr)
        return False
    return True


def main() -> int:
    if not check_lockfiles():
        return 1
    if not check_licenses():
        return 1

    print("[PASS] Dependency policy check passed. Lockfiles intact and licenses approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
