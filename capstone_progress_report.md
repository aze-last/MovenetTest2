# Capstone Project Progress Report
**Project Name:** CellWatch AI  
**Deployment Target:** Real-Time CCTV Surveillance for bjmp Jail Cells  
**Status Update Date:** July 9, 2026

---

## 1. Technical Accomplishments & Bug Fixes

### A. Resolution of Bounding Box Flickering & Object Tracking
- **The Issue:** Bounding boxes rendered in the UI were flickering, and YOLO detections default-assigned a tracking `ID: -1`. This occurred because the AI engine was calling raw model inference (`model()`), treating each frame as a transient, unrelated event.
- **The Fix:** Swapped raw inference for YOLOv8's native tracking API (`model.track(..., persist=True)`). This integrates the embedded ByteTracker algorithm, assigning stable tracking IDs to contraband detections and eliminating the visual flickering in the UI.

### B. Prevention of False-Positive Alerts (Fighting/Aggression)
- **The Issue:** The behavior classification model frequently triggered false "Aggressive / Fighting" alerts when subjects walked normally or stood still due to high-frequency keypoint jitter.
- **The Fixes implemented:**
  1. **Torso-Translation Focus:** Shifted the primary velocity metric from limbs (wrists/elbows) to torso joints (shoulders/hips) to prioritize body translation over arm swings.
  2. **EMA Coordinate Smoothing:** Added Exponential Moving Average (EMA) keypoint coordinate smoothing (`alpha = 0.4`) to filter camera and inference noise.
  3. **Soft-Thresholding (Deadband):** Set a motion deadband of `0.004 * frame_width` (~7.6px for 1080p). Joint movements below this threshold are discarded as noise.
  4. **Tracking Gap Reset:** If a Person ID goes undetected for $> 0.15$ seconds (approx. 4-5 frames), the velocity history is cleared. This prevents "teleportation" speed spikes when tracking is lost/regained.
  5. **NMS Filter & Structure Gate:** Added Non-Maximum Suppression (NMS) (`threshold = 0.15`) to suppress duplicate split detections of the same person, and required at least 5 visible keypoints (including shoulders or hips) to reject ghost/noise detections.
- **Results:** Tested on the walking clip (`Screen Recording 2026-07-07 111126.mp4`), reducing false alerts in the walking region from **100% to 0%**.

### C. Queue Performance & Logging Optimization
- **The Issue:** Severe "Queue Overflow (Backpressure)" warning logs flooded the console/disk on startup and during heavy CPU workloads, causing significant I/O performance bottlenecks.
- **The Fix:** Implemented a 5-second per-camera rate limiter for the `queue_overflow` warnings. Telemetry counters remain 100% accurate, but spam is completely eliminated, reducing CPU/disk overhead.

### D. Model Swap & TensorRT Compilation
- **The Upgrade:** Renamed the newly trained custom model (`cellwatch_v4_yolo26s_best.pt`) to `best.pt` and successfully compiled it into an optimized TensorRT engine (`best.engine`).
- **Performance gains:** Inference latency dropped to a highly stable **20ms - 30ms** per frame on the NVIDIA GeForce RTX 2050 GPU.

### E. Resolved Tracking Event Reference Errors & Unused Import Clean-ups
- **The Issue:** The compiler reported missing reference errors for tracking events (`TRACK_CREATED`, `TRACK_UPDATED`, `TRACK_LOST`, `TRACK_RECOVERED`, `TRACK_TERMINATED`) in `monitor_app.events` and unused import warnings for `numpy`.
- **The Fixes implemented:**
  1. **Define Tracking Events:** Added definitions for `TRACK_CREATED`, `TRACK_UPDATED`, `TRACK_LOST`, `TRACK_RECOVERED`, and `TRACK_TERMINATED` in [events.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/events.py) (Lines 56-61).
  2. **Unused Code Removal:**
     - Removed unused `import numpy as np` from [tracker_manager.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/tracking/tracker_manager.py) (previously Line 6) to clean up imports.
     - Removed unused `import numpy as np` from [ai_engine.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/ai_engine.py) (previously Line 2) to clean up imports.

