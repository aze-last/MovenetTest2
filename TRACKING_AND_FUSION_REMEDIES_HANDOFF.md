# CellWatch AI: Tracking, ReID & Multi-Camera Alert Fusion Architecture Handoff

**Date:** 2026-10-26  
**Context:** Multi-camera alarm storm resolution, cross-camera person tracking, and ReID feasibility analysis for CellWatch AI.  
**Hardware Profile:** NVIDIA GeForce RTX 2050 (4.0 GB VRAM) | 8 Cores / 16 Threads | 16 GB System RAM | Python 3.13.9 | Ultralytics 8.4.86 | OpenCV 4.13.0  
**Target:** 4 Concurrent Camera Feeds @ 20–30 FPS Real-Time Budget  

---

## 1. Executive Problem Summary

### The Symptom: The Monitor "Freaking Out"
When an inmate holding a cellphone is visible across multiple cameras (e.g., Cam 1 and Cam 2), each camera triggers its own independent alert instance. The operator monitor suffers from:
1. **Machine-gun audio beeps** playing asynchronously for every camera view.
2. **Alert Banner flickering and jitter** as Cam 1 and Cam 2 constantly overwrite each other's alert title and thumbnail.
3. **Database pollution** with redundant incident tickets (`INC_..._cam1` and `INC_..._cam2`) for the exact same human subject and contraband occurrence.

---

## 2. Current Codebase Audit (What is Actually Running)

A systematic source code audit revealed the exact mechanics currently in place:

