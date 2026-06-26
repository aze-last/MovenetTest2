# CellWatch AI: Coordinator Manifest & Project Context

## 🛑 MANDATORY: Skill & Agent Activation
**Before performing ANY task**, you MUST:
1.  **Activate Expertise**: Activate the `cellwatch-expert` skill (`activate_skill(name='cellwatch-expert')`) to access institutional guardrails.
2.  **Invoke Agent Roles**: Adhere to the relevant worker role from the `.agent-team` orchestration framework:
    *   **Coordinator**: **THIS FILE (GEMINI.md)** is your template. Focus on orchestration, task management, and project-wide integrity.
    *   **MoveNet-Specialist**: Consult `.agent-team/templates/movenet-specialist.md` for human posture, concealment logic, and motion gating.
    *   **YOLO-Specialist**: Consult `.agent-team/templates/yolo-specialist.md` for object/contraband detection and custom model tuning.
    *   **State & Identity Manager**: Consult `.agent-team/templates/state-identity-manager.md` for `app_state.db`, settings, auth, and branding.
    *   **Incident & Ops Analyst**: Consult `.agent-team/templates/incident-operations-analyst.md` for video buffering, `incidents.db`, and reports.
    *   **Logic-Reviewer**: Consult `.agent-team/templates/logic-reviewer.md` for general backend logic tasks.
    *   **UI/UX Auditor / Redesigner**: Consult `.agent-team/templates/ui-ux-auditor-redesigner.md` for general frontend updates.
3.  **Consult Workflows**: Read the relevant workflow reference in the `cellwatch-expert` skill (e.g., `references/ai.md`) before writing any code.

## 👑 Coordinator Objectives & Rules
**Objective**: Coordinate engineering work while strictly maintaining architectural integrity, thread safety, and the "Institutional Dark" aesthetic.

**Core Rules**:
- **Bounded Tasks**: Assign one bounded task at a time and keep state current in `.agent-team/tasks`.
- **Scope Control**: Approve scope changes explicitly; prevent "feature creep" that risks UI blocking.
- **Risky Files**: Protect `app_state.db`, `auth.py`, and `profile_store.py` from unauthorized edits.
- **Verification**: Every logical change must be verified with `run_test.ps1` or manual module execution before closure.
- **Thread Safety**: Strictly enforce that no AI inference or database I/O happens on the main GUI thread.

## Project Overview
CellWatch AI is an institutional security monitoring system designed for real-time behavior analysis and contraband detection. It leverages computer vision and pose estimation to enhance safety in high-security environments.

*   **Tech Stack**: Python 3.10+, CustomTkinter (UI), SQLite3 (Database), OpenCV (Video).
*   **AI Engines**: MoveNet (TensorFlow) for pose estimation, YOLOv8 (PyTorch/Ultralytics) for object detection.

## Core Architectural Workflows
The project is divided into 6 decoupled workflows. Ensure any modifications respect these boundaries:

1.  **Application Setup & Authentication**: System startup, database initialization, and user security.
    *   *Key Files*: `monitor_app/main.py`, `monitor_app/auth.py`, `monitor_app/profile_store.py`, `monitor_app/utils.py`.
    *   *Logic*: `profile_store.ensure_app_state()` must run at startup. `auth.py` handles the 50/50 split login UI. `utils.py` contains shared UI constants (`WINDOW_SIZE`) and `apply_dark_theme`.
2.  **UI Navigation, Dashboard & Settings**: Navigation routing, hardware metrics, and system configuration.
    *   *Key Files*: `monitor_app/main.py`, `monitor_app/dashboard.py`, `monitor_app/settings.py`.
    *   *Logic*: `CellWatchApp` (in `main.py`) manages `switch_screen`. `dashboard.py` uses `psutil` for health metrics. `settings.py` manages user profiles and system branding.
3.  **Video Capture & Display**: Threaded OpenCV capture and UI frame rendering (~30FPS).
    *   *Key Files*: `monitor_app/camera_view.py`.
    *   *Logic*: Each camera runs in a dedicated `threading.Thread`. Frames are converted from BGR (OpenCV) to RGB (PIL/Tkinter). Graceful fallback to "Signal Lost" placeholder on disconnect.
4.  **AI Inference & Detection**: Human posture tracking and contraband detection with "Motion Gating" optimization.
    *   *Key Files*: `monitor_app/ai_engine.py`, `monitor_app/movenet_tuner.py`.
    *   *Logic*: Uses `BasicMotionEngine` as a gate. Heavy AI (MoveNet/YOLO) only triggers if motion exceeds threshold. `movenet_tuner.py` is used for calibrating confidence and behavior thresholds.
