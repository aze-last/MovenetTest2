# PLAN.md — Dual-Mode Institutional UI: Top Navigation, Dashboard & Incidents

## 1. Spec & Objective
- **Problem:** CellWatch AI's core operator interfaces ([`monitor_app/main.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/main.py), [`monitor_app/dashboard.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/dashboard.py), and [`monitor_app/incidents.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/incidents.py)) currently utilize single-mode dark hex palettes. Operators cannot toggle to Light Mode once logged in, violating duty-shift requirements and causing high eye fatigue in brightly illuminated administrative stations.
- **Hypothesis:** Upgrading navigation tokens and screen palettes to institutional dual-mode `(light_mode, dark_mode)` tuples, adding an omnipresent navigation Theme Toggle button, and configuring dynamic `ttk.Treeview` re-styling will enable 0ms light/dark switching across all views without layout degradation or UI crashes.
- **Invariants & Constraints:**
  - **CustomTkinter Rule:** Strict ban on `letter_spacing` or `kerning` (causes fatal runtime crash).
  - **Rule 1 (Threading):** Never block the UI thread during theme switches or telemetry probes.
  - **Rule 4 (Data Separation):** Operator theme selection is stored exclusively in `app_state.db` via `profile_store.set_appearance_mode()`.
  - **Zero CLS:** All card, vital, and status containers must maintain fixed proportions across theme shifts.
  - **WCAG 2.2 AA Contrast:** All text tokens must exceed 4.5:1 against their active surface in both modes.

---

## 2. Scoped Tasks

### T1 — Navigation Bar & App Shell Dual-Mode Theme Integration
- **Files:** [`monitor_app/main.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/main.py)
- **Scope:**
  1. Upgrade `NAV_PALETTE` in `CellWatchApp` to dual-mode `(light, dark)` tuples for `bar`, `bar_border`, `button`, `button_hover`, `active`, `active_hover`, `text`, `muted`, `warn`, and `warn_hover`.
  2. In `create_navigation()`, add `self._theme_btn` on the navigation bar (placed between `Tools ▾` and `Logout`) displaying `🌙 Dark` or `☀️ Light`.
  3. Implement `toggle_appearance_mode()` in `CellWatchApp` that updates `ctk.set_appearance_mode()`, saves to `profile_store.set_appearance_mode()`, updates button labels, and notifies the active screen (`apply_appearance_mode` if supported).
  4. Ensure `self.container` uses dual-mode background color `("#edf2f7", "#06090c")`.
- **Test:** Unit test verifying `_theme_btn` toggles `ctk.get_appearance_mode()` and updates `NAV_PALETTE` button states.
- **Gate:** `.agents/team/diff-scan.ps1` GREEN, `pytest tests/` passing.

### T2 — Dashboard Screen Dual-Mode Palette & Layout Refinement
- **Files:** [`monitor_app/dashboard.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/dashboard.py)
- **Scope:**
  1. Refactor `DashboardScreen.PALETTE` into dual-mode `(light, dark)` tuples:
     - `page`: `("#edf2f7", "#06090c")`
     - `panel`: `("#f8fafc", "#0f161f")`
     - `card`: `("#ffffff", "#151f2b")`
     - `border`: `("#cbd5e1", "#1e2c3a")`
     - `accent`: `("#1d4ed8", "#4f84bb")`
     - `text_main`: `("#0f172a", "#ffffff")`
     - `text_dim`: `("#334155", "#a2b5c7")`
     - `text_muted`: `("#64748b", "#7e94a8")`
  2. Update `_create_vitals_tile`: Configure `CTkProgressBar` with dual-mode `fg_color=self.PALETTE["page"]` and `progress_color` so track colors do not stay pitch black in light mode.
  3. Refine `corner_radius` on metric cards and panels to disciplined 12–14px institutional geometry.
  4. Ensure high contrast on bottom glow lines and activity ledger rows in light mode.
- **Test:** Unit test verifying `DashboardScreen` instantiates in both Light and Dark modes without missing token keys.
- **Gate:** `.agents/team/diff-scan.ps1` GREEN, `pytest tests/` passing.