### A. Person Tracking is 100% Centroid-Based
* **File:** [`monitor_app/tracking/stable_id.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/tracking/stable_id.py)
* **Implementation:** MoveNet Multipose extracts body keypoints (up to 6 people). In [`ai_engine.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/ai_engine.py#L488-L498) and [`behaviors/engine.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/behaviors/engine.py#L35-L38), the code calculates the midpoint between left/right hips (`hip_centroid`) and updates `StableIDTracker`.
* **The Flaw:** `StableIDTracker` computes simple 2D Euclidean distance on pixel coordinates. It lacks **motion prediction** (Kalman filter) and **appearance modeling**. When inmates cross paths, stop, or turn around, their centroids cross and IDs swap.

### B. ByteTrack is Currently Dormant
* **File:** [`monitor_app/tracking/tracker_manager.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/tracking/tracker_manager.py)
* **Status:** Defines `TrackerManager` wrapping Ultralytics' `BYTETracker`.
* **Audit Finding:** As recorded in [`investigate.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/investigate.py#L68), `TrackerManager` is **never instantiated or called** anywhere in the active inference pipeline.

### C. Contraband (YOLO) is Completely Untracked
* **File:** [`monitor_app/ai_engine.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/ai_engine.py#L716-L718)
* **Status:** YOLO runs `model.predict()`, not `model.track()`.
* **Classes:** 2 custom classes (`0: knife`, `1: cellphone`). It does not detect persons. Contraband detections receive a hardcoded `track_id = -1`.

### D. The Root Cause of Multi-Camera Duplicate Alarms
1. **Per-Camera Decision Trigger:** In [`central_inference.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/central_inference.py#L768-L792), as each camera frame arrives, it asks `decision_engine.evaluate_trigger(packet)` on that single camera's telemetry and fires `DECISION_TRIGGER` immediately.
2. **Per-Camera State Machine:** In [`alert_manager.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/alert_manager.py#L242-L280), `AlertManager` stores `self.camera_states = {}` indexed by `camera_id`. It treats Cam 1 and Cam 2 as isolated universes, creating separate incidents and triggering audio alerts independently.
3. **UI Overwrite:** In [`camera_view.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/camera_view.py#L510-L550), `_show_alert_banner` accepts events from any camera and overwrites the active banner in real time.

---

## 3. Hardware Feasibility & Tracker Benchmark (RTX 2050 / 4GB VRAM)

| Tracker Option | Viability on RTX 2050 (4GB VRAM) | Latency & Hardware Profile | Verdict |
| :--- | :--- | :--- | :--- |
| **Ultralytics ByteTrack** | 🟢 **100% Playable** | CPU-bound Kalman math; takes $< 0.5\text{ ms}$; **0 MB VRAM** | **Recommended.** Swap centroid tracker with ByteTrack immediately. |
| **BoT-SORT (`with_reid: True`)** | 🔴 **High Risk / Unplayable** | Deep embedding pass per crop + Camera Motion Compensation (CMC); VRAM exhaustion risk across 4 cameras | **Skip.** Stationary CCTV does not need CMC; secondary ReID nets will drop FPS from 25 to $<10$. |
| **BoxMOT Library** | 🟡 **Not Recommended** | External package dependency, AGPL-3.0 viral licensing hazards | **Skip.** Ultralytics 8.4.86 already has native ByteTrack/BoT-SORT. |

---

## 4. Correctional Facility Realities (Jail Domain Constraints)

### A. Why Body ReID (OSNet, CLIP-ReID, FastReID) Fails in Jails
* Deep appearance ReID models rely heavily on clothing colors, logo textures, and fashion silhouettes.
* In correctional facilities (e.g., BJMP), **all inmates wear identical uniforms (yellow shirts)**.
* In feature embedding space, two different inmates wearing yellow uniforms yield cosine similarities $> 0.85$. **Body ReID collapses into false-positive identity merging.**

### B. Facial Recognition: OpenCV Zoo (YuNet + SFace)
* **Native Presence:** Verified that `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF` exist in the installed OpenCV (`4.13.0`).
* **Footprint:** `YuNet` (detector) is $\approx 250\text{ KB}$; `SFace` (recognizer) is $\approx 1.2\text{ MB}$.
* **Hardware Impact:** Runs entirely on **CPU** (`DNN_TARGET_CPU`), taking $\approx 2.5\text{ ms}$ per detection. **Consumes 0 MB of GPU VRAM**, preserving 100% of the 4GB VRAM for YOLO and MoveNet.
* **Licensing:** Apache 2.0 (fully open and permissible, unlike InsightFace's commercial licensing).

### C. The Ceiling-Mounted CCTV Gotcha
* Ceiling/wall cameras look down at steep angles ($45^\circ\text{–}60^\circ$). Faces are obscured when inmates look downward at phones.
* **Invariant:** Facial recognition must be **opportunistic**. It must never be a mandatory requirement to alert. If an unidentified face holds a phone, the system must still alert as `Unenrolled Inmate (Track #X)`.

---

## 5. The Three Architectural Remedies

```text
[Camera 1 Feeds] ──┐
[Camera 2 Feeds] ──┼─► [Single-Camera Trackers] ──► [fusion.py: Cross-Cam Deduplication]
[Camera 3 Feeds] ──┤        (ByteTrack on CPU)                  │ (Global Person Registry)
[Camera 4 Feeds] ──┘                                            ▼
                                                    [Global Decision Engine]
                                                    (Zone & Deduplication Gate)
                                                                │
                                                                ▼
                                                [Single Institutional Alert Event]
                                                "Incident #104: Phone (Cam 1 & Cam 2)"
```

### Remedy 1: Zone-Level Deduplication in `fusion.py` (Immediate Architectural Fix)
* **Shift Trigger Authority:** Strip `central_inference.py` of the authority to fire `DECISION_TRIGGER` directly to the `AlertManager`. Cameras only submit raw telemetry to `CameraFusion`.
* **Zone Sliding Window:** When Camera 1 spots a phone in Zone A, `fusion.py` opens a 5–10 second incident window.
* **Corroborating Evidence:** When Camera 2 spots a phone in Zone A during this window, it does **not** create a new incident or sound an alarm. It appends its viewpoint as secondary evidence: `Supporting View: Cam 2 (82% conf)`.
* **Outcome:** Single unified banner in the UI, single institutional audio chime.

### Remedy 2: Single-Camera ByteTrack + Opportunistic Face Binding
* **Tracking:** Convert MoveNet skeleton bounding boxes (`compute_bbox_from_keypoints`) to input for `BYTETracker`. Maintain stable per-camera track IDs across occlusions.
* **Face Binding:** When a face is detected (YuNet $> 0.80$), extract the 128-d embedding with SFace, query enrolled detainee vectors, and bind `detainee_name = "Inmate Juan Dela Cruz"` to the active `ByteTrack` ID.
* **Continuity:** The tracker holds this identity while the inmate moves around the cell, even after their back turns to the camera.

### Remedy 3: Subject-Aware Debounce & Hysteresis in `alert_manager.py`
* Replace per-camera `IncidentState` with **Zone/Subject-scoped State Machines**.
* If `Inmate Juan Dela Cruz` (or `Track #3` in Zone 1) triggers an incident, transition to `CONFIRMED`.
* Subsequent detections over the next 15–20 seconds only feed video evidence into the existing incident package without re-triggering alarms.

---

## 6. Legal & Policy Framework (BJMP / RA 10173)

1. **Republic Act 10173 (Data Privacy Act of 2012):**
   Biometric identification of Persons Deprived of Liberty (PDL) requires institutional clearance in the project authorization letter and a Data Privacy Impact Assessment (DPIA).
2. **Honesty Clause in Thesis / Technical Manuscript:**
   Do not claim the system "perpetually remembers identities." Frame it scientifically:
   * **ByteTrack:** Provides *session-persistent local motion continuity*.
   * **YuNet + SFace:** Provides *opportunistic identity verification* when facial geometry exceeds quality thresholds.

---

## 7. Recommended Implementation Sequence

1. **Step 1:** Implement Zone-Level Deduplication in [`monitor_app/fusion.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/fusion.py) and adjust [`central_inference.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/central_inference.py) to eliminate the multi-camera alert freak-out immediately.
2. **Step 2:** Wire `BYTETracker` into the MoveNet person pipeline in [`behaviors/engine.py`](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/behaviors/engine.py), replacing `StableIDTracker` to eliminate centroid swapping.
3. **Step 3:** Download `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx` into `monitor_app/models/` and build a CPU-based opportunistic face-binding module.
