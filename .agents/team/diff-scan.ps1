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
Run from repo root:  powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\team\diff-scan.ps1 [-TestFilter <name>]
TestFilter is honored by:artisan --filter, pnpm test -- <name>, pytest -k, cargo test <name>, go test -run.
#>
param([string]$TestFilter = "")

$script:fail = $false
function Block([string]$m) { Write-Host "BLOCK: $m"; $script:fail = $true }
function Note([string]$m)  { Write-Host "NOTE:  $m" }
function Report([string]$m){ Write-Host "GATE:  $m" }
function Has-Tool([string]$n) { return [bool](Get-Command $n -ErrorAction SilentlyContinue) }

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

# 1. Change-set acquisition (FAIL-CLOSED)
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

# 1a. Banned files anywhere in the change set (secrets, binary DBs, foreign lockfiles)
$bannedPatterns = @(".env*", "*.sqlite", "*.sqlite3", "*.db", "package-lock.json", "yarn.lock", "bun.lockb")
foreach ($f in $allFiles) {
    if ($f -eq ".env.example") { continue }
    foreach ($pat in $bannedPatterns) {
        if ($f -like $pat) { Block "$f in change set -- banned from commit (secrets, binary DB, or non-pnpm lockfile)." }
    }
}

# 2. Strict PNPM + destructive-op scan on added content
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

# 3. Linter Gate (per-stack detection; every detected stack's linter runs independently)
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

# 4. Test Gate (per-stack; narrower first when changed test files are known)
Write-Host "--- Test Gate ---"

# 4a. Laravel -- artisan test
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

# 4b. Node / TypeScript -- pnpm test
if ($pkgTest) {
    if (Has-Tool "pnpm") {
        if ($TestFilter -ne "") { pnpm test -- $TestFilter } else { pnpm test }
        if ($LASTEXITCODE -ne 0) { $NodeTest = "FAILED"; Block "pnpm test failed (exit $LASTEXITCODE)." } else { $NodeTest = "ran ok" }
    } else {
        $NodeTest = "skipped (pnpm missing)"
        Note "package.json declares a test script but 'pnpm' is not on PATH - tests skipped."
    }
}

# 4c. Python -- pytest (narrower by changed tests/**.py or root test_*.py; uv-preferred)
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

# 4d. Flutter -- flutter test (narrower by changed test/**_test.dart)
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

# 4e. Rust -- cargo test
if (Test-Path "Cargo.toml") {
    if (Has-Tool "cargo") {
        if ($TestFilter -ne "") { cargo test $TestFilter } else { cargo test }
        if ($LASTEXITCODE -ne 0) { $RsTest = "FAILED"; Block "cargo test failed (exit $LASTEXITCODE)." } else { $RsTest = "ran ok" }
    } else {
        $RsTest = "skipped (cargo missing)"
        Note "Rust detected but 'cargo' is not on PATH - tests skipped."
    }
}

# 4f. Go -- go test ./...
if (Test-Path "go.mod") {
    if (Has-Tool "go") {
        if ($TestFilter -ne "") { go test -run $TestFilter ./... } else { go test ./... }
        if ($LASTEXITCODE -ne 0) { $GoTest = "FAILED"; Block "go test failed (exit $LASTEXITCODE)." } else { $GoTest = "ran ok" }
    } else {
        $GoTest = "skipped (go missing)"
        Note "Go detected but 'go' is not on PATH - tests skipped."
    }
}

# 5. No-surface honesty note (only when the repo matches NO supported stack)
$surfaceMarkers = @("artisan", "package.json", "pyproject.toml", "requirements.txt", "pubspec.yaml", "Cargo.toml", "go.mod")
$foundSurfaces = @($surfaceMarkers | Where-Object { Test-Path $_ })
if ($foundSurfaces.Count -eq 0) {
    Note "No supported stack surface found -> lint/test gates skipped by design (see .agents/rules.md)."
}

# 6. Gate Report (definitive per-stack states for the coder report)
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
