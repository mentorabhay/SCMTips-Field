#!/usr/bin/env bash
# Run one CI step, keep its full output in ci-out/<name>.log (published to the ci-logs branch so the
# build can be diagnosed without the Actions log API), and return the command's own exit status.
# Usage: scripts/ci/logged.sh <name> <command> [args...]
set -uo pipefail
name="$1"; shift
out="${GITHUB_WORKSPACE:-$(git rev-parse --show-toplevel)}/ci-out"
mkdir -p "$out"
{ echo "\$ $*"; echo "cwd: $(pwd)"; date -u +"%Y-%m-%dT%H:%M:%SZ"; } > "$out/$name.log"
"$@" 2>&1 | tee -a "$out/$name.log"
status=${PIPESTATUS[0]}
echo "exit status: $status" >> "$out/$name.log"
exit "$status"
