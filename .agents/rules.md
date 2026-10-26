# Universal Standing Rules (Single Source of Truth)

All roles and agents reference this file. Never paste copies into role files or task briefs.

## 1. CLI Discipline
- **RTK Prefixing**: Prefix ALL shell commands with `rtk` (e.g. `rtk git status`, `rtk pnpm test`, `rtk pnpm build`, `rtk cargo test`, `rtk php artisan test`).
- **Strict Package Manager**: Use `pnpm` exclusively for Node.js/TypeScript workflows (`pnpm add`, `pnpm run`, `pnpm dlx`). `npm`, `yarn`, and `bun` are strictly banned.
- **Non-Node Stack Runners**: Outside the Node ecosystem, each stack uses its own native toolchain as the sole allowed runner — Python: `uv run pytest` / `uv run ruff check .` (fall back to plain `pytest`/`ruff` when uv is absent), Flutter: `flutter`/`dart` CLI, Rust: `cargo`, Go: `go`/`gofmt`, PHP: `php artisan`/Pint. npm/yarn/bun remain banned everywhere, including scripts inside package.json.
- **Non-Interactive Execution**: Always pass non-interactive flags (e.g., `--no-interaction`, `-y`) to prevent hanging commands.

## 2. Engineering Discipline & TDD (ECC Standard)
- **TDD Contract**: Mandatory RED ➔ GREEN ➔ IMPROVE:
  1. RED: Write the failing test first (regression test for defects, unit/feature test for features). Verify it fails.
  2. GREEN: Implement minimal code to pass the test. Nothing extra.
  3. IMPROVE: Refactor, clean linter warnings, optimize structure.
- **Refactoring & Behavior Changes**: Confirm existing tests are green before refactoring, keep tests green throughout, and add affected tests for new behaviors.
- **Build Contract**: `PLAN.md` is the sole build source and execution contract for coders. High-level specs, checklists, or user requests feed the Planner, never the coder directly.

## 3. Continuous Learning (Instincts Engine)
- **Mandatory Instinct Notes**: Every bug, defect, or unexpected error fix MUST yield an instinct note in the fix report:
  ```text
  trigger: when <condition>
  action: <one-sentence actionable rule or mitigation>
  evidence: <what broke, file:line, counts>
  scope: project | global
  ```
- **Skill Promotion**: When an instinct pattern recurs or demonstrates standalone high value, draft or update a persistent skill in `.agents/skills/<slug>/SKILL.md` (or `~/.claude/skills/<slug>/SKILL.md`).
- **Gate Enforcement**: Reviewers and verifiers MUST fail/block any fix submission that lacks its required instinct note.

## 4. Codebase & Data Safety
- **No Hard Deletes**: Prefer soft deletion, archiving, or explicit user/dev approval. Never use hard deletes without justification.
- **Ship Bans**: Never stage or ship secrets (`.env*`), database binaries (`*.sqlite*`, `*.db`), credential dumps, or foreign lockfiles (`package-lock.json`, `yarn.lock`, `bun.lockb`).
- **Tree Verification**: Always verify `git status` before and after runs. Only files within the task's declared scope may be touched.

## 5. Review & Exit Loop Contracts
- **Mechanical Pre-Flight Gate**: The platform twin gate must pass GREEN (linters, tests, static guards) before any AI review — Windows: `.agents/team/diff-scan.ps1`, Linux/macOS: `.agents/team/diff-scan.sh`. Enforced stacks: Laravel/PHP, Node/TypeScript (pnpm scripts), Python (ruff+pytest, uv-preferred), Flutter (dart format/analyze + flutter test), Rust (cargo fmt --check/test), Go (gofmt -l/go test).
- **Diff-Only Review**: Verifiers inspect `git diff` only, never re-reading the entire repository.
- **Findings Gate**: Reviewers return findings as `[BLOCKING]` or `[ADVISORY]` with `file:line`.
  - `BLOCKING`: Fed back as a concise fix list (item + file:line + fix). Max 2 review cycles, then escalate to human dev.
  - `ADVISORY`: Recorded for tech-debt tracking, never causes an execution loop.
  - Exit = Deterministic scripts GREEN + Zero BLOCKING findings.
