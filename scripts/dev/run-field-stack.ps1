# Field-test stack on Windows. Usage (PowerShell, in <repo>):
#   .\scripts\dev\run-field-stack.ps1            # start everything (creates .env.local on first run)
#   .\scripts\dev\run-field-stack.ps1 pair       # show the QR code for the phone app
#   .\scripts\dev\run-field-stack.ps1 smoke      # prove the phone -> ERP path without a phone
#   .\scripts\dev\run-field-stack.ps1 delivery   # create a new inbound delivery to receive
#   .\scripts\dev\run-field-stack.ps1 down
# All logic lives in tools/dev_stack/stack.py (tested); this file only forwards the command.
param([string]$Command = "up", [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
uv sync --frozen
uv run python -m tools.dev_stack.stack $Command @Rest
exit $LASTEXITCODE
