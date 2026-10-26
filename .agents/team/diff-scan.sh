#!/usr/bin/env bash
# diff-scan.sh -- bash twin of diff-scan.ps1 (Linux/macOS parity, identical contract).
# Execution Order: script -> failures straight back to the coder -> reviewer inspects git diff.
# Gate-enforced stacks:
#   - Laravel / PHP      : Pint lint + artisan test
#   - Node / TypeScript  : package.json scripts (pnpm lint / pnpm test) - TS rides the Node path
#   - Python             : ruff lint (uv-preferred) + pytest (narrower by changed test files)
#   - Flutter / Dart     : dart format (check-only) + flutter analyze + flutter test
#   - Rust               : cargo fmt --check + cargo test
#   - Go                 : gofmt -l + go test ./...
# Exit 0 = GREEN. Exit 1 = BLOCK. FAIL-CLOSED: git enumeration errors can never produce a silent GREEN.
# Usage: bash .agents/team/diff-scan.sh [TestFilter]
# TestFilter is honored by: artisan --filter, pnpm test -- <name>, pytest -k, cargo test <name>, go test -run.

TESTFILTER="${1:-}"
FAIL=0

block()   { echo "BLOCK: $*"; FAIL=1; }
note()    { echo "NOTE:  $*"; }
report()  { echo "GATE:  $*"; }
has()     { command -v "$1" >/dev/null 2>&1; }

# Per-stack exit report state (n/a = marker absent, never enforced)
LAR_LINT="n/a"; LAR_TEST="n/a"
NODE_LINT="n/a"; NODE_TEST="n/a"
PY_LINT="n/a"; PY_TEST="n/a"
FL_LINT="n/a"; FL_TEST="n/a"
RS_LINT="n/a"; RS_TEST="n/a"
GO_LINT="n/a"; GO_TEST="n/a"

if ! has git; then
  block "git not available - fail-closed: cannot verify the change set."
  echo "RESULT: BLOCK"; exit 1
fi

