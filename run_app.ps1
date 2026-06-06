$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv310\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Missing .venv310. Create it with: py -3.10 -m venv .venv310"
    exit 1
}

& $py (Join-Path $root "monitor_app\main.py")
