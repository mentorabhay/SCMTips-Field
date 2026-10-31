# The 3-minute demo run on Windows (PowerShell 7), docs/DEMO_RUN.md. In <repo>:
#   .\scripts\dev\demo-run.ps1 <the SCMTIPS core checkout>          # or set $env:SCMTIPS_CORE_DIR first
#   .\scripts\dev\demo-run.ps1 <core> --po PO-26-1002 --scenario magnet-export-curbs --web http://app.localhost:3100
# Needs: the core kit running (API :8000, worker :8001) with demo mode on, on a branch that has scmtips-demo and
# scmtips-scenario (the core's integration branch); the Field stack up (run-field-stack.ps1 up) with FIELD_CORE_TARGET=core.
# There is no default core folder on purpose: the kit in <workspace>\ARO may run an older branch.
# All logic lives in tools/dev_stack/demo_run.py (tested); this file only forwards the arguments and the exit code.
param([string]$Core = $env:SCMTIPS_CORE_DIR, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not $Core) {
    Write-Host "FAIL: give the SCMTIPS core checkout: .\scripts\dev\demo-run.ps1 <folder> (or set SCMTIPS_CORE_DIR)"
    exit 1
}
uv run --frozen python -m tools.dev_stack.demo_run --core $Core @Rest
exit $LASTEXITCODE
