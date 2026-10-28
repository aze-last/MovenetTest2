import os

section_22 = """

---

## 22. Beating Sound Alert Loop & Sustained Contraband Track ID Dismissal Monitoring
- **Objective & Scope:**
  - Resolved the alert fatigue problem where stationary light-emitting or reflective objects (lamps, reflections, glare) are classified as contraband (e.g. `cellphone`) and re-trigger an alarm immediately after the operator clicks "Dismiss".
  - Implemented sustained contraband track ID persistence and an operator dismissal registry so dismissed detections remain silenced as long as they are sustained in view, while any *new* contraband detection immediately triggers a fresh alert.
  - Implemented a continuous, rhythmic "beating" heartbeat audio alarm pulse (`winsound.Beep` double-thump: 480 Hz / 440 Hz) that loops persistently until the operator dismisses the detection.
  - Added visual observability: dismissed contraband items render with muted slate-gray bounding boxes and `[DISMISSED]` labels so operators know the system is monitoring the object without triggering alerts.

- **Detailed Line-by-Line Changes:**
  1. `monitor_app/alert_manager.py`:
     - Lines 27–34 (`SoundAlertManager.__init__`):
       - Added `self._is_beating = False`, `self._beating_thread = None`, `self._beating_lock = threading.Lock()`, and `self.active_alert_id = None`.
       - Purpose: Maintains state for the continuous beating sound loop.
     - Lines 87–145 (`SoundAlertManager` Loop API):
       - Added `is_beating(self) -> bool`: Thread-safe query for audio loop status.
       - Added `start_beating_loop(self, alert_id=None)`: Spawns a daemon background thread running `_beating_worker`.
       - Added `stop_beating_loop(self)`: Signals thread termination and resets active alert ID immediately.
       - Added `_beating_worker(self)`: Synthesizes a rhythmic institutional double-thump pulse (480 Hz for 80ms, 60ms pause, 440 Hz for 100ms, 650ms inter-beat pause with 50ms responsive interrupt checks).
       - Purpose: Provides continuous, non-ignorable alert audio until operator action without blocking inference or the UI thread.

  2. `monitor_app/decision.py`:
     - Lines 10–75 (`ContrabandDismissalRegistry`):
       - Implemented thread-safe `ContrabandDismissalRegistry` singleton (`get_dismissal_registry()`).
       - Implemented `dismiss_track(camera_id, track_id)`: Marks a specific contraband ID as dismissed by the operator.
       - Implemented `is_track_dismissed(camera_id, track_id) -> bool`: Checks if track is within the active dismissal TTL (15.0s from last sighting).
       - Implemented `touch_track(camera_id, track_id)`: Refreshes last seen timestamp so sustained detections stay dismissed.
       - Implemented `prune_stale(ttl)`: Cleans up dismissed tracks after they leave the CCTV field of view.
       - Purpose: Eliminates false-positive alert loops from static objects while preserving alert readiness for new objects.
     - Lines 98–145 (`DecisionEngine.evaluate_trigger`):
       - Evaluates contraband detections against `ContrabandDismissalRegistry`.
       - If an object's `track_id` is dismissed, calls `touch_track()`, marks `det["dismissed"] = True`, and filters it out of `packet.alerts`.
       - If all contraband items in the packet are dismissed and no behavior anomalies exist, returns `False` (suppresses recording and alarm).
       - If a *new* un-dismissed contraband ID is present, allows alert and returns `True`.
     - Lines 160–175 (`DecisionEngine.get_event_details`):
       - Skips dismissed contraband items when compiling active event labels.

  3. `monitor_app/camera_view.py`:
     - Lines 922–925 (`CameraMonitorScreen.__init__`):
       - Added `self.active_alert_camera_id = None` and `self.active_alert_contraband_ids = []`.
     - Lines 1060–1075 (`CameraMonitorScreen._on_incident_alert` & `_on_decision_alert`):
       - Extracts contraband track IDs from `ai_results` and forwards them to `_show_alert_banner`.
     - Lines 1076–1110 (`CameraMonitorScreen._show_alert_banner`):
       - Records active camera and contraband track IDs.
       - Calls `get_sound_alert_manager().start_beating_loop()`.
     - Lines 1113–1135 (`CameraMonitorScreen._dismiss_alert_banner`):
       - Calls `get_sound_alert_manager().stop_beating_loop()` to halt audio immediately.
       - Iterates over `self.active_alert_contraband_ids` and registers them with `get_dismissal_registry().dismiss_track()`.
     - Lines 1122–1130 (`CameraMonitorScreen._review_active_incident`):
       - Calls `get_sound_alert_manager().stop_beating_loop()` when jumping to incident review.
     - Lines 1270–1280 (`CameraMonitorScreen.stop_monitoring`):
       - Calls `get_sound_alert_manager().stop_beating_loop()` when leaving Live Monitor.

  4. `monitor_app/central_inference.py`:
     - Lines 305–338 (`_draw_contraband_boxes`):
       - Checks `is_dismissed = bool(det.get("dismissed"))`.
       - If dismissed: renders bounding box in muted slate gray `(139, 116, 100)` with label `"{NAME} #{TRACK_ID} [DISMISSED]"` in light gray.
       - If un-dismissed: renders in high-visibility alert red `(0, 0, 255)` with orange pill badge.
       - Purpose: Provides immediate visual confirmation of dismissed vs active detections.

- **Verification & Mechanical Gate:**
  1. **New Automated Unit Tests:**
     - `tests/test_sound_alert_loop.py` (Beating sound start, stop, non-blocking execution, disabled mode bypass).
     - `tests/test_contraband_dismissal.py` (Registry lifecycle, light glare suppression, and new ID alert triggering).
     - `tests/test_dismissal_ui_flow.py` (End-to-end banner show -> beating sound -> dismiss click -> sound halt & track dismissal).
  2. **Diff-Scan Mechanical Gate (`.agents/team/diff-scan.ps1`):**
     - Result: **`RESULT: GREEN`** (All tests passed).
  3. **Full Regression Suite (`pytest tests/`):**
     - Result: **`170 passed, 1 warning in 26.07s`** (100% test pass rate).
"""

with open("capstone_progress_report.md", "a", encoding="utf-8") as f:
    f.write(section_22)

print("Section 22 appended to capstone_progress_report.md successfully!")

