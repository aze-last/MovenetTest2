import os

section_21 = """

---

## 21. Live Monitor Multi-Cycle Freeze Resolution & Thread-Safety Hardening
- **Objective & Scope:**
  - Resolved the Live Monitoring freeze where video feeds functioned smoothly on initial run but got permanently stuck on the 2nd and 3rd visits while the terminal printed continuous fallback increments (`Fallbacks: 108, 109, 110...`) and queue overflow warnings.
  - Eliminated the background thread collision caused by unjoined `connect_all` workers holding native USB hardware capture locks.
  - Eliminated cross-thread Tkinter calls (`self.after(0, ...)`) from background worker threads which raised `RuntimeError: main thread is not in main loop` and aborted camera initialization.
  - Decoupled live video feed display from heavy inference backpressure drops so raw frames display at 30 FPS even under heavy AI load.
  - Enforced graceful video capture release on widget teardown without hanging the GUI thread.

- **Detailed Line-by-Line Changes:**
  1. `monitor_app/camera_view.py`:
     - Lines 1195–1200 (`CameraMonitorScreen.__init__`):
       - Initialized `self._is_monitoring = False`, `self._connecting = False`, `self._connect_thread = None`, `self._poll_connecting_job = None`.
       - Purpose: Tracks the lifecycle and worker thread of camera connections across repeated screen switches.
     - Lines 1209–1239 (`CameraMonitorScreen.start_monitoring`):
       - Sets `self._is_monitoring = True` and launches `self._connect_thread = threading.Thread(target=connect_all, daemon=True)`.
       - Inside `connect_all`: Added boundary check `if not getattr(self, "_is_monitoring", False): break` before initializing each camera feed.
       - Removed dangerous secondary-thread call `self.after(0, self._hide_connecting_overlay)`; replaced with main-thread timer poller `self._poll_connecting_status()`.
       - Purpose: Prevents zombie connection threads from running into destroyed widgets and avoids Tkinter cross-thread exceptions.
     - Lines 1240–1249 (`CameraMonitorScreen._poll_connecting_status`):
       - Implemented main-thread polling loop using `self.after(100, self._poll_connecting_status)` to safely dismiss the connection overlay when `self._connecting` becomes false.
       - Purpose: Strictly adheres to Tkinter GUI single-thread affinity rules.
     - Lines 1270–1298 (`CameraMonitorScreen.stop_monitoring`):
       - Added `self._is_monitoring = False` and cancelled `self._poll_connecting_job`.
       - Added explicit join for `self._connect_thread` (`self._connect_thread.join(timeout=1.5)`).
       - Purpose: Guarantees background connection activity completely terminates before navigating to other tabs.
     - Lines 1318–1348 (`CameraMonitorScreen._on_incident_alert`, `_on_decision_alert`):
       - Guarded callbacks with `if not self.winfo_exists() or not getattr(self, "_is_monitoring", False): return`.
       - Switched dispatch from `self.after(0, ...)` to `self.after_idle(...)`.
       - Purpose: Prevents queued event callbacks from executing on stale screen widgets.
     - Lines 1385–1395 (`CameraFeedWidget.__init__` & `start`):
       - Scheduled `self.update_loop` initialization directly from the main GUI thread during `__init__`.
       - Removed `self.after(0, self.update_loop)` from `CameraFeedWidget.start()` (which executes in the background `connect_all` thread).
       - Purpose: Eliminates `RuntimeError: main thread is not in main loop` inside Tkinter's `createcommand()`.
     - Lines 1520–1530 (`CameraFeedWidget._open_capture`):
       - Replaced cross-thread `self.after(0, _set_offline)` with `self.is_offline = True`, which is read safely by `self.update_loop()` on the main thread.
       - Purpose: Eliminates cross-thread widget property mutations.
     - Lines 1690–1720 (`CameraFeedWidget._on_inference_complete`):
       - Removed the early `return` condition when `processing_mode == "Queue Drop (Backpressure)"`.
       - Ensures that the current live camera frame is always resized and pushed to `self.result_queue` for rendering at 30 FPS.
       - Restricted `self.recorder.process_frame()` to non-dropped frames only.
       - Purpose: Resolves the video freeze / high fallback count issue (`Fallbacks: 110+`) when GPU inference drops frames under peak load.
     - Lines 1813–1845 (`CameraFeedWidget.stop`):
       - Set `self.running = False`, `self.is_stopped = True`, and pushed termination token `(False, None)` to unblock `self.frame_queue`.
       - Joined `self.cap_thread` first (0.5s timeout) before releasing OpenCV capture handles.
       - If capture thread is finishing a blocking read, delegates release to a daemon background thread (`_safe_release`) so the main thread never stalls.
       - Purpose: Guarantees immediate, clean hardware handle release on Windows DirectShow/MSMF without locking up camera devices for subsequent visits.

  2. `monitor_app/central_inference.py`:
     - Lines 107–113 (`CentralInferenceManager.stop`):
       - Added task queue draining loop upon shutdown.
       - Increased worker thread join timeout to 3.0s.
       - Purpose: Prevents backpressure queue buildup between screen switches.

- **Verification & Mechanical Gate:**
  1. **Multi-Cycle Screen Switch Automated Test (`scratch/test_multi_cycle.py`):**
     - Cycled 3 consecutive times through: `Dashboard -> Live Monitor (3.0s active stream) -> Dashboard -> Live Monitor`.
     - Output: `ALL 3 CYCLES COMPLETED CLEANLY!` with 0 errors, full 30 FPS inference execution (~33ms YOLO GPU, ~12ms MoveNet CPU), and proper camera reconnection on all cycles.
  2. **Diff-Scan Mechanical Gate (`.agents/team/diff-scan.ps1`):**
     - 31 out of 31 test suites passed in 27.99s.
     - Result: **`RESULT: GREEN`**.
"""

with open("capstone_progress_report.md", "a", encoding="utf-8") as f:
    f.write(section_21)

print("Section 21 appended successfully!")

