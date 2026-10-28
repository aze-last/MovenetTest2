# PLAN.md — Sustained Contraband Tracking, Anti-Stagger & Dismissal Isolation

## 1. Spec & Objective
- **Problem Statement:**
  1. **Detection ID Churn & Non-Sustained Tracking:** In `monitor_app/ai_engine.py`, `self.contraband_tracker.update()` is called inside a per-box loop passing a single box `[[x1,y1,x2,y2]]`. When multiple boxes or reflections exist, each box's update increments `lost_count` on all other tracks, killing tracks within 15 frames and forcing new monotonic IDs (1001 -> 1002 -> 1004 -> 1005 -> 1007). Contraband IDs fail to sustain stably.
  2. **Dismissal Hijacking by Centroid Fallback:** `DynamicContrabandTracker` falls back to 90px centroid proximity for any track in `active_tracks`. When the user dismisses an object (e.g. vape) and then presents their phone in the same region, the tracker binds the phone to the vape's dismissed ID. `DecisionEngine` sees the dismissed ID and suppresses all alerts.
  3. **Display Stagger & Frame Flickering:** When GPU inference exceeds ~33ms or queue overflows, dropped tasks return unprocessed blank packets with `alert_triggered=False` and no bounding boxes. The camera feed's result queue alternates between rendered inference frames and blank dropped frames, causing severe visual staggering and bounding box flickering.
  4. **Detection Key Inconsistency:** `ai_engine.py` sets `"conf"`, but `central_inference.py:321` looks for `"confidence"`, causing confidence to always evaluate to 0.0 in bounding box headers.

- **Invariants & Constraints:**
  - Strict Rule 8 (Dependency Freeze): Zero new pip packages.
  - Strict Rule 9 (RTK Tooling): Use `rtk` for command execution.
  - Target Hardware: Windows 11 laptop with NVIDIA RTX 2050 (MoveNet CPU, YOLO GPU).
  - Tri-CLI Loop Protocol: Pre-flight mechanical gate (`diff-scan.ps1`) -> Diff Verifier (`agy --mode plan`).

---

## 2. Scoped Tasks

### T1 — Batch Contraband Tracking & Clean Object Lifetime (surface: monitor_app/ai_engine.py)
- **Files:** `monitor_app/ai_engine.py`, `tests/test_dynamic_contraband_tracking.py`
- **Scope:**
  1. In `_run_yolo_logic()`, aggregate all valid contraband bounding boxes, confidences, and class IDs across `results` into batch lists (`batch_boxes`, `batch_confs`, `batch_cls_ids`).
  2. Invoke `self.contraband_tracker.update(cam_id, batch_boxes, batch_confs, batch_cls_ids)` ONCE per frame per camera.
  3. In `DynamicContrabandTracker.update()`:
     - Tighten centroid proximity fallback: only allow centroid association if `trk["lost_count"] == 0` (prevent resurrecting lost/dismissed objects when a new object appears).
     - Populate both `"conf"` and `"confidence"` in detection dictionaries.
- **TDD Test:** `tests/test_dynamic_contraband_tracking.py` verifying multi-box batch stability and distinct ID allocation for subsequent objects.
- **Exit Gate:** `pytest tests/test_dynamic_contraband_tracking.py` GREEN.

### T2 — Eliminate Display Stagger & Frame Dropping Blank-outs (surface: monitor_app/central_inference.py)
- **Files:** `monitor_app/central_inference.py`, `tests/test_central_inference_pacing.py`
- **Scope:**
  1. In `submit_task()` and `submit_task_async()`, when a task is dropped due to queue backpressure:
     - Instead of wiping bounding boxes with an unprocessed blank packet, pull the latest stable result from `self.last_yolo_results` and `self.last_movenet_results` for that camera.
     - Overlay recent stable bounding boxes so dropped frames maintain display continuity without visual blinking or staggering.
  2. In `_draw_contraband_boxes()`, read `conf = float(det.get("conf", det.get("confidence", 0.0)))`.
- **TDD Test:** Unit test asserting dropped task callback receives preserved detection telemetry and non-empty metadata.
- **Exit Gate:** `pytest tests/test_central_inference_pacing.py` GREEN.

### T3 — Dismissal Registry Scope & Alert Reset Isolation (surface: monitor_app/camera_view.py & monitor_app/decision.py)
- **Files:** `monitor_app/camera_view.py`, `monitor_app/decision.py`, `tests/test_dismissal_ui_flow.py`
- **Scope:**
  1. In `CameraFeedWidget._show_alert_banner()`, explicitly reset `self.active_alert_contraband_ids = list(contraband_ids or [])` so stale dismissed IDs do not leak across distinct alert cycles.
  2. In `ContrabandDismissalRegistry`: ensure dismissal strictly targets the exact track ID. If a new track ID appears on the same camera, immediately treat it as un-dismissed and trigger the alert banner.
- **TDD Test:** Test verifying dismissing track ID 1001 does not suppress track ID 1002 appearing in the same camera view.
- **Exit Gate:** `pytest tests/test_dismissal_ui_flow.py` GREEN.

### T4 — Pre-Flight Mechanical Gate & Diff Review
- **Files:** None (validation only)
- **Scope:**
  1. Run `.agents/team/diff-scan.ps1`.
  2. Run `agy --mode plan` for diff verification.
  3. Append Section 25 to `capstone_progress_report.md` with instinct notes.
  4. Run `scratch/bundle_changes.py` to refresh `changes_today.zip`.