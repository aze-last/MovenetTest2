# Capstone Project Progress Report
**Project Name:** CellWatch AI  
**Deployment Target:** Real-Time CCTV Surveillance for BJMP Jail Cells  
**Status Update Date:** July 13, 2026

---

## 1. Technical Accomplishments & Architectural Shifts

### A. Core Architecture Migration: MoveNet to ONNX Runtime
- **Issue:** The behavior analysis engine (MoveNet Multipose) relied on the heavy `tensorflow-cpu` and `tensorflow-hub` packages. This bloated the application footprint, caused initialization delays, consumed significant RAM, and posed dependency conflict risks with the PyTorch/TensorRT YOLO pipeline.
- **Fix (ONNX Migration):**
  1. Converted the local TensorFlow `saved_model.pb` of MoveNet Multipose into a standalone `movenet_multipose.onnx` model using `tf2onnx` (`opset=13`).
  2. Completely stripped `tensorflow-cpu`, `tensorflow-directml-plugin`, and `tensorflow-hub` from the `requirements.txt`.
  3. Refactored the core AI dispatcher (`monitor_app/ai_engine.py`) and standalone tuner (`monitor_app/movenet_tuner.py`) to utilize the lightweight `onnxruntime` engine.
  4. Explicitly assigned MoveNet's `onnxruntime` inference session to the `['CPUExecutionProvider']`, strictly honoring the hardware constraint of isolating behavior analysis to the CPU, leaving the RTX 2050 GPU dedicated entirely to YOLO.

### B. Custom Model Identity: YOLO26s
- **Update:** Formalized the identity of the custom-trained contraband detection model from generic "YOLOv8" to **YOLO26s**.
- **Implementation:** 
  1. Updated the primary model weight references to use the newly provided `best.pt` (20.3MB).
  2. Executed a system-wide search-and-replace to ensure all UI elements, configuration files, and documentation accurately refer to "YOLO26s" to prevent any future ambiguity regarding the custom architecture.

### C. System Compilation & Deployment (PyInstaller)
- **Goal:** Package the complex multi-threaded, dual-AI pipeline into a standalone Windows executable that functions identically to the development `.venv` without requiring external dependencies on the target deployment machine.
- **Accomplishments:**
  1. Generated and refined `CellWatch.spec` to correctly collect critical submodules (`absl`, `google.protobuf`, `keras`, `tensorflow_hub` (prior to ONNX migration), and `customtkinter`).
  2. Modified the dynamic path resolution (`resource_path()`) across the system to ensure that embedded local databases (`incidents.db`, `profile_store`) and AI models (`best.engine`, `best.onnx`) resolve safely outside the temporary extraction directory when the packaged `.exe` runs.
  3. Successfully ran the packaged Live Monitor from `dist/CellWatch/`, confirming that RTSP streams, YOLO TensorRT engines, and the CustomTkinter UI render identical to the local development environment.

### D. TensorRT 11.x Portability & Engine Compilation
- **Issue:** Compiling the YOLO26s model into a TensorRT engine failed on newer TensorRT 11.x versions due to deprecated flags (`EXPLICIT_BATCH`, `fast_fp16`, etc.) in the Ultralytics exporter.
- **Fix:** Patched the `export/engine.py` logic to bypass deprecated checks dynamically and securely downgraded `protobuf` temporarily to resolve descriptor conflicts. Successfully compiled `best.engine` (45.1MB), achieving highly stable **20ms-30ms** per frame inference latency.

### E. UI Rendering & Thread-Affinity Profiling
- **Resolution of Canvas Spikes:** Diagnosed the ~70ms periodic UI stuttering on the Tkinter canvas. Confirmed that moving PIL Image resizing to the background worker thread pool (`cv2.resize` with `cv2.INTER_LINEAR`) fully resolved the bottleneck. The UI rendering tick has dropped from >60ms per camera down to 5-11ms, ensuring a fluid 30FPS output.

---

## 2. Current Architecture Summary
Based on the decisions ratified in the `GEMINI.md` and `CLAUDE.md` constitution files, the current production architecture is firmly established as follows:

1. **Behavior Engine:** MoveNet Multipose → **ONNX Runtime (CPU Bound)**
2. **Contraband Engine:** YOLO26s → **TensorRT (GPU Bound via RTX 2050)**
3. **Tracking Mechanism:** Embedded ByteTracker (`model.track()`) synchronized across async motion gates.
4. **Rendering:** Pure `CustomTkinter` operating synchronously off a thread-safe, decoupled queue matrix.

---

## 3. Offline Forensic Mode Restoration (July 13, 2026)
- **Issue:** Offline Forensic mode had two critical flaws: stable ID tracking thrashing and behavior classification frame-skipping.
- **Fixes Applied:**
  1. **Video-Time Delta (`classify_behavior`):** Replaced real wall-clock time (`time.time()`) with frame-index-based video time (`frame_index / fps`), ensuring consistent `dt` calculation across sequential video frames.
  2. **Unified Frame Counters (`StableIDTracker`):** Propagated camera-specific `frame_index` to the tracking logic to prevent divergence and false grace-period track resets.
  3. **YOLO Bounding Box Rendering:** Added native bounding box and label rendering to offline annotated video frames.
- **Verification:**
  1. Run MoveNet ONNX on walking-only baseline video: Confirmed **100% Normal** behavior output (0% false positive).
  2. Checked TensorRT vs PyTorch output: Confirmed matching predictions with **0.9382 IoU**.
  3. Validated offline manager run: Incidents, stable IDs, and contraband boxes exported correctly.

---

## 4. Files Modified During This Session
- **`monitor_app/models/movenet_multipose.onnx`**: New compiled ONNX behavior model.
- **`requirements.txt`**: Removed TF dependencies; added `onnxruntime>=1.16.0`.
- **`monitor_app/ai_engine.py`**: Fully replaced TensorFlow APIs with ONNX Runtime APIs; updated `process_frame` and `classify_behavior` to support camera-specific indices.
- **`monitor_app/central_inference.py`**: Propagated camera-specific indices to inference handlers.
- **`monitor_app/offline_inference.py`**: Injected index/timestamp metadata and added contraband rendering.
- **`monitor_app/movenet_tuner.py`**: Updated standalone tuning script to match ONNX architecture.
- **`monitor_app/settings.py`**: Updated UI configuration strings to "YOLO26s".
- **`CellWatch.spec`**: Configuration for standalone PyInstaller builds.
- **`CLAUDE.md` / `GEMINI.md`**: Updated to enforce the new ONNX/YOLO26s standards.
- **`capstone_progress_report.md`**: Rewritten to comprehensively log the transition to the distributable ONNX/TRT architecture.

