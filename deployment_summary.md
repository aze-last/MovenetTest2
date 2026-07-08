# Performance & Detection Optimization Summary
**Date:** July 7, 2026

This document summarizes all the files modified during our performance and tracking optimization session.

## 1. `monitor_app/ai_engine.py`
**What was implemented:**
- **Removed Artificial Lag (Throttle):** Deleted the 50ms (20 FPS) artificial speed limit on the AI so the GPU can run as fast as possible.
- **Removed ByteTrack for YOLO:** Bypassed the object tracker for contraband detection. YOLO now sends its bounding boxes directly to the screen and decision engine instantly. This eliminates the "lag" that was causing split-second cellphone/knife detections to be silently dropped.
- **Enabled Parallel Logic:** Separated MoveNet and YOLO into standalone functions (`run_movenet_only` and `run_yolo_only`) so they can be run on different threads concurrently instead of waiting for each other.
- **Optimized Memory:** Removed redundant `frame.copy()` operations to reduce RAM pressure.
- **Optimized Motion Detection:** Instructed the engine to skip computing motion if the camera worker already computed it, saving CPU cycles.

## 2. `monitor_app/central_inference.py`
**What was implemented:**
- **Parallel Inference Threads:** Completely rewrote the core inference loop. MoveNet (CPU) and YOLO (GPU) now process the exact same frame simultaneously in two parallel threads, effectively doubling system throughput.
- **Asynchronous Submission:** Added `submit_task_async()` which allows the camera to drop a frame into the queue and immediately go back to recording without waiting for the GPU to finish.
- **Larger Queue:** Increased the queue size from 8 to 16 to handle 4 concurrent cameras better and prevent dropped frames.

## 3. `monitor_app/camera_view.py`
**What was implemented:**
- **Non-blocking Camera Flow:** Switched from `submit_task()` to `submit_task_async()`. The camera thread no longer freezes while waiting for the AI to process a frame.
- **Pre-computed Motion Flag:** The camera now passes `motion_detected=True` to the AI engine so it doesn't recalculate motion twice.
- **Removed CPU Throttle:** Removed a stray `time.sleep(0.001)` that was needlessly slowing down the camera feed loop.

## 4. `config.yaml`
**What was implemented:**
- **New Performance Settings:** Added a `performance:` section to configure the new parallel architecture.
- Controls added for `inference_queue_maxsize`, `parallel_inference`, `skip_redundant_motion`, and `submit_timeout_s`.
- (The YOLO `inference_imgsz` was kept at 960 per your request).
