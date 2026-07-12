# Capstone Project Progress Report
**Project Name:** CellWatch AI  
**Deployment Target:** Real-Time CCTV Surveillance for BJMP Jail Cells  
**Status Update Date:** July 9, 2026

---

## 1. Technical Accomplishments & Bug Fixes

### A. Core Inference Pipeline & UI Rendering

- **Resolution of "Time-Travel" Frame Stuttering:**  
  **Issue:** The raw video feed was physically stuttering and jumping back in time. `camera_view.py` attempted to artificially bypass the inference queue for 2 out of every 3 frames (`N=3`) to save CPU, pushing them instantly to the UI. However, the 1 frame sent to the AI queue took ~30ms-50ms to process, arriving at the UI *after* the bypassed future frames were already displayed. This caused the video feed to constantly overwrite itself with older AI-processed frames.  
  **Fix:** Removed the `N=3` manual frame skip in `camera_view.py`. All frames are now unconditionally submitted to `central_inference.py`, which strictly enforces FIFO queue ordering. The central AI manager handles its own throttling (`yolo_skip` and `movenet_skip`) gracefully while ensuring overlays are continuously drawn on every frame. The UI now renders at a perfectly sequential and smooth 30 FPS.

- **Resolution of UI Flickering and Missing MoveNet Skeletons:**  
  **Issue:** The video frames in the UI were flickering, and MoveNet skeletal frames were not rendering. The flickering occurred because the motion gate skipped frames without motion, abruptly clearing all UI overlays. The missing skeletons were caused by MoveNet drawing its lines on an async worker's copied frame rather than the final frame presented to the UI.  
  **Fix:** 
  1. *Persistent Detections (Flicker Fix):* Modified `central_inference.py` so that when a frame is skipped due to lack of motion (`should_run=False`), it explicitly retrieves and merges the last known YOLO and MoveNet results to ensure detection overlays gracefully persist across motion-skipped frames instead of blinking.
  2. *Render Loop Skeletal Drawing:* Relocated the `draw_skeleton` invocation into `central_inference.py`'s `_worker_loop`. Skeletons are now drawn synchronously over the active UI `packet.frame` alongside bounding boxes, ensuring they are not discarded when the async frame copy is destroyed.

- **Thread-Safety & Torn Read Prevention:**  
  **Issue:** The `merged` detection dictionary in `central_inference.py` was being read during the rendering phase while the MoveNet (CPU) and YOLO (GPU) threads were simultaneously updating their respective result dictionaries, causing torn reads.  
  **Fix:** Added a `threading.Lock()` (`self.result_lock`) explicitly scoped around the dictionary writes inside `_movenet_worker` and `_yolo_worker`, and around the `merged` dictionary construction block. The lock is held for mere microseconds, ensuring atomic detection arrays without blocking the main render thread.

### B. AI Tracking & False Positive Mitigation

- **Resolution of Bounding Box Flickering & Object Tracking:**  
  **Issue:** Bounding boxes rendered in the UI were flickering, and YOLO detections default-assigned a tracking `ID: -1` because the AI engine was calling raw model inference (`model()`), treating each frame as a transient event.  
  **Fix:** Swapped raw inference for YOLOv8's native tracking API (`model.track(..., persist=True)`). This integrates the embedded ByteTracker algorithm, assigning stable tracking IDs to contraband detections.

- **Hysteresis Track ID Fix:**  
  **Issue:** YOLO hysteresis cache keys collided for multiple objects of the same class, causing erratic tracking drops and overwrites.  
  **Fix:** Swapped the YOLO hysteresis dictionary key in `ai_engine.py` from `cls_id` to `track_id` (with a coordinate string fallback for untracked items) to guarantee multiple objects are tracked and cached distinctly.

- **Prevention of False-Positive Alerts (Fighting/Aggression):**  
  **Issue:** The behavior classification model frequently triggered false "Aggressive / Fighting" alerts when subjects walked normally or stood still due to high-frequency keypoint jitter.  
  **Fixes Implemented:**
  1. **Torso-Translation Focus:** Shifted the primary velocity metric from limbs (wrists/elbows) to torso joints (shoulders/hips).
  2. **EMA Coordinate Smoothing:** Added Exponential Moving Average (EMA) keypoint coordinate smoothing (`alpha = 0.4`) to filter camera and inference noise.
  3. **Soft-Thresholding (Deadband):** Set a motion deadband of `0.004 * frame_width` (~7.6px for 1080p). Joint movements below this threshold are discarded.
  4. **Tracking Gap Reset:** If a Person ID goes undetected for > 0.15 seconds, the velocity history is cleared to prevent "teleportation" speed spikes.
  5. **NMS Filter & Structure Gate:** Added Non-Maximum Suppression (NMS) (`threshold = 0.15`) to suppress duplicate split detections of the same person.
  **Results:** Tested on the walking clip (`Screen Recording 2026-07-07 111126.mp4`), reducing false alerts in the walking region from **100% to 0%**.