### T3 — Incidents Screen Dual-Mode Palette, TreeView Re-styling & Ergonomics
- **Files:** [`monitor_app/incidents.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/incidents.py)
- **Scope:**
  1. Refactor module-level `PALETTE` into dual-mode `(light, dark)` tuples across all background surfaces, tab segments, cards, borders, text, and alert states.
  2. Implement `apply_appearance_mode()` on `IncidentsScreen` and `IncidentLogTable`:
     - Dynamically reconfigure `ttk.Style("Incidents.Treeview")` and `Incidents.Treeview.Heading` with light-mode backgrounds (`#ffffff`, `#e2e8f0`) and dark text (`#0f172a`) when in Light Mode, vs `#1b2430` / `#f3f7fb` when in Dark Mode.
  3. Ensure `_status_style(status)` yields high-contrast colors on both light and dark card backgrounds.
  4. Refine corner radii on header and summary cards from 24px/18px down to 14px.
  5. Ensure evidence video player frame maintains clean letterbox border in both modes.
- **Test:** Unit test validating `IncidentsScreen` tabview and treeview style configuration across appearance mode changes.
- **Gate:** `.agents/team/diff-scan.ps1` GREEN, `pytest tests/` passing.

### T4 — Verification & Test Suite
- **Files:** [`tests/test_dashboard_incidents_ui.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/tests/test_dashboard_incidents_ui.py)
- **Scope:**
  1. Test `CellWatchApp` navigation bar theme button and toggle execution.
  2. Test `DashboardScreen` metric updates and vitals progress bar configurations in Light and Dark modes.
  3. Test `IncidentsScreen` overview summaries, tab switching, and `ttk.Treeview` style reconfiguration across modes.
- **Gate:** Full test suite passes (all 100+ tests), gate GREEN, documentation in `capstone_progress_report.md` updated, and `changes_today.zip` updated.

---

## 3. Edge Cases & Safety
1. **Dynamic ttk Treeview Style Sharing:** Standard Tkinter ttk styles are global to the Tk interpreter. Changing `Incidents.Treeview` and `Accounts.Treeview` must not adversely affect other ttk widgets or crash on headless execution.
2. **Missing Video File in Incident Review:** If `video_path` does not exist on disk, playback must fail gracefully without resetting the theme state or throwing uncaught exceptions.
3. **Hardware Health Thread Safety:** `psutil` CPU/RAM/Disk calls in `update_system_health()` run on the scheduled Tk timer; verify they never freeze the UI during theme switching.
4. **Active Screen Redraw:** CustomTkinter widgets re-render automatically on appearance mode change, but the active navigation button highlight must preserve its bold active contrast in both modes.

---

## 4. Track 2 — Incident Page Background Defect, Reports & Settings Dual-Mode

### T5 — Incident Screen Background Bleed-Through Elimination
- **Files:** [`monitor_app/incidents.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/incidents.py), [`monitor_app/utils.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/utils.py)
- **Defect Analysis:** In Light Mode, `IncidentsScreen` outer margins, borders, and the background behind `CTkTabview` segmented buttons displayed pure black `#1e1e1e`. Cause: `IncidentsScreen` inherited from `ttk.Frame`, which uses Tkinter's `TFrame` style configured to `#1e1e1e` in `apply_dark_theme`.
- **Scope:**
  1. Change `IncidentsScreen` from `class IncidentsScreen(ttk.Frame)` to `class IncidentsScreen(ctk.CTkFrame)`. Initialize with `super().__init__(parent, fg_color=PALETTE["page"], corner_radius=0)`.
  2. In `monitor_app/utils.py`, implement `update_ttk_theme(root, mode)` to update `TFrame` and `TLabel` backgrounds to `#edf2f7` in Light Mode and `#06090c` in Dark Mode. Call this from `main.py` on startup and on appearance mode toggle.

### T6 — Reports Screen Dual-Mode Palette & Layout
- **Files:** [`monitor_app/reports.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/reports.py)
- **Scope:**
  1. Change `ReportsScreen` from `class ReportsScreen(ttk.Frame)` to `class ReportsScreen(ctk.CTkFrame)` with `fg_color=self.PALETTE["page"], corner_radius=0`.
  2. Convert `PALETTE` into dual-mode `(light, dark)` tuples for all tokens: `page`, `panel`, `panel_alt`, `card`, `card_soft`, `surface`, `paper`, `paper_border`, `paper_text`, `border`, `text`, `muted`, `subtle`, `accent`, `accent_hover`, `success`, `success_hover`, `warning`.
  3. Standardize corner radii (26/24/20px down to 14px).
  4. Update OptionMenu, Date Entries, CheckBoxes, and Preview Textbox to support dual-mode colors and high-contrast text.
  5. Implement `apply_appearance_mode()`.

### T7 — Settings Screen (Profile & Monitoring) Dual-Mode Palette & Table Re-styling
- **Files:** [`monitor_app/settings.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/settings.py)
- **Scope:**
  1. Convert `PALETTE` into dual-mode `(light, dark)` tuples for all tokens.
  2. Update `_build_account_directory_card`: Replace `table_wrap = tk.Frame(card, bg=PALETTE["panel"])` with `ctk.CTkFrame(card, fg_color="transparent")`.
  3. Update `_configure_tree_style()` and `account_tree.tag_configure("ACTIVE" / "DISABLED")` to resolve single hex colors depending on active appearance mode (`Light` vs `Dark`).
  4. Update `CTkTooltip` to dynamically adapt background and text colors to the active appearance mode.
  5. Implement `apply_appearance_mode()` to update `Accounts.Treeview` and table tags on theme toggle.

### T8 — Automated UI Tests & Mechanical Gate Verification
- **Files:** [`tests/test_reports_settings_ui.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/tests/test_reports_settings_ui.py)
- **Scope:**
  1. Test `ReportsScreen` palette tuples and instantiation.
  2. Test `SettingsScreen` (both `mode="profile"` and `mode="monitoring"`) palette tuples and treeview style updates.
  3. Run full test suite and `.agents/team/diff-scan.ps1`.

---

## 5. Track 3 — Production Dark Mode Architecture, Card Line Removal & Theme Icons

### T9 — Operational Status Cards Line Removal
- **Files:** [`monitor_app/dashboard.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/dashboard.py)
- **Scope:** Remove the bottom accent frame (`glow = ctk.CTkFrame(card, fg_color=accent, height=3, corner_radius=10)`) from each of the 4 operational status cards (`Active Feeds`, `Incidents`, `Live Alerts`, `System Uptime`). Eliminates harsh saturated bottom stripes that fight for visual attention, yielding clean, unpolluted surface cards.
- **Documentation Rationale (Rule: code removal must be documented):** The colored underline was originally a static visual decoration that introduced visual noise and competed with primary vital metrics. Removing it delivers a cleaner, institutional card aesthetic where status is conveyed by text hierarchy rather than arbitrary border striping.

### T10 — Dynamic Sun/Moon Theme Toggle Icons
- **Files:** [`monitor_app/utils.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/utils.py), [`monitor_app/main.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/main.py), [`monitor_app/auth.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/auth.py)
- **Scope:**
  1. In `monitor_app/utils.py`, implement `create_theme_icon(size=(20, 20))` using PIL with supersampled antialiasing to generate high-resolution `CTkImage` with a warm glowing sun for dark mode and sleek crescent moon for light mode.
  2. In `monitor_app/main.py`, mount the theme icon onto `self._theme_btn` on the top navigation bar with streamlined geometry (`width=44, height=40, text=""`) so it functions as a modern, un-clipped institutional toolbar icon button.
  3. In `monitor_app/auth.py`, mount the theme icon onto `self.btn_theme_toggle`.

### T11 — Comprehensive 6-Pillar Dark Mode Architecture Guide
- **Scope:** Provide production-grade implementation guide and Tailwind CSS / CSS custom properties covering:
  1. Near-Black Surface & Layering Strategy (stepped elevations)
  2. Elevation via Lightness (ambient surface lifting over dark drop shadows)
  3. Multi-Tier Text Opacity (single variable, 87% / 60% / 38% alphas)
  4. Calming Brand Accents (desaturated, luminous hues)
  5. Alpha Hairline Borders (1px white @ 8% alpha)
  6. Image & Illustration Dimming (0.9 brightness + dark SVGs)

### T12 — Verification & Mechanical Gate
- **Scope:** Run automated tests in `.venv310`, run `.agents/team/diff-scan.ps1`, update `capstone_progress_report.md` and `changes_today.zip`.

