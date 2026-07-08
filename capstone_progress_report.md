# Capstone Project Progress Report
**Project Name:** CellWatch AI  
**Deployment Target:** Real-Time CCTV Surveillance for bjmp Jail Cells  
**Status Update Date:** July 8, 2026

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

- **Async MoveNet Staleness:** To maintain target FPS on target hardware, MoveNet runs asynchronously (every 6th frame / ~500ms). YOLO runs on every 3rd frame. If two subjects rapidly swap coordinates within a 500ms window, YOLO contraband detections could temporarily be correlated with the incorrect subject. This is mitigated by NMS and tracking resets but remains a known trade-off of the low-resource CPU-gated architecture.
