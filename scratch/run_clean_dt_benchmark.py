import os
import sys
import time
import json
import cv2
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from monitor_app.ai_engine import MotionOptimizedEngine, CapstoneDebug

# Silence noisy alert logs during benchmark
CapstoneDebug.log = lambda cam_id, msg: None

def run_dt_test(video_path, num_cameras, duration_s=6.0):
    cap = cv2.VideoCapture(video_path)
    frames = []
    for _ in range(200):
        ret, frame = cap.read()
        if not ret: break
        frames.append(frame)
    cap.release()

    engine = MotionOptimizedEngine()
    engine.enable_movenet = True
    engine.enable_yolo = False

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

    while (time.time() - start_t) < duration_s:
        frame = frames[frame_idx % len(frames)]
        for cam_id in cam_ids:
            engine.run_movenet_only(frame, camera_id=cam_id, frame_index=frame_idx, draw=False)
        frame_idx += 1

    dts = np.array([r[2] for r in dt_records])
    if len(dts) == 0:
        return {"num_cameras": num_cameras, "samples": 0}
    
    return {
        "num_cameras": num_cameras,
        "samples": int(len(dts)),
        "median_ms": float(np.median(dts) * 1000),
        "p95_ms": float(np.percentile(dts, 95) * 1000),
        "p99_ms": float(np.percentile(dts, 99) * 1000),
        "pct_gt_150ms": float(np.mean(dts > 0.150) * 100.0)
    }

if __name__ == "__main__":
    video_p = r"recordings\cam_14\2026-08-25\event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4"
    results = []
    for nc in [1, 2, 4]:
        print(f"Benchmarking {nc} camera(s)...", flush=True)
        r = run_dt_test(video_p, nc, duration_s=6.0)
        results.append(r)
        print(f"Done {nc} cam: median={r['median_ms']:.1f}ms, p95={r['p95_ms']:.1f}ms, >150ms={r['pct_gt_150ms']:.2f}%", flush=True)
    
    print("\n--- FINAL DT RESULTS TABLE ---")
    print(json.dumps(results, indent=2))
