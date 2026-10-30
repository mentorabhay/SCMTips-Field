#!/usr/bin/env bash
# Field-test stack on Linux/macOS. Same commands as run-field-stack.ps1 (up | pair | smoke | delivery | status | down).
set -euo pipefail
cd "$(dirname "$0")/../.."
uv sync --frozen
exec uv run python -m tools.dev_stack.stack "${1:-up}" "${@:2}"
