# Repair & Expansion Checklist (Audit-Driven)

Maintenance register for the kit. Every item below comes from the **2026-10-25 execution audit**
(diff-scan.ps1 was actually executed against sandbox git repos, not just read).
Policy: checkboxes change only together with a version bump (`.agents/VERSION.md`) and a
matching `.agents/CHANGELOG.md` entry. Agents: work top-down inside PENDING groups.

## Re-Run Acceptance Protocol (must pass after ANY gate change)

Run from any scratch dir; expected results are contractual:

```powershell
# Scenario 1: zero-commit repo with UNDERWAY violations -> must BLOCK
git init; Set-Content a.js "npm install x"; Set-Content .env.local "SECRET=1"; git add -N .
# expect EXIT 1 + BLOCK lines (was: silent GREEN before v1.1.0)

# Scenario 2: committed repo, untracked violations (no git add -N) -> must BLOCK
git commit once; Set-Content .env5 "PASSWORD=1"; Set-Content hack.js "yarn add x"
# expect EXIT 1 + BLOCK lines (was: silent GREEN before v1.1.0)

# Scenario 3: clean tracked change -> GREEN with coverage NOTE
Set-Content clean.js "console.log('ok')" (tracked edit)
# expect EXIT 0 + NOTE "No supported stack surface found..." when no stack marker
# (artisan/package.json/pyproject/requirements.txt/pubspec.yaml/Cargo.toml/go.mod) exists

# Scenario 4 (v1.2.0): pyproject.toml present but no ruff/pytest/uv/pytest toolchain gap
# expect: no crash; explicit NOTEs "skipped (ruff/uv missing)"; Gate Report shows states.
# With pytest present and no tests at all: exit 1 + "pytest collected no tests (exit 5)
# - TDD requires a failing-first test" (pytest exit 5 is deliberately a failure).

# Scenario 5 (v1.2.0): tests/test_demo.py changed -> narrower pytest runs exactly that
# file. expect Gate Report "ran ok (narrow)" (verified live, pytest 9.1.1).

# EVERY scenario must be executed through BOTH twins with matching output:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .agents\team\diff-scan.ps1
#   bash .agents/team/diff-scan.sh
```

---


## DONE — v1.1.0 repair pass (2026-10-25)

- [x] **diff-scan.ps1 fail-closed**: git failure (exit != 0) now BLOCKs instead of silently scanning an empty change set. No more GREEN-on-error.
- [x] **Untracked-file coverage**: `git ls-files --others --exclude-standard` is always merged into the change set. Untracked `.env*` / lockfiles / violating content can no longer escape (the critical hole proven in the audit).
- [x] **Zero-commit repos**: no HEAD -> whole worktree treated as new content; banned-file + content scans still run.
- [x] **Tracked vs untracked content split**: tracked files scan added lines from `git diff -U0`; untracked files scan their full body as new content.
- [x] **Stack-honesty notes**: Laravel/Node absence -> explicit NOTE instead of silent skip; Flutter/Python/Rust/Go presence -> explicit "NOT gate-enforced yet" NOTE.
- [x] **README scope corrected** (Section 3 rule 5): officially gate-enforced stacks = **Laravel + Node.js/TypeScript**; other stacks tracked here, not falsely claimed.
- [x] **Tool Degradation Matrix** added to `autonomous-worker.md` (rtk / kiro-cli / agy / opencode fallbacks).
- [x] **Acceptance protocol** codified in this file (above) and re-executed for this pass.

**Audit evidence recap (v1.0.1 gate, now fixed):**

| Scenario | Expected | v1.0.1 actual | v1.1.0 |
|---|---|---|---|
| No-commit repo + `.env.local` + `npm install` | BLOCK | GREEN ❌ | BLOCK ✅ |
| Untracked `.env5` + `yarn add` violation | BLOCK | GREEN ❌ | BLOCK ✅ |
| Files after `git add -N`, violating | BLOCK | BLOCK ✅ | BLOCK ✅ |


## DONE — v1.2.0 stack-gate expansion (2026-10-25)

