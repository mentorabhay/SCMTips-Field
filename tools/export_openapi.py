#!/usr/bin/env python3
"""Export FastAPI OpenAPI 3.1 Specification to packages/field-contract/openapi.json (Task T1.021)."""

import json
import sys
from pathlib import Path

# Add field-api/src to sys.path
ROOT = Path(__file__).resolve().parent.parent
for _src in ("services/field-api/src", "services/erp-sim/src", "services/field-worker/src", "connectors/sap/src"):
    sys.path.insert(0, str(ROOT / _src))

from erp_sim.app import app as erp_sim_app  # noqa: E402
from field_api.app import app  # noqa: E402

OUTPUT_PATH = ROOT / "packages" / "field-contract" / "openapi.json"
ERP_SIM_OUTPUT_PATH = ROOT / "packages" / "field-contract" / "erp-sim.openapi.json"


def main() -> int:
    openapi_schema = app.openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
    with open(ERP_SIM_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(erp_sim_app.openapi(), f, indent=2)
    print(f"[OK] Exported OpenAPI: {OUTPUT_PATH.relative_to(ROOT)}, {ERP_SIM_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