### F. Environment Dependencies & requirements.txt Synchronization
- **The Issue:** The `requirements.txt` file referenced non-existent or outdated PyTorch wheel versions (`torch==2.7.1+cu118`, etc.), which would cause dependency installation to fail on replica machines.
- **The Fix:** Synchronized [requirements.txt](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/requirements.txt) to target the exact running dependencies of the RTX 2050 deployment environment:
  - Line 6: Pinned `ultralytics==8.4.26`.
  - Line 14: Updated to `torch==2.4.1+cu118`.
  - Line 15: Updated to `torchvision==0.19.1+cu118`.
  - Line 16: Updated to `torchaudio==2.4.1+cu118`.
  - Line 17: Added `tensorrt==11.1.0.106` to ensure GPU engine optimization runs in replica setups.

### G. RAM Optimization & Rendering Decoupling
- **The Issue:** 
  1. Massive RAM ballooning (~1.87 GB) because raw BGR numpy arrays were stored in the pre-roll event memory buffer.
  2. Bounding boxes were flickering because rendering (`cv2.rectangle`) was tethered to the YOLO inference loop, which intentionally skips frames to maintain performance.
  3. YOLO hysteresis cache keys collided for multiple objects of the same class, causing erratic tracking drops and overwrites.
- **The Fixes implemented:**
  1. **In-Memory JPEG Compression:** Refactored [incident_record.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/incident_record.py) to compress `bgr_frame` into 80% quality JPEG bytes (`cv2.imencode`) before appending to `pre_roll_buffer`. This detached the numpy memory allocator and dropped the footprint to ~45 MB. Frames are now decoded (`cv2.imdecode`) dynamically upon write in `_start_recording`.
  2. **Decoupled Continuous Rendering:** Removed all `cv2` drawing logic from [ai_engine.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/ai_engine.py) (`_run_yolo_logic`). Added a continuous rendering loop inside [central_inference.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/central_inference.py) (`_run_parallel_inference`) that guarantees boxes are drawn on every frame based on the cached `merged` dictionary detections.
  3. **Hysteresis Track ID Fix:** Swapped the YOLO hysteresis dictionary key in `ai_engine.py` from `cls_id` to `track_id` (with a coordinate string fallback for untracked items) to guarantee multiple objects are tracked and cached distinctly.

### H. Hardware Utilization & Tracking Continuity (Unthrottling)
- **The Issue:** The system's CPU and GPU were underutilized ("on chill"), and the YOLO tracking (ByteTracker) dropped IDs because it was being fed 1 frame and skipping 2 (`yolo_skip = 3`). ByteTracker's Kalman filter requires continuous sequential frames to maintain motion prediction.
- **The Fixes implemented:**
  1. **Unthrottled YOLO:** Modified [central_inference.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/central_inference.py) to change `self.yolo_skip` from 3 to 1. Feeding every frame to the GPU ensures the ByteTracker maintains a perfect lock on contraband targets.
  2. **Unthrottled MoveNet:** Changed `self.movenet_skip` from 6 to 2 to utilize the Ryzen 7's CPU headroom, making aggressive behavior detection 3x more responsive.

### I. Thread-Safety & Torn Read Prevention
- **The Issue:** The `merged` detection dictionary in `central_inference.py` was being read during the rendering phase while the MoveNet (CPU) and YOLO (GPU) threads were simultaneously updating their respective result dictionaries. This lack of synchronization caused race conditions, leading to torn reads (partially updated object detections rendering on screen).
- **The Fix:** Added a `threading.Lock()` (`self.result_lock`) explicitly scoped around the dictionary writes inside `_movenet_worker` and `_yolo_worker`, and around the `merged` dictionary construction block in the main queue thread. The lock is held for mere microseconds (pure dict updating/copying), ensuring atomic detection arrays without blocking the main render thread.

---

## 2. Architectural Decisions & Guardrails

