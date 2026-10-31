#!/usr/bin/env bash
# The 3-minute demo run on Linux/macOS (docs/DEMO_RUN.md):
#   scripts/dev/demo-run.sh <the SCMTIPS core checkout> [--po PO-26-1002] [--scenario magnet-export-curbs]
# (or set SCMTIPS_CORE_DIR). All logic lives in tools/dev_stack/demo_run.py; this file forwards the arguments, and
# exec hands the run's own exit code back.
set -euo pipefail
cd "$(dirname "$0")/../.."
core="${1:-${SCMTIPS_CORE_DIR:-}}"
if [ $# -gt 0 ]; then shift; fi
exec uv run --frozen python -m tools.dev_stack.demo_run --core "$core" "$@"