- [x] **TypeScript (Node path) verified**: TS projects ride the Node path — any `package.json` with `"lint"`/`"test"` scripts (Vitest/Jest/ESLint configs resolve through them under pnpm). Verified live with real pnpm: lint ran; a script referencing a nonexistent command was caught as expected. TS-specific exit report = the per-stack `GATE:  NODE/TS : lint=... | test=...` lines.
- [x] **Python gate**: `pyproject.toml`/`requirements.txt` detection → `ruff check .` (uv-preferred) + pytest. Narrower test selection: changed `tests*/**.py` (any depth) or root `test_*.py` files run first. Agent invocation rule `uv run pytest` documented in `rules.md` §1. pytest exit 5 ("collected no tests") gets a distinct failure message tying it to the TDD contract. Verified live with real pytest 9.1.1: narrow run executed the changed test file (passed), full-run-with-no-tests blocked with the actionable message.
- [x] **Flutter gate**: `pubspec.yaml` detection → `dart format --set-exit-if-changed --output=none .` (check-only — never rewrites files) + `flutter analyze`; narrower `flutter test <changed _test.dart files>`. `flutter`/`dart` documented in `rules.md` as the allowed non-pnpm toolchain for this ecosystem.
- [x] **Bash twin `diff-scan.sh`**: full parity port (no Windows-specific constructs; bash 3.2-safe patterns). Identical contract, same BLOCK/NOTE/GATE/RESULT text, same exit codes. `bash -n` clean under both git-bash (Laragon git 2.x) and WSL bash; acceptance scenarios S1/S2/S3/S4/S5/S7 executed identically through both twins. Installers print the per-OS gate command in the copy receipt.
- [x] **Rust / Go gates**: `Cargo.toml` → `cargo fmt --check` + `cargo test` (optional filter); `go.mod` → `gofmt -l .` (any output = files listed, BLOCK) + `go test ./...` (optional `-run` filter). Bench-grade status: enforced whenever the toolchain is on PATH; NICEd as skipped with the exact gap when absent.
- [x] **Per-stack Gate Report**: every run ends with a `GATE:` line per stack (`lint=... | test=...` with states ran ok / FAILED / skipped (reason) / n/a) — the honest exit report for any stack combination, replacing ambiguous bare success.
- [x] **Tool-availability guards**: every runner invocation is gated by `Get-Command`/`command -v` (php, pnpm, ruff, uv, pytest, dart, flutter, cargo, gofmt, go) — missing toolchains degrade to explicit NOTEs instead of undocumented errors.
- [x] **No-surface honesty note widened**: fires only when NO supported stack marker exists at all (artisan/package.json/pyproject.toml/requirements.txt/pubspec.yaml/Cargo.toml/go.mod).


## PENDING B — Mods-parity "teeth" (mechanical enforcement, no harness abandonment)

- [ ] **OpenCode permissions**: deny-list `npm`, `yarn`, `bun` subprocess invocations at harness level (cannot run vs "please don't run").
- [ ] **OpenCode hooks**: PreToolUse-style hook invoking the diff-scan detection logic on shell commands — moves the rtk/pnpm/destructive regexes from prompt rules to mechanical interception.
- [ ] **Model routing policy**: cheap-tier routing contract for trivial ops (typos, renames, comments) in `kiro-planner.md`/coordinator — cost gap vs mods' Haiku routing.
- [ ] **Live squad dashboard**: decide OpenCode TUI plugin vs Claude Code mod for a status pane driven by the Obsidian vault task cards (`Notes/10-Projects/*/TODO-*.md` statuses).
- [ ] **Cross-session messaging** the coordinator's PLAN.md dispatch stays; evaluate Claude Code mods' session-push for Claude-Code-only legs (optional add-on, not a dependency).


## PENDING C — Kit polish (small, queue-able)

- [ ] `subagents/verifier.md`: axis list mismatch — output template shows "Maintainability" but defined axis 5 is "Continuous Learning" (audit finding; align naming).
- [ ] designer-worker/crawler skill cross-references: ensure each role file explicitly names which bundled skills it loads.
- [ ] `.agents/README` for operators: one-page "how the gates, vault, and versions interact" diagram (optional, nice for new agents).
- [ ] Consider secret-VALUE scan (regex for high-entropy strings) in diff-scan — today only file names are banned, content can still hold keys in non-`.env` files.
