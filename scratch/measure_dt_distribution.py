import os
import sys
import time
import cv2
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from monitor_app.ai_engine import MotionOptimizedEngine

def measure_dt_distribution(video_path, num_cameras=1, duration_seconds=15.0):
    print(f"\n==========================================")
    print(f" MEASURING DT DISTRIBUTION: {num_cameras} CAMERA(S)")
    print(f"==========================================")
    
    cap = cv2.VideoCapture(video_path)
    frames = []
    # Preload 300 frames to avoid disk I/O distortion
    for _ in range(300):
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    print(f"Preloaded {len(frames)} frames into memory for benchmarking.")

    engine = MotionOptimizedEngine()
    engine.enable_movenet = True
    engine.enable_yolo = False  # Test MoveNet CPU behavior cadence

    # Hook or monitor classify_behavior dt calls
    dt_records = []
    
    orig_classify = engine.classify_behavior
    def tracked_classify(kps, p_id, cam_id, frame_shape, custom_time=None):
        key = f"{cam_id}_{p_id}"
        current_time = custom_time if custom_time is not None else time.time()
        if key in engine.trackers:
            prev_t = engine.trackers[key]["time"]
            dt = current_time - prev_t
            dt_records.append((cam_id, p_id, dt))
        return orig_classify(kps, p_id, cam_id, frame_shape, custom_time=custom_time)
    
    engine.classify_behavior = tracked_classify

    start_t = time.time()
    frame_idx = 0
    cam_ids = [f"cam_{i+1}" for i in range(num_cameras)]

    # Simulate multi-camera round-robin arrival
    while (time.time() - start_t) < duration_seconds:
        frame = frames[frame_idx % len(frames)]
        for cam_id in cam_ids:
            engine.run_movenet_only(frame, camera_id=cam_id, frame_index=frame_idx, draw=False)
        frame_idx += 1

    elapsed = time.time() - start_t
    print(f"Processed {frame_idx} rounds across {num_cameras} camera(s) in {elapsed:.2f}s (Overall FPS: {(frame_idx * num_cameras) / elapsed:.1f})")

    # Analyze dt distribution
    dts = [r[2] for r in dt_records]
    if not dts:
        print("No dt records collected (no persons tracked).")
        return None

    dts = np.array(dts)
    median_dt = np.median(dts)
    p95_dt = np.percentile(dts, 95)
    p99_dt = np.percentile(dts, 99)
    pct_gt_150ms = np.mean(dts > 0.150) * 100.0

    print(f"Results for {num_cameras} Camera(s):")
    print(f"  Total dt samples    : {len(dts)}")
    print(f"  Median dt           : {median_dt*1000:.1f} ms")
    print(f"  p95 dt              : {p95_dt*1000:.1f} ms")
    print(f"  p99 dt              : {p99_dt*1000:.1f} ms")
    print(f"  Percentage > 150 ms : {pct_gt_150ms:.2f}% (RESET RISK)")

    return {
        "num_cameras": num_cameras,
        "samples": len(dts),
        "median_ms": median_dt * 1000,
        "p95_ms": p95_dt * 1000,
        "p99_ms": p99_dt * 1000,
        "pct_gt_150ms": pct_gt_150ms
    }

if __name__ == "__main__":
    video_p = r"recordings\cam_14\2026-08-25\event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4"
    res1 = measure_dt_distribution(video_p, num_cameras=1, duration_seconds=10.0)
    res2 = measure_dt_distribution(video_p, num_cameras=2, duration_seconds=10.0)
    res4 = measure_dt_distribution(video_p, num_cameras=4, duration_seconds=10.0)