5.  **Incident Recording & Buffering**: Pre-roll buffering (deque) and automated evidence clipping (.mp4).
    *   *Key Files*: `monitor_app/incident_record.py`.
    *   *Logic*: Maintains a `collections.deque` for pre-roll (5s). `IncidentRecorder` handles state transitions from `BUFFERING` to `RECORDING` based on AI triggers.
6.  **Incident Review & Reporting**: Event logging, confidence scoring, and operational digest generation.
    *   *Key Files*: `monitor_app/incidents.py`, `monitor_app/reports.py`, `monitor_app/alerts.py`.
    *   *Logic*: Reads from `incidents.db`. Supports filtering by "Confirmed" or "False Alarm" status. `reports.py` generates operational digests.

## Critical Architectural Rules

### 1. Dual Databases
There is a strict separation between configuration and event data.
*   **`app_state.db`**: Stores system settings, user credentials, and branding. Managed by `profile_store.py`. Now also includes the `ai_settings` table for persisting the AI Detection Profile (High, Medium, Low, Custom) and custom threshold values.
*   **`incidents.db`**: Stores AI event logs and metadata. Managed by `incidents.py`.
*   *Constraint*: Agents working on user/system state MUST NOT touch the incident database, and vice-versa.

### 2. Thread Safety & UI Responsiveness
*   **Rule**: The main UI thread must never be blocked by video processing, heavy I/O, or AI inference.
*   **Implementation**: `camera_view.py` and `incident_record.py` must use dedicated `threading.Thread` loops. Use `time.sleep()` in loops to prevent CPU saturation.

### 3. Hardware Dependencies & Fallbacks
*   **Rule**: The application must gracefully handle varying hardware capabilities (CPU vs. GPU) and missing model files.
*   **Implementation**: `ai_engine.py` must maintain robust try/except blocks and provide fallback to `BasicMotionEngine` when heavy models fail to load.

### 4. UI Consistency & Limitations
*   **Rule**: Adhere to the "Institutional Dark" aesthetic.
*   **Implementation**: Always use `self.NAV_PALETTE` in `main.py` for navigation elements and the `PALETTE` in `dashboard.py`/`settings.py` for screen-specific widgets.
*   **Restriction**: Do NOT use `letter_spacing` in CustomTkinter widgets as it is unsupported in this environment and will cause errors.

## AI Threshold Reference

### MoveNet Behavior Thresholds (`ai_engine.py` → `_set_logic_sensitivity()`)

| Threshold | `high` | `medium` (default) | `low` (initial theoretical) | Purpose |
|---|---|---|---|---|
| `CONF_THR` | 0.25 | 0.22 | 0.18 | Keypoint confidence cutoff |
| `AGG_THR` | 450.0 px/sec | 180.0 px/sec | 700.0 px/sec | Aggressive / Fighting trigger |
| `ACTIVE_THR` | 140.0 px/sec | 90.0 px/sec | 250.0 px/sec | Fast Movement trigger |
| `ALERT_FRAMES` | 2 | 3 | 5 | Consecutive frames before alert |
| `motion_threshold` | 4500 | 5000 | 6000 | Min non-zero pixels to gate AI |
| `motion_ratio` | 0.009 | 0.010 | 0.012 | Adaptive gate (frame_w × frame_h × ratio) |

**Hardcoded values in `ai_engine.py`:**
- Person detection confidence: `> 0.2` (mean keypoint conf, L310)
- Skeleton draw / edge confidence: `> 0.3` (L398–400)

### YOLOv8 Contraband Thresholds (`ai_engine.py` → `_run_yolo_logic()`)

| Class ID | Label | Confidence Threshold |
|---|---|---|
| 0 | knife | 0.30 |
| 1 | cellphone | 0.30 |

- Fallback threshold for unlisted classes: `0.50`
- Inference image size: `640`

### Tuner Thresholds (`movenet_tuner.py`, module-level constants)

Mirrors `high` sensitivity: `CONF_THR=0.25`, `AGG_THR=450.0`, `ACTIVE_THR=140.0`, `MOTION_THRESHOLD=4500`, `MOTION_RATIO=0.009`.

## Development Commands
*   **Run Application**: `powershell.exe -ExecutionPolicy Bypass -File .\run_app.ps1`
*   **Environment**: Uses `.venv310` virtual environment.