scan_added_lines_label=""
scan_added_lines_n=0
scan_one(){ # $1=label, $2=line content
  local file="$1" line="$2"
  case "$file" in
    .agents/*|*.md) return 0 ;;
  esac
  local n="$scan_added_lines_n"
  case "$line" in
    *"npm run"*|*"npm install"*|*"yarn add"*|*"yarn install"*|*"bun add"*|*"bun install"*)
      block "$file (~added $n): Non-pnpm command detected ($line). Use pnpm exclusively." ;;
  esac
  case "$line" in
    *'->forceDelete()'*|*"DROP TABLE"*|*"TRUNCATE TABLE"*)
      case "$file" in
        *migration*) ;;
        *) block "$file (~added $n): High-risk destructive operation ($line). Soft delete or explicit dev approval required." ;;
      esac ;;
  esac
}
scan_begin(){ scan_added_lines_n=0; scan_added_lines_label="$1"; }
scan_line(){ scan_added_lines_n=$((scan_added_lines_n + 1)); scan_one "$scan_added_lines_label" "$1"; }

# 1. Change-set acquisition (FAIL-CLOSED)
HAS_HEAD=0
if git rev-parse -q --verify HEAD >/dev/null 2>&1; then HAS_HEAD=1; fi

FILES=()
if [ "$HAS_HEAD" = "1" ]; then
  TRACKED_REVISION_="$(git diff HEAD --name-only 2>/dev/null)"
  if [ $? -ne 0 ]; then
    block "git diff HEAD failed - fail-closed: cannot verify the change set."
  else
    while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done <<<"$TRACKED_REVISION_"
  fi
else
  note "No commits yet (no HEAD) - entire worktree is treated as new content."
fi

UNTRACKED_REVISION_="$(git ls-files --others --exclude-standard 2>/dev/null)"
if [ $? -ne 0 ]; then
  block "git ls-files failed - fail-closed: cannot list untracked files."
else
  while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done <<<"$UNTRACKED_REVISION_"
fi

# dedupe (bash 3.2-safe: no mapfile / process substitution)
if [ "${#FILES[@]}" -gt 0 ]; then
  DEDUPED="$(printf '%s\n' "${FILES[@]}" | awk '!seen[$0]++' || true)"
  FILES=()
  while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done <<<"$DEDUPED"
fi

# 1a. Banned files anywhere in the change set (secrets, binary DBs, foreign lockfiles)
for f in ${FILES[@]+"${FILES[@]}"}; do
  [ "$f" = ".env.example" ] && continue
  case "$f" in
    .env*|*.sqlite|*.sqlite3|*.db|package-lock.json|yarn.lock|bun.lockb)
      block "$f in change set -- banned from commit (secrets, binary DB, or non-pnpm lockfile)." ;;
  esac
done

# 2. Strict PNPM + destructive-op scan on added content
for f in ${FILES[@]+"${FILES[@]}"}; do
  if [ ! -e "$f" ]; then continue; fi # deleted file - name already banned-checked above
  TRACKED_F=1
  if [ "$HAS_HEAD" = "1" ]; then
    git ls-files --error-unmatch -- "$f" >/dev/null 2>&1 || TRACKED_F=0
  else
    TRACKED_F=0
  fi
  scan_begin "$f"
  if [ "$TRACKED_F" = "1" ]; then
    ADDED_OUT="$(git diff HEAD -U0 -- "$f" 2>/dev/null)"
    if [ $? -ne 0 ]; then
      block "git diff -U0 failed for $f - fail-closed."
      continue
    fi
    if [ -n "$ADDED_OUT" ]; then
      ADDED_PLAIN="$(printf '%s\n' "$ADDED_OUT" | grep '^+' | grep -v '^+++' | cut -c2-)"
      if [ -n "$ADDED_PLAIN" ]; then
        while IFS= read -r line; do scan_line "$line"; done <<<"$ADDED_PLAIN"
      fi
    fi
  else
    if [ -f "$f" ]; then
      while IFS= read -r line; do scan_line "$line"; done <"$f"
    fi
  fi
done

# 3. Linter Gate (per-stack detection)
echo "--- Linter Gate ---"

# 3a. Laravel -- Pint
if [ -f vendor/bin/pint ]; then
  if has php; then
    if php vendor/bin/pint --dirty --format agent; then LAR_LINT="ran ok"; else LAR_LINT="FAILED"; block "Pint linter failed."; fi
  else
    LAR_LINT="skipped (php missing)"
    note "Laravel Pint present but 'php' is not on PATH - lint skipped."
  fi
fi

# 3b. Node / TypeScript -- pnpm lint
if [ -f package.json ]; then
  if grep -q '"lint"' package.json; then
    if has pnpm; then
      if pnpm run lint; then NODE_LINT="ran ok"; else NODE_LINT="FAILED"; block "pnpm lint failed."; fi
    else
      NODE_LINT="skipped (pnpm missing)"
      note "package.json declares a lint script but 'pnpm' is not on PATH - lint skipped."
    fi
  fi
fi

# 3c. Python -- ruff (uv-wrapped preferred)
PYTHON_MARK=0
[ -f pyproject.toml ] && PYTHON_MARK=1
[ -f requirements.txt ] && PYTHON_MARK=1
if [ "$PYTHON_MARK" = "1" ]; then
  if has ruff || has uv; then
    if [ -f pyproject.toml ] && has uv; then
      if uv run ruff check .; then PY_LINT="ran ok"; else PY_LINT="FAILED"; block "ruff check failed (uv run)."; fi
    else
      if ruff check .; then PY_LINT="ran ok"; else PY_LINT="FAILED"; block "ruff check failed."; fi
    fi
  else
    PY_LINT="skipped (ruff/uv missing)"
    note "Python detected but neither 'ruff' nor 'uv' is on PATH - lint skipped (agents: use 'uv run ruff check .')."
  fi
fi

# 3d. Flutter / Dart -- dart format (check-only) + flutter analyze
if [ -f pubspec.yaml ]; then
  if has dart && has flutter; then
    if dart format --set-exit-if-changed --output=none .; then FMT_OK=1; else FMT_OK=0; fi
    if [ "$FMT_OK" = "1" ] && flutter analyze; then
      FL_LINT="ran ok"
    else
      FL_LINT="FAILED"
      block "dart format / flutter analyze failed - run 'dart format .' locally then re-check."
    fi
  else
    FL_LINT="skipped (dart/flutter missing)"
    note "Flutter detected but 'dart'/'flutter' not on PATH - lint skipped."
  fi
fi

# 3e. Rust -- cargo fmt --check
if [ -f Cargo.toml ]; then
  if has cargo; then
    if cargo fmt --check; then RS_LINT="ran ok"; else RS_LINT="FAILED"; block "cargo fmt --check failed - run 'cargo fmt' locally."; fi
  else
    RS_LINT="skipped (cargo missing)"
    note "Rust detected but 'cargo' is not on PATH - lint skipped."
  fi
fi

# 3f. Go -- gofmt -l
if [ -f go.mod ]; then
  if has gofmt; then
    UNFMT="$(gofmt -l . 2>/dev/null || true)"
    if [ -n "$UNFMT" ]; then
      GO_LINT="FAILED"
      block "gofmt: files need formatting:" 
      while IFS= read -r g; do [ -n "$g" ] && block "  - $g"; done <<<"$UNFMT"
    else
      GO_LINT="ran ok"
    fi
  else
    GO_LINT="skipped (gofmt missing)"
    note "Go detected but 'gofmt' is not on PATH - lint skipped."
  fi
fi

# 4. Test Gate (per-stack; narrower first when changed test files are known)
echo "--- Test Gate ---"

# 4a. Laravel -- artisan test
if [ -f artisan ]; then
  if has php; then
    if [ -n "$TESTFILTER" ]; then
      if php artisan test --compact --filter="$TESTFILTER"; then LAR_TEST="ran ok (filter)"; else LAR_TEST="FAILED"; block "Tests failed."; fi
    else
      ran_any=0
      failed=0
      for f in ${FILES[@]+"${FILES[@]}"}; do
        case "$f" in
          tests/*.php)
            ran_any=1
            if ! php artisan test --compact "$f"; then failed=1; block "Tests failed in $f."; fi ;;
        esac
      done
      if [ "$failed" = "1" ]; then LAR_TEST="FAILED"
      elif [ "$ran_any" = "1" ]; then LAR_TEST="ran ok (narrow)"
      else
        if php artisan test --compact; then LAR_TEST="ran ok (full)"; else LAR_TEST="FAILED"; block "Tests failed."; fi
      fi
    fi
  else
    LAR_TEST="skipped (php missing)"
    note "Laravel detected but 'php' is not on PATH - tests skipped."
  fi
fi

# 4b. Node / TypeScript -- pnpm test
if [ -f package.json ] && grep -q '"test"' package.json; then
  if has pnpm; then
    if [ -n "$TESTFILTER" ]; then
      if pnpm test -- "$TESTFILTER"; then NODE_TEST="ran ok"; else NODE_TEST="FAILED"; block "pnpm test failed."; fi
    else
      if pnpm test; then NODE_TEST="ran ok"; else NODE_TEST="FAILED"; block "pnpm test failed."; fi
    fi
  else
    NODE_TEST="skipped (pnpm missing)"
    note "package.json declares a test script but 'pnpm' is not on PATH - tests skipped."
  fi
fi

# 4c. Python -- pytest (narrower by changed tests/*.py; uv-preferred with pyproject.toml)
if [ "$PYTHON_MARK" = "1" ]; then
  if has pytest || has uv; then
    PYTEST_ARGS=()
    for f in ${FILES[@]+"${FILES[@]}"}; do
      case "$f" in
        tests/*|test/*) case "$f" in *.py) PYTEST_ARGS+=("$f") ;; esac ;;
      esac
    done
    if [ -f pyproject.toml ] && has uv; then
      if [ -n "$TESTFILTER" ]; then
        uv run pytest -k "$TESTFILTER"; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (filter)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) - TDD requires a failing-first test; add at least one pytest test."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC) (uv run)."; fi
      elif [ ${#PYTEST_ARGS[@]} -gt 0 ]; then
        uv run pytest "${PYTEST_ARGS[@]}"; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (narrow)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) in the changed test files - TDD requires a failing-first test."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC) (uv run)."; fi
      else
        uv run pytest; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (full)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) - project has no tests yet; TDD requires at least one."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC) (uv run)."; fi
      fi
    else
      if [ -n "$TESTFILTER" ]; then
        pytest -k "$TESTFILTER"; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (filter)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) - TDD requires a failing-first test; add at least one pytest test."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC)."; fi
      elif [ ${#PYTEST_ARGS[@]} -gt 0 ]; then
        pytest "${PYTEST_ARGS[@]}"; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (narrow)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) in the changed test files - TDD requires a failing-first test."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC)."; fi
      else
        pytest; RC=$?
        if [ $RC -eq 0 ]; then PY_TEST="ran ok (full)"
        elif [ $RC -eq 5 ]; then PY_TEST="FAILED"; block "pytest collected no tests (exit 5) - project has no tests yet; TDD requires at least one."
        else PY_TEST="FAILED"; block "pytest failed (exit $RC)."; fi
      fi
    fi
  else
    PY_TEST="skipped (pytest/uv missing)"
    note "Python detected but neither 'pytest' nor 'uv' is on PATH - tests skipped (agents: use 'uv run pytest')."
  fi
fi

# 4d. Flutter -- flutter test
if [ -f pubspec.yaml ]; then
  if has flutter && has dart; then
    ran_any=0; failed=0
    for f in ${FILES[@]+"${FILES[@]}"}; do
      case "$f" in
        test/*_test.dart|test/*/*_test.dart)
          ran_any=1
          if ! flutter test "$f"; then failed=1; block "flutter test failed in $f."; fi ;;
      esac
    done
    if [ "$failed" = "1" ]; then FL_TEST="FAILED"
    elif [ "$ran_any" = "1" ]; then FL_TEST="ran ok (narrow)"
    else
      if flutter test; then FL_TEST="ran ok (full)"; else FL_TEST="FAILED"; block "flutter test failed."; fi
    fi
  else
    FL_TEST="skipped (flutter missing)"
    note "Flutter detected but 'flutter' is not on PATH - tests skipped."
  fi
