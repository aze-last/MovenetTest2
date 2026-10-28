# PLAN.md — Beating Sound Alert Loop & Sustained Contraband ID Dismissal Monitoring

## 1. Spec & Objective
- **Problem:**
  1. **Transient Audio Alarm:** Currently, when an alert fires, `SoundAlertManager` plays a single brief beep. If the operator is attending to other tasks, this brief sound is easily missed. The operator requires a continuous rhythmic "beating" heartbeat pulse that loops persistently until dismissed.
  2. **False Positives from Light Sources & Alert Storms:** Stationary light-emitting objects (lights, reflections, glares, shiny surfaces) are frequently classified as `cellphone`. When the operator clicks "Dismiss", the UI banner closes for a fraction of a second, but on the very next frame, the same light source triggers `DECISION_TRIGGER` and `INCIDENT_START` all over again. The operator cannot dismiss that specific light source while it remains in view.
- **Solution & Invariants:**
  1. **Continuous Beating Audio Loop:** `SoundAlertManager` provides a thread-safe, non-blocking beating heartbeat pulse loop (`start_beating_loop`, `stop_beating_loop`) using native Windows `winsound.Beep` (double-thump cadence: 480 Hz / 440 Hz) that plays until the operator clicks "Dismiss".
  2. **Sustained Contraband Tracking by ID:** Contraband detections maintain a stable ID (`track_id` from ByteTrack or spatial grid key for untracked items).
  3. **ID-Specific Dismissal Registry:** Clicking "Dismiss" registers that `(camera_id, contraband_track_id)` as dismissed. While that specific ID continues to be seen or coasted within hysteresis TTL, it is suppressed from re-triggering alert banners or audio beeps.
  4. **New Detection Trigger Invariant:** If a *new* contraband detection with a different ID appears (or on another camera), it is NOT in the dismissed registry and immediately fires a new detection alert message and restarts the beating sound loop.
  5. **Visual Distinction:** Sustained dismissed items are rendered with muted styling (`[DISMISSED]`, gray border) so operators maintain visual observability without alarm fatigue.
  6. **Rule 8 (Dependency Freeze):** Zero new pip dependencies. Uses Python standard library `winsound` and `threading`.

---

## 2. Scoped Tasks

### T1 — Beating Sound Loop in `SoundAlertManager`
- **Surface:** `monitor_app/alert_manager.py`
- **Scope:**
  1. Add `_is_beating` flag, `_beating_thread`, and `_beating_lock` to `SoundAlertManager`.
  2. Implement `start_beating_loop(alert_id=None)`: launches a daemon background thread that generates a rhythmic double-pulse heartbeat (`winsound.Beep(480, 80)` -> pause `0.06s` -> `winsound.Beep(440, 100)` -> pause `0.65s`).
  3. Implement `stop_beating_loop()`: thread-safely sets `_is_beating = False` to terminate playback immediately.
  4. Implement `is_beating() -> bool`.
- **Test:** `tests/test_sound_alert_loop.py`
- **Gate:** Tests pass verifying loop start, non-blocking execution, and immediate stop.

### T2 — Sustained Contraband ID Tracking & Dismissal Registry
- **Surface:** `monitor_app/decision.py`
- **Scope:**
  1. Implement `ContrabandDismissalRegistry` singleton in `monitor_app/decision.py`:
     - Tracks `dismissed_tracks: Dict[str, Dict[Any, float]]` mapping `camera_id -> {track_id: timestamp_dismissed}`.
     - `dismiss_track(camera_id, track_id)`: registers dismissal.
     - `is_track_dismissed(camera_id, track_id) -> bool`: checks if track is active in dismissal window (TTL = 15.0s from last sighting).
     - `touch_track(camera_id, track_id)`: updates last seen timestamp for active dismissed track.
     - `prune_stale()`: cleans up tracks not seen for > 15s.
  2. In `DecisionEngine.evaluate_trigger(packet)`:
     - Filters contraband detections against `ContrabandDismissalRegistry`.
     - If all detected contraband items on the packet have been dismissed by the operator, suppress contraband trigger for this packet.
     - If a *new* or un-dismissed contraband ID is present, allow trigger and return `True`.
  3. Expose helper `get_dismissal_registry()`.
- **Test:** `tests/test_contraband_dismissal.py`
- **Gate:** Tests pass verifying sustained ID dismissal, suppression of dismissed contraband, and immediate triggering of new/different contraband IDs.

### T3 — Camera View & Banner Integration
- **Surface:** `monitor_app/camera_view.py`
- **Scope:**
  1. In `CameraMonitorScreen._show_alert_banner`:
     - Collects `active_contraband_track_ids` from `ai_results` or `packet.detections`.
     - Calls `get_sound_alert_manager().start_beating_loop(incident_id)`.
  2. In `CameraMonitorScreen._dismiss_alert_banner`:
     - Calls `get_sound_alert_manager().stop_beating_loop()`.
     - Calls `get_dismissal_registry().dismiss_track(camera_id, tid)` for each active contraband track.
  3. In `CameraMonitorScreen._review_active_incident` and `stop_monitoring`:
     - Calls `get_sound_alert_manager().stop_beating_loop()`.
  4. In `CameraFeedWidget` / BBox Drawing:
     - Check `is_track_dismissed(camera_id, track_id)`. If dismissed, render label as `f"{name.upper()} [DISMISSED]"` with muted border color (`#64748b`).
- **Test:** `tests/test_dismissal_ui_flow.py`
- **Gate:** Tests pass verifying dismissal banner, sound stop, and track dismissal integration.

### T4 — Mechanical Gate, Verification & Documentation
- **Surface:** `capstone_progress_report.md`, `changes_today.zip`
- **Scope:**
  1. Run `diff-scan.ps1` (all tests GREEN).
  2. Log all line numbers and purpose in `capstone_progress_report.md` (Section 22).
  3. Bundle modified files in `changes_today.zip`.