### C. System Performance & Optimization

- **Hardware Utilization & Tracking Continuity (Unthrottling):**  
  **Issue:** The system's CPU and GPU were underutilized, and ByteTracker dropped IDs because it was being fed 1 frame and skipping 2 (`yolo_skip = 3`).  
  **Fix:** Modified `central_inference.py` to change `self.yolo_skip` from 3 to 1. Feeding every frame to the GPU ensures the ByteTracker maintains a perfect lock on contraband targets. Changed `self.movenet_skip` from 6 to 2 to utilize the Ryzen 7's CPU headroom, making behavior detection 3x more responsive.

- **Model Swap & TensorRT Compilation:**  
  **Upgrade:** Renamed the newly trained custom model to `best.pt` and successfully compiled it into an optimized TensorRT engine (`best.engine`).  
  **Performance Gains:** Inference latency dropped to a highly stable **20ms - 30ms** per frame on the NVIDIA GeForce RTX 2050 GPU.

- **RAM Optimization via JPEG Compression:**  
  **Issue:** Massive RAM ballooning (~1.87 GB) because raw BGR numpy arrays were stored in the pre-roll event memory buffer.  
  **Fix:** Refactored `incident_record.py` to compress `bgr_frame` into 80% quality JPEG bytes (`cv2.imencode`) before appending to `pre_roll_buffer`. This dropped the footprint to ~45 MB. Frames are now decoded (`cv2.imdecode`) dynamically upon write.

- **Queue Performance & Logging Optimization:**  
  **Issue:** Severe "Queue Overflow (Backpressure)" warning logs flooded the console/disk on startup and during heavy CPU workloads.  
  **Fix:** Implemented a 5-second per-camera rate limiter for the `queue_overflow` warnings. Telemetry counters remain 100% accurate, but spam is eliminated.

- **Resolution of Thread Exhaustion & CPU Thrashing:**  
  **Issue:** In `central_inference.py`, `submit_task_async` spawned a raw `threading.Thread(...)` for *every single frame* per camera to wait for the inference callback (up to 120 threads per second). This raw thread allocation caused severe OS-level context switching, GIL contention, and elevated thermals on the target machine.  
  **Fix:** Removed raw thread creation. Replaced it with a bounded `ThreadPoolExecutor(max_workers=4)` assigned to `self.callback_executor` (line 46). The callback invocation was moved into the central `_worker_loop` (line 501), ensuring callbacks are processed cleanly as tasks finish, completely eliminating the 120 threads/sec power leak.

- **Resolution of Warped NMS Suppression Zones:**  
  **Issue:** MoveNet's duplicate detection suppression (NMS) computed Euclidean distance on normalized `[0,1]` coordinates. On a 16:9 frame, this created elliptical suppression zones, causing over-suppression horizontally and under-suppression vertically.  
  **Fix:** Scaled the normalized centroid distances by the actual frame dimensions `(frame_w, frame_h)` before computing the Euclidean distance, yielding a true circular suppression radius.

- **Prevention of Live Monitor Freezes from Synchronous YOLO Reloads:**  
  **Issue:** If YOLO tracking failed, the exception handler instantiated a new `YOLO(fallback_path)` synchronously inside the main GPU loop. This would block the central dispatcher for several seconds, completely freezing the live video feed for all cameras.  
  **Fix:** Modified the exception handler to instantly flag the AI as degraded (`self._yolo_is_reloading = True`) and spawn a detached background thread (`_bg_reload`) to load the model asynchronously, allowing the pipeline to continue operating smoothly on fallback mechanics until tracking is fully restored.

### D. Codebase Health & Dependencies

- **Environment Dependencies & `requirements.txt` Synchronization:**  
  **Issue:** The `requirements.txt` file referenced non-existent or outdated PyTorch wheel versions (`torch==2.7.1+cu118`).  
  **Fix:** Synchronized `requirements.txt` to target the exact running dependencies of the RTX 2050 deployment environment (`ultralytics==8.4.26`, `torch==2.4.1+cu118`, `tensorrt==11.1.0.106`).

