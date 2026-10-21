
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found at: $Python"
    exit 1
}

Push-Location $ProjectRoot

try {
    Write-Host "`n[1/3] Ruff linting"
    & $Python -m ruff check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "`n[2/3] Ruff formatting"
    & $Python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "`n[3/3] Pytest"
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "`nAll quality checks passed."
}
finally {
    Pop-Location
}
