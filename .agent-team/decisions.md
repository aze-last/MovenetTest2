# Agent Team Decisions - CellWatch AI

- **Runtime Mode**: `manual-session`
- **Shared Truth**: Task files in `.agent-team/tasks`
- **Transport**: Mailbox files in `.agent-team/mailbox`
- **Default Isolation**: Shared workspace with bounded file ownership.
- **Architectural Guardrail**: Never block the main Tkinter thread. UI responsiveness is priority #1.
- **Database Rule**: Config stays in `app_state.db`. Incident logs stay in `incidents.db`.
- **UI Constraint**: Do NOT use `letter_spacing` in any CustomTkinter widget (unsupported).
- **Verification Rule**: Every logical change must be verified with `run_test.ps1` (if available) or manual execution of the affected module.
- **Redesign Rule**: UI redesigns must adhere to the "Institutional Dark" palette defined in `utils.py` and `dashboard.py`.
