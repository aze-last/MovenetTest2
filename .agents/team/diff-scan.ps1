<#
diff-scan.ps1 -- Deterministic Gate (Windows; bash twin: diff-scan.sh for Linux/macOS).
Execution Order: script -> failures straight back to the coder -> reviewer inspects git diff.
Gate-enforced stacks:
  - Laravel / PHP      : Pint lint + artisan test
  - Node / TypeScript  : package.json scripts (pnpm lint / pnpm test) - TS rides the Node path
  - Python             : ruff lint (uv-preferred) + pytest (narrower by changed test files)
  - Flutter / Dart     : dart format (check-only) + flutter analyze + flutter test
  - Rust               : cargo fmt --check + cargo test
  - Go                 : gofmt -l + go test ./...
Tool-missing and no-surface cases are explicitly NOTEd, never silently skipped.
Exit 0 = GREEN. Exit 1 = BLOCK. The gate is FAIL-CLOSED: git enumeration errors can never produce a silent GREEN.
Run from repo root:  powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\team\diff-scan.ps1 [-TestFilter <name>] [-GateOnly]
TestFilter is honored by:artisan --filter, pnpm test -- <name>, pytest -k, cargo test <name>, go test -run.
-GateOnly runs the allowlist/denied-file/secret/pnpm/destructive gate and exits before any
linter or test. run-verifier.ps1 uses it so no gate logic is duplicated.
#>
param([string]$TestFilter = "", [switch]$GateOnly)

