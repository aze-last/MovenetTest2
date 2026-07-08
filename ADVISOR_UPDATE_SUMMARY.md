# CellWatch AI: Recent Architecture & Feature Updates

This document summarizes the recent architectural upgrades and feature implementations completed for the CellWatch AI project.

## 1. Live Monitor Initialization Overhaul (Freeze Fix)
The camera initialization process has been completely refactored to eliminate the critical UI freezing issue (where the application would show "Not Responding" for 20+ seconds on startup).

* **Parallel Connections:** Camera handshakes are now dispatched to background threads via `ThreadPoolExecutor`, reducing total wait time to the duration of the single slowest camera.
* **Loading Overlay:** Added a "Connecting to cameras..." modal overlay to provide immediate user feedback while background threads process.
* **Aggressive Timeouts:** Enforced a strict 5000ms `CAP_PROP_OPEN_TIMEOUT_MSEC` limit on all OpenCV `VideoCapture` instances to swiftly abort dead RTSP streams.
* **Thread-Safe Failovers:** Camera connection failures are gracefully passed back to the main Tkinter thread using `self.after()`, marking failed camera tiles as "OFFLINE" without crashing the grid.

## 2. Multi-Camera Concealment Fusion Engine
The concealment detection pipeline has been upgraded from a single-camera heuristic to a robust, multi-camera fusion architecture.

* **Per-Camera Classification (`hand_observation.py`):** Each camera independently classifies a subject's hands as `VISIBLE`, `CONCEALED`, or `UNKNOWN` (e.g., if the camera is viewing the subject from a side-profile).
* **Zone-Level Fusion (`concealment_fusion.py`):** The system merges these per-camera observations. It employs cross-camera veto rules: if Camera A suspects concealment but Camera B clearly sees the wrist (Visible), Camera B's observation overrides and vetoes the concealment.
* **Side-Profile Mitigation:** Single side-view cameras no longer have the authority to trigger a concealment alert on their own (as they usually just suffer from viewpoint occlusion). They emit an `UNKNOWN` state to the fusion engine.
* **Decision Engine Gating:** The `decision.py` engine now mandates that any concealment `BehaviorEvidence` must possess a `fusion_confirmed = true` flag before triggering an actual incident record.
* **Note on YOLO:** The previously considered Phase 6 (adding a dedicated YOLO hand-concealment model) was intentionally cancelled to conserve the 4GB GPU VRAM budget on the target deployment laptop. The fusion engine successfully relies solely on the optimized MoveNet pipeline.

## 3. Object Detections (Contraband)
Object detection remains a **single-camera event**. Unlike concealment, which is prone to viewpoint occlusion, contraband (like cellphones and knives) relies on absolute visibility. If any single camera clearly detects contraband, an alert is triggered immediately without cross-camera verification.
