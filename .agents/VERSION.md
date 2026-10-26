# Agentic Team Orchestrator — Version Manifest

> Version: v1.2.1
> Last Updated: 2026-10-26
> This file is the canonical, parseable version record for the kit. **Agents: read this FIRST** — before the README body, before installing, before editing anything.

## Parse Contract
- Exactly one line starts with `> Version: vMAJOR.MINOR.PATCH`. Agents compare it against their installed copy to decide which kit is newest.
- `.agents/CHANGELOG.md` (newest first) describes every change; its top entry must always match the current version.

## The Ascension Contract (applies to every AI agent AND human editor)
- **ANY content change** — new skill, edited role file, fixed script, README rewrite — bumps the version by exactly one increment **as part of that change**, never deferred to a later pass.
- Tier rules: **PATCH** (`v1.0.1 → v1.0.2`) for fixes, edits, and small additions (the default); **MINOR** for new skills, roles, or pipelines; **MAJOR** for breaking protocol changes.
- Every bump updates both `> Version:` and `> Last Updated:` lines and **prepends** a matching entry to `.agents/CHANGELOG.md` (newest first).

## One-Command Helper
```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File .agents\version-up.ps1 -Note "what changed"
# add  -Minor  or  -Major  for higher tiers; without flags the bump is PATCH
```
The helper rewrites the manifest lines and prepends the changelog entry in one shot. Manual edits to the same two files are equally valid.

## Unmarked Changes
If a human edits kit files manually without bumping, the **next AI agent that operates on this repo MUST**: notice the discrepancy, bump retroactively (PATCH), and log the entry as `unmarked change: <summary>` before continuing with its assigned work.

## Update Detection (installed projects)
1. Read the `> Version:` line in BOTH this source kit and the project's `.agents/VERSION.md`.
2. **Source > project** ⇒ re-run `install-team.ps1` / `install-team.sh` from the source kit. The whole-copy installer run IS the update — never hand-merge role files.
3. **Project > source** ⇒ someone modified the installed copy locally; ask the operator before overwriting anything.
4. Installers print the kit version on every run — treat that printed line as the sync receipt.



