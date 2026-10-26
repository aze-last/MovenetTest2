<#
version-up.ps1 -- One-shot semantic version bump for the Agentic Team Orchestrator kit.

What it does (run from the kit root or an installed project root):
  1. Bumps '> Version:' in .agents\VERSION.md        (default tier: PATCH, v1.0.1 -> v1.0.2)
  2. Restamps   '> Last Updated:' with today's date
  3. Prepends a matching entry to .agents\CHANGELOG.md (newest first)

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File .agents\version-up.ps1 -Note "what changed"
  powershell -NoProfile -ExecutionPolicy Bypass -File .agents\version-up.ps1 -Minor -Note "new skill added"
  powershell -NoProfile -ExecutionPolicy Bypass -File .agents\version-up.ps1 -Major -Note "breaking protocol change"
#>
param(
    [string]$Note = "content update",
    [switch]$Minor,
    [switch]$Major
)

$manifestPath  = Join-Path $PSScriptRoot "VERSION.md"
$changelogPath = Join-Path $PSScriptRoot "CHANGELOG.md"

if (-not (Test-Path $manifestPath)) {
    Write-Error "VERSION.md not found at $manifestPath"
    exit 1
}

$manifest = Get-Content $manifestPath -Raw -Encoding UTF8

if ($manifest -notmatch '(?m)^>\s*Version:\s*v(\d+)\.(\d+)\.(\d+)') {
    Write-Error "No '> Version: vMAJOR.MINOR.PATCH' line found in $manifestPath"
    exit 1
}

# NOTE: never name locals $major/$minor - they would collide case-insensitively
# with the $Major/$Minor switch parameters (PowerShell variables are case-insensitive).
$vMajor = [int]$Matches[1]
$vMinor = [int]$Matches[2]
$vPatch = [int]$Matches[3]

if ($Major)     { $vMajor = $vMajor + 1; $vMinor = 0; $vPatch = 0 }
elseif ($Minor) { $vMinor = $vMinor + 1; $vPatch = 0 }
else            { $vPatch = $vPatch + 1 }

$newVersion = "v$vMajor.$vMinor.$vPatch"
$stamp = (Get-Date -Format "yyyy-MM-dd")

$manifest = $manifest -replace '(?m)^>\s*Version:\s*v\d+\.\d+\.\d+', "> Version: $newVersion"
$manifest = $manifest -replace '(?m)^>\s*Last Updated:\s*\d{4}-\d{2}-\d{2}', "> Last Updated: $stamp"
Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

if (Test-Path $changelogPath) {
    $changelog = Get-Content $changelogPath -Raw -Encoding UTF8
    $entry = "## $newVersion - $stamp`n- $Note`n"
    if ($changelog -match '(?m)^# Changelog[^\r\n]*\r?\n') {
        $changelog = $changelog -replace '(?m)^(# Changelog[^\r\n]*\r?\n)', "`$1`n$entry"
    } else {
        $changelog = "$entry`n$changelog"
    }
    Set-Content -Path $changelogPath -Value $changelog -Encoding UTF8
} else {
    Write-Warning "CHANGELOG.md not found at $changelogPath - version bumped without changelog entry."
}

Write-Host "[OK] Kit version bumped to $newVersion ($Note)" -ForegroundColor Green
