# Changelog

## v1.2.1 - 2026-10-26
- Exempt .agents and markdown from diff-scan regex checks, and detect repo local virtualenv pytest

## v1.2.0 - 2026-10-25
- **Four new stack gates enforced** (closing PENDING A): **Python** (`ruff check .` uv-preferred + pytest, narrower on changed `tests*/**.py` / root `test_*.py`; pytest exit 5 = "no tests collected" gets a distinct TDD-mandated failure message), **Flutter** (`dart format --set-exit-if-changed --output=none .` check-only + `flutter analyze` + narrower `flutter test` on changed `*_test.dart`), **Rust** (`cargo fmt --check` + `cargo test`), **Go** (`gofmt -l .` + `go test ./...`). All filter-aware via `-TestFilter` / argv 1 where the tool supports it.
- **Bash twin `diff-scan.sh`**: full-parity port for Linux/macOS — identical contract, output text (BLOCK/NOTE/GATE/RESULT), and exit codes; bash-3.2-safe constructs; verified `bash -n` under git-bash and WSL bash, plus identical scenario outcomes through both twins. Installers print the per-OS gate command in the copy receipt.
- **Per-stack Gate Report**: every run ends with a `GATE:` summary per stack (`lint=... | test=...`: ran ok / FAILED / skipped (reason) / n/a) — honest exit reporting for any stack combination; also serves as the TypeScript exit report (TS rides the Node path via `package.json` scripts).
- **Tool-availability guards**: every runner (php, pnpm, ruff, uv, pytest, dart, flutter, cargo, gofmt, go) checked with `Get-Command`/`command -v` before invocation — missing toolchains degrade to explicit NOTEs, never undocumented failures.
- **No-surface honesty note widened**: fires only when NO stack marker exists (artisan/package.json/pyproject.toml/requirements.txt/pubspec.yaml/Cargo.toml/go.mod).
- **rules.md updated**: §1 adds per-stack allowed runners (`uv run pytest`, flutter/dart, cargo, go — npm/yarn/bun banned everywhere incl. script bodies); §5 Mechanical Pre-Flight Gate entry rewritten for the twin + six-stack scope.
- **README updated**: tree includes `diff-scan.sh`; Section 3 rule 5 rewritten (six gate-enforced stacks); top-claim parenthetical synced.
- **Acceptance protocol extended** (`REPAIR-CHECKLIST.md`): python-toolchain-gap scenario, narrower-pytest scenario (executed live with pytest 9.1.1), Node path scenario with real pnpm, and a both-twins output-parity requirement.

## v1.1.0 - 2026-10-25
- **diff-scan.ps1 hardened to FAIL-CLOSED**: git enumeration failures now BLOCK instead of silently scanning an empty change set (no more GREEN-on-error).
- **Untracked-file coverage**: `git ls-files --others --exclude-standard` is always merged into the change set; untracked `.env*` / lockfiles / violating content can no longer escape. Banned-name pattern widened to `.env*` (catches `.env5`-style variants).
- **Zero-commit repos**: no HEAD → whole worktree treated as new content; banned-file and added-content scans still run.
- **Tracked vs untracked content split**: tracked files scan added lines from `git diff -U0`; untracked files scan their full body as new content.
- **Stack-honesty notes**: absent Laravel/Node gate surface → explicit NOTE instead of silent skip; Flutter/Python/Rust/Go presence → explicit "NOT gate-enforced yet" NOTE.
- **Honest stack scope** (README §3 rule 5): officially gate-enforced stacks = **Laravel + Node.js/TypeScript**; other stacks tracked as pending, not falsely claimed.
- Added `.agents/REPAIR-CHECKLIST.md` — audit-driven register with done items, pending gate coverage (Python/Flutter/bash twin/Rust/Go), mods-parity "teeth" plan, and the re-runnable acceptance protocol.
- Added **Tool Degradation Matrix** to `autonomous-worker.md` (rtk / kiro-cli / agy / opencode fallbacks — role files are the contract, CLIs are interchangeable executors).
- Acceptance protocol executed: no-commit violations → BLOCK, untracked violations → BLOCK, clean tracked change → GREEN + NOTE (all previously-proven holes closed).

All notable changes to the Agentic Team Orchestrator kit. **Newest first.**
Every entry corresponds to a bump of `> Version:` in `.agents/VERSION.md`.

## v1.0.1 - 2026-10-25
- Added `.agents/skills/obsidian-second-brain/SKILL.md` — scaffolds an Obsidian-formatted second brain (`Notes/` vault) with note taxonomy, six templates, and a whole-crew routing table (planner briefs, coder instinct notes, verifier verdicts, crawler dossiers).
- Rerouted `wiki-keeper.md` task cards and decision logs into the vault (`Notes/10-Projects/<slug>/...`).
- Registered the skill in the coordinator roster (`autonomous-worker.md`).
- Introduced the kit version system: `.agents/VERSION.md` manifest, this changelog, and `version-up.ps1` bump helper.
- Installers (`install-team.ps1`, `install-team.sh`) now print the kit version after copying.
- README: added kit version badge, updated verification tree, and new Section 4 — "Kit Versioning & Update Protocol".

## v1.0.0 - 2026-10-25
- Initial kit: Tri-CLI pipeline (`kiro-cli` planner → `opencode` coder → `diff-scan.ps1` mechanical pre-gate → `agy` verifier), 10 bundled skills, subagent fleet, universal installation scripts, and standing rules in `.agents/rules.md` (rtk prefixing, strict pnpm, TDD RED→GREEN→IMPROVE, instinct-note gate, diff-only review, banned files).