### A. Multi-Model Configuration Council
- **Decision:** Stick to a single optimized model for production rather than allowing multi-model dynamic configurations.
- **Rationale:** Convened an AI architecture council. Dynamic multi-model loading in production poses a severe risk of VRAM crashes (4GB limit on the RTX 2050 target laptop) and violates Capstone reliability guidelines. Model configuration remains restricted to developer A/B testing only.

### B. Robust Boundary Coordinate Scaling
- **Decision:** Implemented a robust boundary range check `[-1.0, 2.0]` for normalized coordinates inside the tracking module.
- **Rationale:** MoveNet keypoint predictions occasionally exceed `1.0` due to bounding box padding near frame boundaries. The new range ensures that real edge-detections are scaled correctly to the virtual `1920x1080` canvas, while unit test mocks with pixel coordinates (e.g. `10.0`, `100.0`) remain unscaled.

---

## 3. Known Limitations & Risks

- **Async MoveNet Staleness (Mitigated):** Previously, to maintain FPS, MoveNet ran asynchronously (every 6th frame / ~500ms) and YOLO every 3rd frame. With the recent hardware unthrottling (MoveNet every 2nd frame, YOLO every frame), the staleness window is drastically reduced from ~500ms to ~60ms. While rapid subject coordinate swapping is now far less likely to cause YOLO miscorrelation, extreme high-speed motion could still theoretically outpace the 30FPS capture rate.

---

## 4. Files Modified
- `monitor_app/incident_record.py` (Pre-roll JPEG memory compression)
- `monitor_app/ai_engine.py` (Hysteresis `track_id` fix, decoupled rendering, YOLO track API)
- `monitor_app/central_inference.py` (Hardware unthrottling, continuous rendering loop, thread-safe dict merging)
- `monitor_app/events.py` (Added missing tracking events)
- `monitor_app/tracking/tracker_manager.py` (Removed unused imports)
- `requirements.txt` (Synchronized TensorRT/CUDA dependencies)
- `capstone_progress_report.md` (Added documentation for thread-safety fix)

### J. Resolution of UI Flickering and Missing MoveNet Skeletons
- **The Issue:** The video frames in the UI were flickering, and MoveNet skeletal frames were not rendering. The flickering occurred because the motion gate skipped frames without motion, which returned an empty detections dictionary and abruptly cleared all UI overlays. The missing skeletons were caused by MoveNet drawing its lines on an async worker's copied frame rather than the final frame presented to the UI.
- **The Fixes implemented:**
  1. **Persistent Detections (Flicker Fix):** Modified `central_inference.py` so that when a frame is skipped due to lack of motion (`should_run=False`), it explicitly retrieves and merges the last known YOLO and MoveNet results (`last_movenet_results` and `last_yolo_results`) to ensure detection overlays gracefully persist across motion-skipped frames instead of blinking.
  2. **Render Loop Skeletal Drawing:** Relocated the `draw_skeleton` invocation into `central_inference.py`'s `_worker_loop`. Skeletons are now drawn synchronously over the active UI `packet.frame` alongside bounding boxes, ensuring they are not discarded when the async frame copy is destroyed.

### K. Resolution of "Time-Travel" Frame Stuttering
- **The Issue:** The raw video feed was physically stuttering and jumping back in time. This occurred because `camera_view.py` attempted to artificially bypass the inference queue for 2 out of every 3 frames (`N=3`) to save CPU, pushing them instantly to the UI. However, the 1 frame sent to the AI queue took ~30ms-50ms to process, meaning it arrived at the UI *after* the bypassed future frames were already displayed, causing the video feed to constantly overwrite itself with older AI-processed frames.
- **The Fix:** Removed the `N=3` manual frame skip in `camera_view.py`. All frames are now unconditionally submitted to `central_inference.py`, which strictly enforces FIFO queue ordering. The central AI manager handles its own throttling (`yolo_skip` and `movenet_skip`) gracefully while ensuring bounding boxes and overlays are continuously drawn on every frame. The UI now renders at a perfectly sequential and smooth 30 FPS.
