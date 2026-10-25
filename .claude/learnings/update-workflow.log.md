# Learnings log — self-updating-desktop-workflow (build-fix Essex loop)

Purpose: every build/test failure hit during Milestones 2–3 gets a one-block entry
here (symptom → root cause → fix → prevention) so the next conversation starts
with the solution, not the error. Appended by the orchestrator after each fix.

Format per entry:
## YYYY-MM-DD — <short symptom>
- Symptom: (failing command + error excerpt)
- Root cause:
- Fix: (files + lines)
- Prevention:

---
## 2026-10-08 — Commit round: two silent failures, both process bugs
- Symptom 1: commit chain did nothing (log unchanged, cache empty), no error shown.
  Root cause: `git check-ignore` exits 1 when a file is NOT ignored, and it sat
  inside an `if ($?)` chain — every step after it was skipped silently.
  Fix: diagnostics (check-ignore, grep) on `;`, never inside `if ($?)` gates.
- Symptom 2: .gitignore edit reported success but the rule wasn't in the file
  (concurrent writer clobbered it or stale-base apply).
  Fix: always read-back-verify edits (`Select-String`) before relying on them,
  especially on a shared tree. Re-applied + verified via check-ignore exit 0.
- Prevention: gate commits on explicit-path adds only (no `git add -A` near
  multi-GB artifacts); confirm ignore rules with check-ignore before staging.

## 2026-10-08 — M2 fix pass: clean (no new build problems)
- Symptom: none — 12 new + 2 tightened tests went RED→GREEN first try; 110 passed.
- Note: `tests/test_installer_prereqs.py::test_subsystem_contract` already expected `config.yaml::max_installer_bytes` — cross-track test foresight confirmed the key name before M2 added it.
- Prevention: n/a.

## 2026-10-08 — M2: foreign edits appeared mid-track (concurrent-editor collision)
- Symptom: `git status` during M2 showed unplanned `M CellWatch.spec, hooks/hook-tensorflow.py, monitor_app/__init__.py (__version__ 0.1.0→1.0.0), monitor_app/ai_engine.py (get_models_dir), monitor_app/utils.py (data_path→LocalAppData)` — none from M2 prompts; content matches the installer-track plan (T5/T6/slimming), i.e. the other AI is editing the SAME tree live.
- Root cause: two agents, one working tree, no branch/worktree separation.
- Fix: STOPPED M2 Gate 2 (no commit into dirty tree). Reverted utils.py via `git checkout --` to protect M2 scope — but that DESTROYED the other track's uncommitted T5 work.
- Prevention: (1) NEVER `git checkout --` foreign changes — `git stash push -m <track>` preserves them. (2) One agent per worktree/branch; check `git status` BEFORE dispatching subagents and AFTER each return. (3) Ask user to confirm tree ownership when foreign diffs appear.

## 2026-10-08 — M2: suite-count drift is state-dependence, not flakiness
- Symptom: full-suite totals read 65 → 63 → 77 → 84 → 87 across runs/agents.
- Root cause (partial): test files for the active slice grow the total (expected); `test_codebase_integrity.py` parametrizes over repo contents so counts move as files are added. Compare PER-FILE counts (`--collect-only` grouped), never raw totals.
- Prevention: record per-file collect counts at RED time; treat ±N drift as signal to diff the file list, not rerun blindly.

## 2026-10-08 — Milestone 1 (carried over, no new failures)
- Symptom: none — 65 passed at commit; pytest-cov absent so no coverage % number.
- Prevention: add pytest-cov to dev requirements before enforcing coverage gates.
