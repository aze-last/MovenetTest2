# scratch/append_section_23.py

section_23 = """

---

## 23. Dynamic Contraband Tracking & Per-Camera Queue Pacing Remediations
- **Objective & Scope:**
  - Resolved the critical issue where an operator dismissed an intentional false positive (vape / light source), and subsequently showing a mobile phone was not detected or given an ID.
  - Root Cause 1: In `ai_engine.py`, untracked contraband detections used a deterministic static spatial-grid hash (`abs(hash(f"untracked_{cls_id}_{gx}_{gy}")) % 9000 + 1000`). Because the user was in the same chair/area, the phone mapped to the exact same ID (`4441` / `6072`) as the dismissed vape, causing `DecisionEngine` to immediately silence it.
  - Root Cause 2: In `central_inference.py` and `camera_view.py`, 4 cameras running at 30 FPS submitted 120 FPS into `self.task_queue` (max size 15). The GPU can process ~15-18 FPS total. 88% of frames were dropped to backpressure, returning raw unannotated frames to the UI and starving YOLO of incoming frames.
  - Root Cause 3: In `central_inference.py:228`, `_draw_contraband_boxes` was called before `DecisionEngine` evaluated dismissals, and it did not have `camera_id` to query `ContrabandDismissalRegistry` directly.

- **Detailed Line-by-Line Changes:**
  1. `monitor_app/ai_engine.py`:
     - Lines 660–755 (`DynamicContrabandTracker`):
       - Implemented camera-scoped dynamic contraband tracker using IoU (0.25 threshold) and centroid proximity (90px fallback).
       - Allocates monotonically incrementing unique track IDs (`self._next_track_id = 1001, 1002, 1003...`).
       - Ages unmatched tracks across frames and prunes dead tracks after `max_lost_frames = 15`.
       - Purpose: Guarantees that when an object leaves and a new object is presented, it receives a brand-new ID that is not dismissed.
     - Lines 140–145 (`MotionOptimizedEngine.__init__`):
       - Initialized `self.contraband_tracker = DynamicContrabandTracker()`.
     - Lines 875–895 (`_run_yolo_logic`):
       - Replaced static grid hash with `self.contraband_tracker.update(cam_id, [[x1, y1, x2, y2]], [conf], [cls_id])`.
       - Purpose: Eliminates ID collision across sequential object presentations.

  2. `monitor_app/central_inference.py`:
     - Lines 58–62 (`CentralInferenceManager.__init__`):
       - Added `self._in_flight_cameras = set()` and `self._in_flight_lock = threading.Lock()`.
     - Lines 63–78 (`CentralInferenceManager` Pacing API):
       - Added `has_in_flight_task(camera_id) -> bool`: Thread-safe query checking if an inference task for this camera is currently queued or executing.
       - Added `mark_task_in_flight(camera_id)` and `clear_task_in_flight(camera_id)`.
     - Lines 235 & 710 (`_draw_contraband_boxes` call sites):
       - Passed `camera_id=camera_id` into `_draw_contraband_boxes`.
     - Lines 305–325 (`_draw_contraband_boxes`):
       - Directly checks `get_dismissal_registry().is_track_dismissed(camera_id, track_id)`.
       - Renders dismissed items in muted slate gray `[DISMISSED]`, and un-dismissed items in high-visibility red `ALERT`.
     - Lines 865, 878, 937, 955 (`_worker_loop`, `submit_task`, `submit_task_async`):
       - Integrated in-flight tracking so tasks clear their in-flight state immediately upon completion or drop.

  3. `monitor_app/camera_view.py`:
     - Lines 1720–1745 (`CameraFeedWidget._worker_thread`):
       - Added pacing check: if `manager.has_in_flight_task(str(self.camera_id))` is True, pushes the current frame directly to `self.result_queue` for fluid 30 FPS display without submitting duplicate tasks to `self.task_queue`.
       - Purpose: Eliminates `Queue Overflow (Backpressure)` warnings and prevents frames from being dropped prior to inference.

- **Verification & Mechanical Gate:**
  1. **New Automated Unit Test (`tests/test_dynamic_contraband_tracking.py`):**
     - Verified dynamic ID allocation when an object leaves and a new object is presented (`test_dynamic_contraband_tracker_allocates_new_id_on_new_object`).
     - Verified DecisionEngine trigger differentiation between dismissed vape ID and new phone ID (`test_dismissal_differentiation_with_decision_engine`).
     - Verified CentralInferenceManager in-flight pacing tracking (`test_central_inference_in_flight_pacing`).
     - Output: **`3 passed in 2.96s`**.
  2. **Diff-Scan Mechanical Gate (`.agents/team/diff-scan.ps1`):**
     - Result: **`RESULT: GREEN`**.
  3. **Full Regression Test Suite (`pytest tests/`):**
     - Result: **`190 passed, 1 warning in 28.73s`** (100% test pass rate).
"""

with open("capstone_progress_report.md", "a", encoding="utf-8") as f:
    f.write(section_23)

print("Section 23 appended to capstone_progress_report.md successfully!")

