"""Alembic Round-Trip Verification Job (Task T1.007)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_service(service_name: str) -> None:
    svc_dir = ROOT / "services" / service_name
    print(f"Testing Alembic round-trip for {service_name}...")
    # Check current
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=svc_dir,
        check=True,
    )
    # Check downgrade base
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=svc_dir,
        check=True,
    )
    # Check re-upgrade head
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=svc_dir,
        check=True,
    )
    print(f"Alembic round-trip for {service_name} SUCCESSFUL.")


def main() -> None:
    test_service("field-api")
    test_service("erp-sim")
    print("ALL ALEMBIC ROUND-TRIPS PASSED.")


if __name__ == "__main__":
    main()