$script:fail = $false
function Block([string]$m) { Write-Host "BLOCK: $m"; $script:fail = $true }
function Note([string]$m)  { Write-Host "NOTE:  $m" }
function Report([string]$m){ Write-Host "GATE:  $m" }
function Has-Tool([string]$n) { return [bool](Get-Command $n -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------------------
# Fail-closed repository allowlist + secret/credential gate.
# This runs before any linter/test (and before any verifier/model call).
# Default deny: missing allowlist, missing repo identity, or no matching entry
# aborts immediately. Findings never print the suspected secret value.
# ---------------------------------------------------------------------------

function Normalize-RepoPath([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return "" }
    $x = $p.Trim().TrimEnd([char[]]@('\', '/'))
    $x = $x -replace '\\', '/'
    if ($x -match '^[A-Za-z]:') {
        $x = $x.Substring(0, 1).ToLowerInvariant() + $x.Substring(1)
    }
    return $x.ToLowerInvariant()
}

function Normalize-Remote([string]$r) {
    if ([string]::IsNullOrWhiteSpace($r)) { return "" }
    $x = $r.Trim().TrimEnd([char[]]@('\', '/'))
    $x = $x -replace '\.git$', ''
    return $x.ToLowerInvariant()
}

function Get-RepoRoot {
    $out = @(git rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or $out.Count -eq 0 -or [string]::IsNullOrWhiteSpace($out[0])) {
        return $null
    }
    return $out[0].Trim()
}

function Get-RepoRemotes {
    $result = @()
    $names = @(git remote 2>$null)
    if ($LASTEXITCODE -ne 0) { return $result }
    foreach ($name in $names) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $urls = @(git remote get-url --all $name 2>$null)
        foreach ($url in $urls) {
            if (-not [string]::IsNullOrWhiteSpace($url)) { $result += $url.Trim() }
        }
    }
    return $result
}

function Assert-RepoAllowed {
    $allowlist = if ($env:REPO_ALLOWLIST -and $env:REPO_ALLOWLIST.Trim() -ne "") {
        $env:REPO_ALLOWLIST
    } else {
        Join-Path (Get-Location) ".agents/team/repo-allowlist.txt"
    }
    if (-not (Test-Path -LiteralPath $allowlist -PathType Leaf)) {
        Block "REPO_ALLOWLIST not found at $allowlist - default deny (no verifier/model call)."
        return $false
    }

    $root = Get-RepoRoot
    if ([string]::IsNullOrWhiteSpace($root)) {
        Block "Cannot determine the repository root - default deny."
        return $false
    }

    $normRoot = Normalize-RepoPath $root
    $normRemotes = @(Get-RepoRemotes | ForEach-Object { Normalize-Remote $_ } | Where-Object { $_ -ne "" } | Select-Object -Unique)
    $entries = @(Get-Content -LiteralPath $allowlist -Encoding UTF8 |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -ne "" -and -not $_.StartsWith("#") })

    if ($entries.Count -eq 0) {
        Block "REPO_ALLOWLIST is empty at $allowlist - default deny."
        return $false
    }

    $allowed = $false
    foreach ($entry in $entries) {
        if ($entry -match '^path\s*:\s*(.+)$') {
            if ((Normalize-RepoPath $Matches[1]) -eq $normRoot) { $allowed = $true; break }
        } elseif ($entry -match '^remote\s*:\s*(.+)$') {
            $needle = Normalize-Remote $Matches[1]
            if ($normRemotes -contains $needle) { $allowed = $true; break }
        } else {
            if ((Normalize-RepoPath $entry) -eq $normRoot) { $allowed = $true; break }
            $needle = Normalize-Remote $entry
            if ($normRemotes -contains $needle) { $allowed = $true; break }
        }
    }

    if (-not $allowed) {
        Block "Repository not allowlisted (default deny). Root: $root. Add 'path:$root' or a matching 'remote:<url>' to $allowlist."
        return $false
    }
    Note "Repository allowlisted: $root"
    return $true
}

$script:BinaryExtensions = @(
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.tif', '.tiff',
    '.pdf', '.zip', '.gz', '.tgz', '.tar', '.7z', '.rar', '.xz', '.bz2',
    '.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.pyc', '.pyo', '.class',
    '.jar', '.war', '.mp3', '.mp4', '.mov', '.avi', '.mkv', '.wav', '.flac',
    '.woff', '.woff2', '.ttf', '.otf', '.eot', '.sqlite', '.sqlite3', '.db',
    '.xls', '.xlsx', '.doc', '.docx', '.ppt', '.pptx', '.psd', '.blend'
)

function Test-BinaryFile([string]$path) {
    $ext = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($script:BinaryExtensions -contains $ext) { return $true }
    try {
        $full = (Get-Item -LiteralPath $path -ErrorAction Stop).FullName
        $fs = [System.IO.File]::OpenRead($full)
        try {
            $buf = New-Object byte[] 8000
            $n = $fs.Read($buf, 0, $buf.Length)
            for ($i = 0; $i -lt $n; $i++) {
                if ($buf[$i] -eq 0) { return $true }
            }
        } finally {
            $fs.Close()
        }
    } catch {
        return $true
    }
    return $false
}

function Test-PathHasSegment([string]$path, [string]$segment) {
    $p = ($path -replace '\\', '/').Trim('/')
    if ($p -eq $segment) { return $true }
    if ($p -like "$segment/*") { return $true }
    if ($p -like "*/$segment/*") { return $true }
    if ($p -like "*/$segment") { return $true }
    return $false
}

function Test-DeniedFile([string]$path) {
    $p = ($path -replace '\\', '/')
    $leaf = [System.IO.Path]::GetFileName($p)

    # Environment templates are safe; every other .env* file is denied.
    if ($leaf -match '^\.env\.(example|sample|template|dist)$') { return $null }
    if ($leaf -like '.env*') { return 'environment file' }

    if ($leaf -match '^appsettings(\..+)?\.json$') { return 'application settings (may contain credentials)' }
    if ($leaf -match '^id_(rsa|ed25519|ecdsa|dsa)') { return 'SSH private key' }
    if ($leaf -match '\.(pem|key|pfx|p12|jks|keystore|ppk|kdbx|ovpn)$') { return 'private key / credential container' }
    if ($leaf -match '^(credentials|secrets?)(\..+)?$') { return 'credentials file' }
    if ($leaf -match '^(service-account|service_account).*\.json$') { return 'service account key' }
    if ($leaf -match '^\.?(npmrc|pypirc|netrc|git-credentials)$') { return 'credential config' }
    if ($leaf -match '^terraform\.tfstate(\..*)?$' -or $leaf -like '*.tfvars' -or $leaf -like '*.tfvars.json') { return 'terraform state/vars (may contain secrets)' }
    if ($leaf -eq 'package-lock.json' -or $leaf -eq 'yarn.lock' -or $leaf -eq 'bun.lockb') { return 'non-pnpm lockfile' }
    if ($leaf -like '*.sqlite' -or $leaf -like '*.sqlite3' -or $leaf -like '*.db') { return 'binary database' }
    if ($leaf -like '*.dump' -or $leaf -like '*.bak') { return 'database dump/backup' }

    if ($leaf -like '*.sql') {
        if ($p -match '(^|/)(migrations?|migrate|db/migrate)/') { return $null }
        if ($leaf -match 'migrat') { return $null }
        return 'SQL dump/export (may contain sensitive data)'
    }

    if (Test-PathHasSegment $p 'storage') { return 'storage directory' }
    if (Test-PathHasSegment $p '.aws' -and $leaf -eq 'credentials') { return 'AWS credentials' }
    if (Test-PathHasSegment $p '.ssh') { return 'SSH directory' }
    if (Test-PathHasSegment $p '.kube' -and $leaf -eq 'config') { return 'Kubernetes config' }
    if (Test-PathHasSegment $p '.docker' -and $leaf -eq 'config.json') { return 'Docker credential config' }

    return $null
}

$script:SecretRules = @(
    [pscustomobject]@{ Name = 'private-key'; Pattern = '-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----' },
    [pscustomobject]@{ Name = 'aws-access-key'; Pattern = '\b(?:AKIA|ASIA)[0-9A-Z]{16}\b' },
    [pscustomobject]@{ Name = 'aws-secret-key'; Pattern = '(?i)aws_secret_access_key\s*[:=]\s*["'']?[A-Za-z0-9/+=]{40}' },
    [pscustomobject]@{ Name = 'github-token'; Pattern = '\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b' },
    [pscustomobject]@{ Name = 'slack-token'; Pattern = '\bxox[baprs]-[A-Za-z0-9-]{10,}\b' },
    [pscustomobject]@{ Name = 'google-api-key'; Pattern = '\bAIza[0-9A-Za-z\-_]{35}\b' },
    [pscustomobject]@{ Name = 'stripe-key'; Pattern = '\b(?:sk|rk)_live_[0-9A-Za-z]{24,}\b' },
    [pscustomobject]@{ Name = 'openai-style-key'; Pattern = '\bsk-[A-Za-z0-9_-]{32,}\b' },
    [pscustomobject]@{ Name = 'jwt'; Pattern = '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b' },
    [pscustomobject]@{ Name = 'connection-string-password'; Pattern = '(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/@]+:[^@\s]+@' },
    [pscustomobject]@{ Name = 'secret-assignment'; Pattern = '(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|refresh[_-]?token|password|passwd)\b\s*[:=]\s*["''][A-Za-z0-9_\-./+=]{16,}["'']' }
)

$script:SecretFindingKeys = @{}
$script:ScannedLines = New-Object System.Collections.Generic.List[string]

function Test-PlaceholderSecret([string]$text) {
    return ($text -match '(?i)(example|sample|placeholder|dummy|fake|redacted|changeme|change[_-]?me|your[_-]|x{3,}|<[^>]+>|\$\{[^}]+\}|%[A-Z_]+%|os\.environ|process\.env|getenv|env\.get|secret[_-]?manager|vault)')
}

function Get-AddedLineRecords([string]$file) {
    $records = @()
    $newLine = 0
    $diff = @(git diff HEAD -U0 -- $file 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Block "git diff -U0 failed for $file (exit $LASTEXITCODE) - fail-closed."
        return $records
    }
    foreach ($line in $diff) {
        if ($line -match '^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@') {
            $newLine = [int]$Matches[1]
        } elseif ($line -match '^\+(?!\+\+)') {
            $records += [pscustomobject]@{ Line = $newLine; Text = $line.Substring(1) }
            $newLine++
        } elseif ($line -match '^ ') {
            $newLine++
        }
    }
    return $records
}

function Get-FileLineRecords([string]$file) {
    $records = @()
    $lines = @(Get-Content -LiteralPath $file -Encoding UTF8 -ErrorAction SilentlyContinue)
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $records += [pscustomobject]@{ Line = ($i + 1); Text = [string]$lines[$i] }
    }
    return $records
}

function Find-SecretFindings([string]$file, $records) {
    if ($null -eq $records) { return }
    foreach ($rec in @($records)) {
        if ($null -eq $rec) { continue }
        $text = [string]$rec.Text
        if ($text -eq '') { continue }
        if ($script:ScannedLines.Count -lt 200000) {
            $script:ScannedLines.Add("$file`:$($rec.Line): $text")
        }
        if (Test-PlaceholderSecret $text) { continue }
        foreach ($rule in $script:SecretRules) {
            if ($text -match $rule.Pattern) {
                $key = "$file`:$($rec.Line):$($rule.Name)"
                if (-not $script:SecretFindingKeys.ContainsKey($key)) {
                    $script:SecretFindingKeys[$key] = $true
                    Block "$file`:$($rec.Line) - potential secret ($($rule.Name)); value not printed."
                }
                break
            }
        }
    }
}

function Invoke-GitleaksText([string]$label, [string]$text) {
    if (-not (Has-Tool "gitleaks")) { return }
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, $text, (New-Object System.Text.UTF8Encoding($false)))
        & gitleaks detect --no-git --source $tmp --redact --no-banner *> $null
        $code = $LASTEXITCODE
        # gitleaks: 0 = clean, 1 = leaks found, anything else = scanner error.
        if ($code -eq 1) {
            Block "gitleaks reported potential secrets in $label (values redacted); see repo-relative file:line from the regex scan above."
        } elseif ($code -ne 0) {
            Block "gitleaks failed on $label (exit $code) - fail-closed."
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-SecretContentGate {
    # Tracked changes: added lines only (existing untouched content is not re-reviewed).
    foreach ($f in @($files)) {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { continue }
        if (Test-BinaryFile $f) { Note "Skipped binary content scan: $f"; continue }
        Find-SecretFindings $f @(Get-AddedLineRecords $f)
    }
    # Untracked files: the whole file is new content.
    foreach ($f in @($untracked)) {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { continue }
        if (Test-BinaryFile $f) { Note "Skipped binary content scan: $f"; continue }
        Find-SecretFindings $f @(Get-FileLineRecords $f)
    }
    # PLAN.md is the build contract and is always scanned in full.
    if (Test-Path -LiteralPath "PLAN.md" -PathType Leaf) {
        if (Test-BinaryFile "PLAN.md") {
            Block "PLAN.md is binary - fail-closed."
        } else {
            Find-SecretFindings "PLAN.md" @(Get-FileLineRecords "PLAN.md")
        }
    }
    # Optional stronger oracle. The regex rules above are the always-on fallback.
    if (Has-Tool "gitleaks") {
        Invoke-GitleaksText "diff+PLAN.md" ($script:ScannedLines -join "`n")
    } else {
        Note "gitleaks not installed - regex secret fallback used (diff added lines + PLAN.md)."
    }
}

# Per-stack exit report state (n/a = marker absent, never enforced)
$LarLint = "n/a"; $LarTest  = "n/a"
$NodeLint = "n/a"; $NodeTest = "n/a"
$PyLint = "n/a"; $PyTest  = "n/a"
$FlLint = "n/a"; $FlTest  = "n/a"
$RsLint = "n/a"; $RsTest  = "n/a"
$GoLint = "n/a"; $GoTest  = "n/a"

function Test-AddedLines([string]$file, [string[]]$lines) {
    if ($file -like ".agents/*" -or $file -like "*.md") { return }
    $n = 0
    foreach ($line in $lines) {
        $n++
        $code = $line.Substring(1)
        if ($code -match "\b(npm\s+run|npm\s+install|yarn\s+add|yarn\s+install|bun\s+add|bun\s+install)\b") {
            Block "$file (~added $n): Non-pnpm command detected ($($code.Trim())). Use pnpm exclusively."
        }
        if ($code -match "->forceDelete\(\)" -or $code -match "(?i)\b(DROP\s+TABLE|TRUNCATE\s+TABLE)\b") {
            if ($file -notlike "*migration*") {
                Block "$file (~added $n): High-risk destructive operation ($($code.Trim())). Soft delete or explicit dev approval required."
            }
        }
    }
}

# 1. Repository allowlist gate (FAIL-CLOSED, before any model call)
#    Default deny: missing/empty allowlist, or no path/remote match, aborts here.
Write-Host "--- Repository Allowlist Gate ---"
if (-not (Assert-RepoAllowed)) {
    Write-Host "RESULT: BLOCK"
    exit 1
}

# 2. Change-set acquisition (FAIL-CLOSED)
#    Tracked changes   : git diff HEAD --name-only
#    Untracked files   : git ls-files --others --exclude-standard  (ALWAYS included - untracked
#                        violating files can no longer escape the ban check)
#    Zero-commit repo  : no HEAD exists -> the whole worktree counts as new content.
git rev-parse -q --verify HEAD 2>$null | Out-Null
$hasHead = ($LASTEXITCODE -eq 0)

$files = @()
if ($hasHead) {
    $gitOutput = git diff HEAD --name-only 2>$null
    if ($LASTEXITCODE -ne 0) {
        Block "git diff HEAD failed (exit $LASTEXITCODE) - fail-closed: cannot verify the change set."
    } else {
        $files = @($gitOutput | Where-Object { $_ -ne "" })
    }
} else {
    Note "No commits yet (no HEAD) - entire worktree is treated as new content."
}

$untracked = @()
$gitOutput = git ls-files --others --exclude-standard 2>$null
if ($LASTEXITCODE -ne 0) {
    Block "git ls-files failed (exit $LASTEXITCODE) - fail-closed: cannot list untracked files."
} else {
    $untracked = @($gitOutput | Where-Object { $_ -ne "" })
}

$allFiles = @($files + $untracked | Select-Object -Unique)

# 2a. Denied files anywhere in the change set.
#     Covers secrets, credential containers, binary DBs, SQL dumps, and foreign lockfiles.
foreach ($f in $allFiles) {
    $reason = Test-DeniedFile $f
    if ($reason) { Block "$f in change set -- denied ($reason)." }
}

# 2b. Secret content gate (diff added lines + untracked text + full PLAN.md).
#     Runs before any linter/test and before the verifier/model call. Never prints values.
Invoke-SecretContentGate

# 3. Strict PNPM + destructive-op scan on added content
#    Tracked files: scan added lines from git diff -U0. Untracked files: whole file is new content.
foreach ($f in $files) {
    if (-not (Test-Path $f)) { continue } # deleted file - name already banned-checked above
    $added = @(git diff HEAD -U0 -- $f 2>$null | Where-Object { $_ -match "^\+" -and $_ -notmatch "^\+\+\+" })
    if ($LASTEXITCODE -ne 0) {
        Block "git diff -U0 failed for $f (exit $LASTEXITCODE) - fail-closed."
        continue
    }
    Test-AddedLines $f $added
}
foreach ($f in $untracked) {
    $added = @(Get-Content $f -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object { "+$_" })
    Test-AddedLines $f $added
}

# 3a. Gate-only mode (used by run-verifier): exit before any linter/test execution.
if ($GateOnly) {
    Write-Host "--- Gate Report ---"
    Report "GATE-ONLY: allowlist + denied-file + secret + pnpm/destructive checks."
    if ($script:fail) {
        Write-Host "RESULT: BLOCK"
        exit 1
    }
    Write-Host "RESULT: GREEN"
    exit 0
}

# 4. Linter Gate (per-stack detection; every detected stack's linter runs independently)
Write-Host "--- Linter Gate ---"

# 3a. Laravel -- Pint
if (Test-Path "vendor/bin/pint") {
    if (Has-Tool "php") {
        php vendor/bin/pint --dirty --format agent
        if ($LASTEXITCODE -ne 0) { $LarLint = "FAILED"; Block "Pint linter failed (exit $LASTEXITCODE)." } else { $LarLint = "ran ok" }
    } else {
        $LarLint = "skipped (php missing)"
        Note "Laravel Pint present but 'php' is not on PATH - lint skipped."
    }
}

# 3b. Node / TypeScript -- pnpm lint (TS projects declare "lint" in package.json)
$pkgLint = $false; $pkgTest = $false
if (Test-Path "package.json") {
    $pkg = Get-Content "package.json" -Raw -Encoding UTF8
    if ($pkg -match '"lint"') { $pkgLint = $true }
    if ($pkg -match '"test"') { $pkgTest = $true }
}
if ($pkgLint) {
    if (Has-Tool "pnpm") {
        pnpm run lint
        if ($LASTEXITCODE -ne 0) { $NodeLint = "FAILED"; Block "pnpm lint failed (exit $LASTEXITCODE)." } else { $NodeLint = "ran ok" }
    } else {
        $NodeLint = "skipped (pnpm missing)"
        Note "package.json declares a lint script but 'pnpm' is not on PATH - lint skipped."
    }
}

# 3c. Python -- ruff (uv-wrapped invocation preferred when pyproject.toml + uv exist)
if ((Test-Path "pyproject.toml") -or (Test-Path "requirements.txt")) {
    if ((Has-Tool "ruff") -or (Has-Tool "uv")) {
        if ((Test-Path "pyproject.toml") -and (Has-Tool "uv")) {
            uv run ruff check .
        } else {
            ruff check .
        }
        if ($LASTEXITCODE -ne 0) { $PyLint = "FAILED"; Block "ruff check failed (exit $LASTEXITCODE)." } else { $PyLint = "ran ok" }
    } else {
        $PyLint = "skipped (ruff/uv missing)"
        Note "Python detected but neither 'ruff' nor 'uv' is on PATH - lint skipped (agents: use 'uv run ruff check .')."
    }
}

# 3d. Flutter / Dart -- dart format (check-only) + flutter analyze
if (Test-Path "pubspec.yaml") {
    if ((Has-Tool "dart") -and (Has-Tool "flutter")) {
        dart format --set-exit-if-changed --output=none .
        $fmtOk = ($LASTEXITCODE -eq 0)
        flutter analyze
        if ((-not $fmtOk) -or ($LASTEXITCODE -ne 0)) {
            $FlLint = "FAILED"
            Block "dart format / flutter analyze failed - run 'dart format .' then re-check (exit codes: fmt=$(if ($fmtOk) { 0 } else { 1 }))."
        } else {
            $FlLint = "ran ok"
        }
    } else {
        $FlLint = "skipped (dart/flutter missing)"
        Note "Flutter detected but 'dart'/'flutter' not on PATH - lint skipped."
    }
}

# 3e. Rust -- cargo fmt --check
if (Test-Path "Cargo.toml") {
    if (Has-Tool "cargo") {
        cargo fmt --check
        if ($LASTEXITCODE -ne 0) { $RsLint = "FAILED"; Block "cargo fmt --check failed - run 'cargo fmt' locally (exit $LASTEXITCODE)." } else { $RsLint = "ran ok" }
    } else {
        $RsLint = "skipped (cargo missing)"
        Note "Rust detected but 'cargo' is not on PATH - lint skipped."
    }
}

# 3f. Go -- gofmt -l (non-empty output = files need formatting)
if (Test-Path "go.mod") {
    if (Has-Tool "gofmt") {
        $unfmt = @(gofmt -l . 2>$null | Where-Object { $_ -ne "" })
        if ($unfmt.Count -gt 0) {
            $GoLint = "FAILED"
            Block "gofmt: files need formatting: $($unfmt -join ', ')."
        } else {
            $GoLint = "ran ok"
        }
    } else {
        $GoLint = "skipped (gofmt missing)"
        Note "Go detected but 'gofmt' is not on PATH - lint skipped."
    }
}

# 5. Test Gate (per-stack; narrower first when changed test files are known)
Write-Host "--- Test Gate ---"

# 5a. Laravel -- artisan test
if (Test-Path "artisan") {
    if (Has-Tool "php") {
        if ($TestFilter -ne "") {
            php artisan test --compact --filter=$TestFilter
            if ($LASTEXITCODE -eq 0) { $LarTest = "ran ok (filter)" } else { $LarTest = "FAILED"; Block "Tests failed (exit $LASTEXITCODE)." }
        } elseif (@($allFiles | Where-Object { $_ -like "tests/*.php" }).Count -gt 0) {
            foreach ($tf in @($allFiles | Where-Object { $_ -like "tests/*.php" })) {
                php artisan test --compact $tf
                if ($LASTEXITCODE -ne 0) { $LarTest = "FAILED"; Block "Tests failed in $tf (exit $LASTEXITCODE)." }
            }
            if ($LarTest -eq "n/a") { $LarTest = "ran ok (narrow)" }
        } else {
            php artisan test --compact
            if ($LASTEXITCODE -eq 0) { $LarTest = "ran ok (full)" } else { $LarTest = "FAILED"; Block "Tests failed (exit $LASTEXITCODE)." }
        }
    } else {
        $LarTest = "skipped (php missing)"
        Note "Laravel detected but 'php' is not on PATH - tests skipped."
    }
}

# 5b. Node / TypeScript -- pnpm test
if ($pkgTest) {
    if (Has-Tool "pnpm") {
        if ($TestFilter -ne "") { pnpm test -- $TestFilter } else { pnpm test }
        if ($LASTEXITCODE -ne 0) { $NodeTest = "FAILED"; Block "pnpm test failed (exit $LASTEXITCODE)." } else { $NodeTest = "ran ok" }
    } else {
        $NodeTest = "skipped (pnpm missing)"
        Note "package.json declares a test script but 'pnpm' is not on PATH - tests skipped."
    }
}

# 5c. Python -- pytest (narrower by changed tests/**.py or root test_*.py; uv-preferred)
if ((Test-Path "pyproject.toml") -or (Test-Path "requirements.txt")) {
    $pyTests = @($allFiles | Where-Object { $_ -match "^tests?[/\\].*\.py$" -or ($_ -like "test_*.py") })
    $localPytest = if (Test-Path ".venv310\Scripts\pytest.exe") { ".venv310\Scripts\pytest.exe" }
                   elseif (Test-Path ".venv\Scripts\pytest.exe") { ".venv\Scripts\pytest.exe" }
                   elseif (Has-Tool "pytest") { "pytest" }
                   else { $null }
    if ($localPytest -or (Has-Tool "uv")) {
        $pyViaUv = ((Test-Path "pyproject.toml") -and (Has-Tool "uv"))
        if ($pyViaUv) {
            if ($TestFilter -ne "") { uv run pytest -k $TestFilter }
            elseif ($pyTests.Count -gt 0) { uv run pytest @pyTests }
            else { uv run pytest }
        } else {
            if ($TestFilter -ne "") { & $localPytest -k $TestFilter }
            elseif ($pyTests.Count -gt 0) { & $localPytest @pyTests }
            else { & $localPytest }
        }
        if ($LASTEXITCODE -ne 0) {
            if ($LASTEXITCODE -eq 5) {
                Block "pytest collected no tests (exit 5) - TDD requires a failing-first test; add at least one pytest test."
            } else {
                Block "pytest failed (exit $LASTEXITCODE)."
            }
            $PyTest = "FAILED"
        }
        elseif ($TestFilter -ne "") { $PyTest = "ran ok (filter)" }
        elseif ($pyTests.Count -gt 0) { $PyTest = "ran ok (narrow)" }
        else { $PyTest = "ran ok (full)" }
    } else {
        $PyTest = "skipped (pytest/uv missing)"
        Note "Python detected but neither 'pytest' nor 'uv' is on PATH - tests skipped (agents: use 'uv run pytest')."
    }
}

# 5d. Flutter -- flutter test (narrower by changed test/**_test.dart)
if (Test-Path "pubspec.yaml") {
    if ((Has-Tool "flutter") -and (Has-Tool "dart")) {
        $flTests = @($allFiles | Where-Object { $_ -match "^test[/\\].*_test\.dart$" })
        if ($flTests.Count -gt 0) {
            flutter test @flTests
            if ($LASTEXITCODE -eq 0) { $FlTest = "ran ok (narrow)" } else { $FlTest = "FAILED"; Block "flutter test failed (exit $LASTEXITCODE)." }
        } else {
            flutter test
            if ($LASTEXITCODE -eq 0) { $FlTest = "ran ok (full)" } else { $FlTest = "FAILED"; Block "flutter test failed (exit $LASTEXITCODE)." }
        }
    } else {
        $FlTest = "skipped (flutter missing)"
        Note "Flutter detected but 'flutter' is not on PATH - tests skipped."
    }
}

# 5e. Rust -- cargo test
if (Test-Path "Cargo.toml") {
    if (Has-Tool "cargo") {
        if ($TestFilter -ne "") { cargo test $TestFilter } else { cargo test }
        if ($LASTEXITCODE -ne 0) { $RsTest = "FAILED"; Block "cargo test failed (exit $LASTEXITCODE)." } else { $RsTest = "ran ok" }
    } else {
        $RsTest = "skipped (cargo missing)"
        Note "Rust detected but 'cargo' is not on PATH - tests skipped."
    }
}

# 5f. Go -- go test ./...
if (Test-Path "go.mod") {
    if (Has-Tool "go") {
        if ($TestFilter -ne "") { go test -run $TestFilter ./... } else { go test ./... }
        if ($LASTEXITCODE -ne 0) { $GoTest = "FAILED"; Block "go test failed (exit $LASTEXITCODE)." } else { $GoTest = "ran ok" }
    } else {
        $GoTest = "skipped (go missing)"
        Note "Go detected but 'go' is not on PATH - tests skipped."
    }
}

# 6. No-surface honesty note (only when the repo matches NO supported stack)
$surfaceMarkers = @("artisan", "package.json", "pyproject.toml", "requirements.txt", "pubspec.yaml", "Cargo.toml", "go.mod")
$foundSurfaces = @($surfaceMarkers | Where-Object { Test-Path $_ })
if ($foundSurfaces.Count -eq 0) {
    Note "No supported stack surface found -> lint/test gates skipped by design (see .agents/rules.md)."
}

# 7. Gate Report (definitive per-stack states for the coder report)
Write-Host "--- Gate Report ---"
Report "LARAVEL : lint=$LarLint | test=$LarTest"
Report "NODE/TS : lint=$NodeLint | test=$NodeTest"
Report "PYTHON  : lint=$PyLint | test=$PyTest"
Report "FLUTTER : lint=$FlLint | test=$FlTest"
Report "RUST    : lint=$RsLint | test=$RsTest"
Report "GO      : lint=$GoLint | test=$GoTest"

if ($script:fail) {
    Write-Host "RESULT: BLOCK"
    exit 1
} else {
    Write-Host "RESULT: GREEN"
    exit 0
}