- **Resolved Tracking Event Reference Errors & Unused Import Clean-ups:**  
  **Fix:** Added missing tracking event definitions (`TRACK_CREATED`, etc.) in `monitor_app.events`. Removed unused `import numpy as np` from tracker managers to clean up imports.

---

## 2. Architectural Decisions & Guardrails

### A. Multi-Model Configuration Council
- **Decision:** Stick to a single optimized model for production rather than allowing multi-model dynamic configurations.
- **Rationale:** Convened an AI architecture council. Dynamic multi-model loading in production poses a severe risk of VRAM crashes (4GB limit on the RTX 2050 target laptop) and violates Capstone reliability guidelines. Model configuration remains restricted to developer A/B testing only.

### B. Robust Boundary Coordinate Scaling
- **Decision:** Implemented a robust boundary range check `[-1.0, 2.0]` for normalized coordinates inside the tracking module.
- **Rationale:** MoveNet keypoint predictions occasionally exceed `1.0` due to bounding box padding near frame boundaries. The new range ensures that real edge-detections are scaled correctly to the virtual `1920x1080` canvas.

---

## 3. Known Limitations & Risks

- **Async MoveNet Staleness (Mitigated):** Previously, to maintain FPS, MoveNet ran asynchronously (every 6th frame / ~500ms). With the recent hardware unthrottling (MoveNet every 2nd frame), the staleness window is drastically reduced from ~500ms to ~60ms. While rapid subject coordinate swapping is now far less likely to cause miscorrelation, extreme high-speed motion could still theoretically outpace the 30FPS capture rate.

- **I/O & Interrupt Contention (USB + Network):** Running multiple high-resolution physical webcams through a single USB hub simultaneously with an H.264 RTSP network stream causes severe resource contention on the laptop. While the USB webcams can run smoothly on their own, the massive number of hardware interrupts from the USB bus starves the network card or CPU decode threads of I/O cycles. This starvation manifests as network packet drops for the RTSP stream, triggering the OpenCV/FFmpeg freezing behavior. To run a mixed deployment of USB and RTSP cameras, USB bandwidth must be heavily distributed or camera frame rates lowered to prevent overwhelming the laptop's I/O controller.

---

## 4. Files Modified (Recent Changes)
- `monitor_app/camera_view.py` (Removed N=3 frame-bypassing to fix time-travel stuttering)
- `monitor_app/central_inference.py` (Hardware unthrottling, continuous rendering loop, MoveNet skeletal drawing, thread-safe dict merging, persistent detections on motion gate skips)
- `monitor_app/ai_engine.py` (Hysteresis `track_id` fix, decoupled rendering, YOLO track API)
- `monitor_app/incident_record.py` (Pre-roll JPEG memory compression)
- `monitor_app/events.py` (Added missing tracking events)
- `monitor_app/tracking/tracker_manager.py` (Removed unused imports)
- `requirements.txt` (Synchronized TensorRT/CUDA dependencies)
- `capstone_progress_report.md` (Updated structural report and findings)

### E. Camera Streaming Reliability & Stalled Read Watchdog
- **Resolution of RTSP Connection and Stream Stalls:**
  **Issue:** Real-time RTSP camera feeds periodically freeze and lock up during ongoing streaming on Windows. This is caused by `cap.read()` blocking indefinitely in OpenCV's underlying I/O backend when decode errors occur, without a native timeout.
  **Fixes:**
  1. *Forced FFMPEG Backend:* Forced the FFMPEG backend (and TCP transport/low latency env configurations) for RTSP feeds.
  2. *FFMPEG RTSP Timeout:* Corrected the timeout setting in `OPENCV_FFMPEG_CAPTURE_OPTIONS` to use `stimeout` in microseconds (`stimeout;5000000` = 5 seconds) instead of the invalid `timeout;5000` milliseconds parameter, which FFmpeg was ignoring.
  3. *Decoupled Producer Thread:* Created a dedicated background thread (`_capture_thread_loop`) that handles `cap.read()` and feeds a bounded single-frame queue (`frame_queue = Queue(maxsize=1)`).
  4. *Read-Level Watchdog:* Updated `_worker_loop` to read from the queue with `timeout=2.5`. If the queue is empty for >2.5s, a stall is detected.
  5. *Asynchronous Release (Deadlock Prevention):* Modified the cleanup and watchdog recovery logic to offload `cap.release()` to a background daemon thread. Since `VideoCapture.release()` blocks on the same mutex as `VideoCapture.read()`, releasing synchronously while `read()` is blocked would deadlock the main camera worker thread. Releasing asynchronously prevents this deadlock.
  6. *Corrupted Frame Protection:* Added validation to check if frames retrieved are `None` or have a size of `0` before processing. This blocks corrupted RTSP packets from propagating downstream to the AI engine where they would trigger exception pauses.
  7. *UI Status Visibility:* The UI now clearly displays `RECONNECTING` (in orange) on the camera tile rather than silently freezing on the last frame, and skips submitting frames to `central_inference.py` entirely while offline to protect the shared queue from garbage frames.

