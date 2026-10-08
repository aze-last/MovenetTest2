# scripts/build_installer.ps1 - Automated Inno Setup Builder for CellWatch AI
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " CellWatch AI - Inno Setup Installer Build Pipeline" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Read single-source application version from monitor_app/__init__.py
$InitPy = Join-Path $ProjectRoot "monitor_app\__init__.py"
if (-not (Test-Path $InitPy)) {
    Write-Error "Cannot find $InitPy"
    exit 1
}

$VersionMatch = Select-String -Path $InitPy -Pattern '__version__\s*=\s*["'']([^"'']+)["'']'
if (-not $VersionMatch) {
    Write-Error "Could not parse __version__ from $InitPy"
    exit 1
}
$AppVersion = $VersionMatch.Matches[0].Groups[1].Value
Write-Host "[1/5] Application Version: $AppVersion" -ForegroundColor Green

# 2. Locate Inno Setup Compiler (ISCC.exe)
$IsccCandidates = @(
    "C:\Users\ASUS\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

$IsccPath = $null
foreach ($cand in $IsccCandidates) {
    if (Test-Path $cand) {
        $IsccPath = $cand
        break
    }
}

if (-not $IsccPath) {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        $IsccPath = $cmd.Source
    }
}

if (-not $IsccPath) {
    Write-Error "Inno Setup Compiler (ISCC.exe) not found! Install via 'winget install JRSoftware.InnoSetup'."
    exit 1
}
Write-Host "[2/5] Located Inno Setup: $IsccPath" -ForegroundColor Green

# 3. Ensure VC++ 2015-2022 x64 Redistributable is vendored and hash-pinned in installer/redist/
$RedistDir = Join-Path $ProjectRoot "installer\redist"
if (-not (Test-Path $RedistDir)) {
    New-Item -ItemType Directory -Path $RedistDir -Force | Out-Null
}

$VcRedistPath = Join-Path $RedistDir "vc_redist.x64.exe"
# Pinned SHA-256 hash for Microsoft Visual C++ 2015-2022 Redistributable (x64) v14.40+
$ExpectedVcRedistSha256 = "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b"

if (-not (Test-Path $VcRedistPath)) {
    Write-Host "[3/5] Downloading Microsoft Visual C++ 2015-2022 Redistributable..." -ForegroundColor Yellow
    $VcUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $VcUrl -OutFile $VcRedistPath -UseBasicParsing
        Write-Host "      Downloaded vc_redist.x64.exe successfully." -ForegroundColor Green
    } catch {
        Write-Error "Failed to download vc_redist.x64.exe: $_"
        exit 1
    }
} else {
    Write-Host "[3/5] Visual C++ Redistributable cached: $VcRedistPath" -ForegroundColor Green
}

# Verify pinned SHA-256 hash
$ActualVcHash = (Get-FileHash -Path $VcRedistPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualVcHash -ne $ExpectedVcRedistSha256.ToLowerInvariant()) {
    Remove-Item $VcRedistPath -Force -ErrorAction SilentlyContinue
    Write-Error "SHA-256 mismatch for vc_redist.x64.exe! Expected: $ExpectedVcRedistSha256, got: $ActualVcHash. Deleted corrupted file."
    exit 1
}
Write-Host "      Verified vc_redist.x64.exe SHA-256: $ActualVcHash" -ForegroundColor Green

# 4. Compile Inno Setup Script
$IssFile = Join-Path $ProjectRoot "installer\CellWatch.iss"
$OutputDir = Join-Path $ProjectRoot "artifacts\installer"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "[4/5] Compiling installer with Inno Setup..." -ForegroundColor Yellow
$Process = Start-Process -FilePath $IsccPath -ArgumentList "/DMyAppVersion=$AppVersion", "`"$IssFile`"" -NoNewWindow -PassThru -Wait
if ($Process.ExitCode -ne 0) {
    Write-Error "ISCC compilation failed with exit code $($Process.ExitCode)"
    exit $Process.ExitCode
}

# 5. Verify Output and Compute SHA-256
$InstallerExe = Join-Path $OutputDir "CellWatch-Setup-$AppVersion.exe"
if (-not (Test-Path $InstallerExe)) {
    Write-Error "Expected installer not found at $InstallerExe"
    exit 1
}

$Hash = (Get-FileHash -Path $InstallerExe -Algorithm SHA256).Hash.ToLowerInvariant()
$SizeMB = [math]::Round(((Get-Item $InstallerExe).Length / 1MB), 2)

Write-Host "[5/5] Installer Generated Successfully!" -ForegroundColor Green
Write-Host "      Path:    $InstallerExe" -ForegroundColor Cyan
Write-Host "      Size:    $SizeMB MB" -ForegroundColor Cyan
Write-Host "      SHA-256: $Hash" -ForegroundColor Cyan

# 6. Generate matching version.json template
$VersionJsonPath = Join-Path $OutputDir "version.json"
$VersionData = [PSCustomObject]@{
    version           = $AppVersion
    notes             = @(
        "Initial release with MoveNet pose estimation and YOLO26s contraband detection.",
        "Integrated multi-camera Concealment Fusion Engine.",
        "Institutional Dark theme and operator telemetry monitoring."
    )
    publishedAt       = (Get-Date -Format "yyyy-MM-dd")
    releasePageUrl    = "https://github.com/CellWatchAI/CellWatch/releases/tag/v$AppVersion"
    installerFileName = "CellWatch-Setup-$AppVersion.exe"
    installerUrl      = "https://github.com/CellWatchAI/CellWatch/releases/download/v$AppVersion/CellWatch-Setup-$AppVersion.exe"
    sha256            = $Hash
}

$VersionData | ConvertTo-Json -Depth 4 | Set-Content -Path $VersionJsonPath -Encoding utf8
Write-Host "      Manifest template written to: $VersionJsonPath" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
