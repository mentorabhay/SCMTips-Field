#!/usr/bin/env python3
"""SCMTIPS Field - Comprehensive Typecheck Runner (Remediation Rule 2.2 / Task R0.4).

Executes:
1. mypy --strict on services/*/src, connectors/*/src, tools/
2. tsc --noEmit on apps/field-console and packages/*
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def get_tsc_command() -> list[str]:
    local_tsc_js = ROOT / "node_modules" / "typescript" / "bin" / "tsc"
    if local_tsc_js.exists():
        node_bin = shutil.which("node") or "node"
        return [node_bin, str(local_tsc_js)]

    # Check local node_modules .bin
    if os.name == "nt":
        local_cmd = ROOT / "node_modules" / ".bin" / "tsc.cmd"
        if local_cmd.exists():
            return [str(local_cmd)]
    else:
        local_sh = ROOT / "node_modules" / ".bin" / "tsc"
        if local_sh.exists():
            return [str(local_sh)]

    # Fallback to npx
    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "tsc"]
    return ["tsc"]


def run_mypy() -> int:
    print("=" * 60)
    print("Running mypy --strict across first-party Python codebase...")
    print("=" * 60)
    targets = [
        "services/field-api/src",
        "services/field-worker/src",
        "services/erp-sim/src",
        "connectors/sap-s4/src",
        "tools/",
    ]
    existing_targets = [t for t in targets if (ROOT / t).exists()]
    cmd = ["uv", "run", "mypy", "--strict"] + existing_targets
    print(f"Command: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode


def run_tsc() -> int:
    print("=" * 60)
    print("Running tsc --noEmit across TypeScript apps and packages...")
    print("=" * 60)
    tsc = get_tsc_command()
    rc = 0

    # 1. apps/field-console
    console_dir = ROOT / "apps" / "field-console"
    if (console_dir / "tsconfig.json").exists():
        print(f"Checking {console_dir}...")
        cmd = tsc + ["--noEmit", "-p", str(console_dir / "tsconfig.json")]
        proc = subprocess.run(cmd, cwd=console_dir)
        if proc.returncode != 0:
            rc = proc.returncode

    # 2. packages/*/tsconfig.json
    packages_dir = ROOT / "packages"
    if packages_dir.exists():
        for p_dir in packages_dir.iterdir():
            if p_dir.is_dir() and (p_dir / "tsconfig.json").exists():
                print(f"Checking {p_dir}...")
                cmd = tsc + ["--noEmit", "-p", str(p_dir / "tsconfig.json")]
                proc = subprocess.run(cmd, cwd=p_dir)
                if proc.returncode != 0:
                    rc = proc.returncode

    return rc


def main() -> int:
    mypy_rc = run_mypy()
    tsc_rc = run_tsc()
    if mypy_rc != 0 or tsc_rc != 0:
        print(f"\n[FAIL] Typecheck failed (mypy={mypy_rc}, tsc={tsc_rc})")
        return 1
    print("\n[PASS] All first-party Python and TypeScript passed strict type checking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