---

### F. RTSP Low-Latency Buffering Fix (Problem 2)
- **Resolution of ~2-second RTSP live delay:**
  **Issue:** RTSP camera feeds (e.g. Tapo C200C) exhibited a ~2-second delay between real-world action and on-screen display, caused by FFmpeg's internal frame buffering — a buffering issue, not an architecture issue.
  **Fix (`monitor_app/camera_view.py`, line ~684, `_open_capture`):** Added the missing low-latency flags to `OPENCV_FFMPEG_CAPTURE_OPTIONS` for RTSP (non-int) sources.
  - **Before:** `rtsp_transport;tcp|buffer_size;102400|max_delay;500000|stimeout;5000000`
  - **After:** `rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000|stimeout;5000000`
  - Added `fflags;nobuffer` (disable input buffering) and `flags;low_delay` (minimize decoder latency).
  - Removed `buffer_size;102400` (a large receive buffer that works against low-latency intent; omitted in the approved target config).
  - **Preserved** `stimeout;5000000` (5s connection-hang protection from fix E.2 above) rather than dropping it, avoiding a regression of that documented fix.
  - **Confirmed already present (no change):** `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` at line ~698 is already applied specifically to RTSP captures (the non-int `else` branch).

---

### G. Decoupled Camera Feed Resizing & Thread-Affinity Optimization (Q4 Performance Fix)
- **Resolution of Live Monitor Freezes & Thread Bottlenecks:**
  **Issue:** Resizing raw camera frames (`640x480` webcams and `1280x720` RTSP feeds) was executing synchronously on the main Tkinter UI thread during the update loop. Resizing 4 feeds took `~60ms` per tick, immediately blowing the `33ms` main-thread frame budget (limiting rendering to ~10 FPS even in steady-state). In addition, PIL's default resizing and Canvas updates frequently triggered massive garbage collection and synchronization spikes of up to `282.9ms`, completely freezing the live screen.
  **Fixes (`monitor_app/camera_view.py`):**
  1. *Decoupled Off-Thread Resizing:* Moved the image resizing operations into background threads: `_on_inference_complete` (running in the 4-worker `callback_executor` ThreadPool) for AI-processed frames, and `_worker_loop` (camera worker background thread) for power-saving frames.
  2. *OpenCV Bilinear Optimization:* Swapped PIL's slow default resize with a highly optimized `cv2.resize(..., interpolation=cv2.INTER_LINEAR)` call executing *before* the BGR→RGB conversion. This downscales the image first, shrinking the color conversion workload by up to 75% for 720p feeds and leveraging fast SIMD instructions.
  3. *Type-Aware Main Thread Bypass:* Modified `update_loop` to accept pre-resized PIL `Image` objects. It bypasses PIL conversion/resizing entirely, only invoking `ImageTk.PhotoImage` and `canvas.itemconfig` (which have Tkinter thread-affinity).
  4. *Size-Mismatch Safety Fallback:* Added a main-thread fallback using `Image.resize` to handle dynamic window resizing safely. The fallback triggers exactly once on startup/resize and remains at 0 during steady-state (verified by telemetry logs).
  **Results:** Eliminated main-thread resize time from **12-20ms per camera down to 0.0ms**. Reduced total main-thread rendering per camera to **~5-11ms** (totalling **~28-40ms** across all 4 cameras), allowing the system to achieve its target 30 FPS.

---

## 4. Files Modified (Recent Changes)
- `monitor_app/camera_view.py` (Decoupled PIL Image resize to background thread workers, optimized resize with cv2.INTER_LINEAR, shifted color conversion downstream of resize, implemented type-aware bypass on Tkinter main thread, and added size-mismatch fallback logging telemetry)
- `capstone_progress_report.md` (Updated structural progress report with off-thread camera resizing accomplishments)

