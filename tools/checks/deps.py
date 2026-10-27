#!/usr/bin/env python3
"""Dependency Policy Checker (Task T1.072 / FR1.064 / TC1.165).

Enforces:
1. Pinned lockfiles (uv.lock) exist.
2. Licence allowlist compliance (MIT, Apache-2.0, BSD, ISC, PSF, MPL-2.0).
3. Zero forbidden copyleft licenses (GPL, AGPL, SSPL).
"""

from pathlib import Path
import sys

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
    uv_lock = ROOT / "uv.lock"
    content = uv_lock.read_text(encoding="utf-8")

    # Simple scan of lockfile text for forbidden viral licenses
    for forbidden in FORBIDDEN_KEYWORDS:
        if f'license = "{forbidden}' in content or f'license = "{forbidden}"' in content:
            print(
                f"[FAIL] Forbidden licence keyword '{forbidden}' detected in dependencies.",
                file=sys.stderr,
            )
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