fi

# 4e. Rust -- cargo test
if [ -f Cargo.toml ]; then
  if has cargo; then
    if [ -n "$TESTFILTER" ]; then
      if cargo test "$TESTFILTER"; then RS_TEST="ran ok (filter)"; else RS_TEST="FAILED"; block "cargo test failed."; fi
    else
      if cargo test; then RS_TEST="ran ok (full)"; else RS_TEST="FAILED"; block "cargo test failed."; fi
    fi
  else
    RS_TEST="skipped (cargo missing)"
    note "Rust detected but 'cargo' is not on PATH - tests skipped."
  fi
fi

# 4f. Go -- go test ./...
if [ -f go.mod ]; then
  if has go; then
    if [ -n "$TESTFILTER" ]; then
      if go test -run "$TESTFILTER" ./...; then GO_TEST="ran ok (filter)"; else GO_TEST="FAILED"; block "go test failed."; fi
    else
      if go test ./...; then GO_TEST="ran ok (full)"; else GO_TEST="FAILED"; block "go test failed."; fi
    fi
  else
    GO_TEST="skipped (go missing)"
    note "Go detected but 'go' is not on PATH - tests skipped."
  fi
fi

# 5. No-surface honesty note (only when the repo matches NO supported stack)
SURFACES=0
for m in artisan package.json pyproject.toml requirements.txt pubspec.yaml Cargo.toml go.mod; do
  [ -e "$m" ] && SURFACES=1
done
if [ "$SURFACES" = "0" ]; then
  note "No supported stack surface found -> lint/test gates skipped by design (see .agents/rules.md)."
fi

# 6. Gate Report (definitive per-stack states for the coder report)
echo "--- Gate Report ---"
report "LARAVEL : lint=$LAR_LINT | test=$LAR_TEST"
report "NODE/TS : lint=$NODE_LINT | test=$NODE_TEST"
report "PYTHON  : lint=$PY_LINT | test=$PY_TEST"
report "FLUTTER : lint=$FL_LINT | test=$FL_TEST"
report "RUST    : lint=$RS_LINT | test=$RS_TEST"
report "GO      : lint=$GO_LINT | test=$GO_TEST"

if [ "$FAIL" = "1" ]; then
  echo "RESULT: BLOCK"; exit 1
else
  echo "RESULT: GREEN"; exit 0
fi
