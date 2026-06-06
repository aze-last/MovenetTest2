# Agent Team Runtime - CellWatch AI Edition

Repo-local coordinator-plus-workers runtime for engineering work on this repository.

## Purpose

- keep task ownership explicit
- preserve the "Institutional Dark" aesthetic while implementing changes
- verify work (AI inference, DVR, UI) before completion
- avoid accidental edits to risky files (e.g., `app_state.db`, `auth.py`)

## Shared State

- team config: `.agent-team/team.json`
- decision log: `.agent-team/decisions.md`
- task board: `.agent-team/tasks/*.json`
- mailbox transport: `.agent-team/mailbox/`
- worker role prompts: `.agent-team/templates/*.md`

## Workflow Standards

1. **Safety First**: Never block the main Tkinter thread with AI or I/O.
2. **Database Separation**: Respect the boundary between `app_state.db` (Config) and `incidents.db` (Logs).
3. **Hardware Agnostic**: Ensure fallbacks for AI models (BasicMotionEngine) are always functional.
4. **UI Consistency**: No `letter_spacing` in CustomTkinter. Use established `PALETTE` and `NAV_PALETTE`.

## Specialized Workers

- **Coordinator**: Orchestrates tasks and ensures architectural alignment.
- **Logic-Reviewer**: Validates AI inference states, motion gating, and recording workflows.
- **UI/UX Auditor**: Critically evaluates the CustomTkinter interface against institutional standards.
