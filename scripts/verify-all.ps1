$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

Set-Location $repoRoot
python scripts/verify_all.py $args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
