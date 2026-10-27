import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import time
import cv2
import numpy as np
import torch
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace

from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.evidence import TrackedPerson
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.tracking.tracker_manager import DetectionsAdapter

VIDEO_PATH = "recordings/cam_14/2026-08-25/event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4"
FRAMES_TO_EVALUATE = 900  # 30 seconds @ 30 FPS


class LegacyCentroidTracker:
    """Exact emulation of pre-Phase 1 nearest centroid tracker."""
    def __init__(self, max_distance=120.0, grace_period=30):
        self.max_distance = max_distance
        self.grace_period = grace_period
        self._tracks = {}
        self._next_id = 0

    def update(self, persons, frame_number):
        matches = []
        for p_idx, person in enumerate(persons):
            cx, cy = person.hip_centroid or (0.0, 0.0)
            for sid, data in self._tracks.items():
                ex, ey = data["hip_centroid"]
                # Scaled to 1920x1080
                dist = (((cx - ex) * 1920.0) ** 2 + ((cy - ey) * 1080.0) ** 2) ** 0.5
                if dist < self.max_distance:
                    matches.append((p_idx, sid, dist))

        # Greedy sort
        matches.sort(key=lambda x: x[2])
        matched_persons = set()
        matched_tracks = set()

        for p_idx, sid, dist in matches:
            if p_idx in matched_persons or sid in matched_tracks:
                continue
            person = persons[p_idx]
            person.stable_id = sid
            self._tracks[sid]["hip_centroid"] = person.hip_centroid or (0.0, 0.0)
            self._tracks[sid]["last_seen_frame"] = frame_number
            matched_persons.add(p_idx)
            matched_tracks.add(sid)

        for p_idx, person in enumerate(persons):
            if p_idx not in matched_persons:
                person.stable_id = self._next_id
                self._tracks[person.stable_id] = {
                    "hip_centroid": person.hip_centroid or (0.0, 0.0),
                    "last_seen_frame": frame_number,
                }
                self._next_id += 1

        stale_ids = [
            sid for sid, data in self._tracks.items()
            if frame_number - data["last_seen_frame"] > self.grace_period
        ]
        for sid in stale_ids:
            del self._tracks[sid]

        return persons


def run_benchmark():
    print("=" * 70)
    print("CELLWATCH AI — EMPIRICAL MOT BENCHMARK ON NVIDIA RTX 2050")
    print(f"Target GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Clip: {VIDEO_PATH}")
    print(f"Frames: {FRAMES_TO_EVALUATE}")
    print("=" * 70)

    if not os.path.exists(VIDEO_PATH):
        print(f"ERROR: Video {VIDEO_PATH} not found!")
        return

    cap = cv2.VideoCapture(VIDEO_PATH)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Total video frames available: {total_video_frames}")

    # Initialize Engine (MoveNet on CPU)
    print("Initializing MotionOptimizedEngine (MoveNet CPU ONNX)...")
    engine = MotionOptimizedEngine()

    # Pre-extract MoveNet person detections for the test segment
    # so both trackers are evaluated on the EXACT identical detections
    print(f"Extracting MoveNet detections for {FRAMES_TO_EVALUATE} frames...")
    frames_data = []  # list of (frame_idx, legacy_persons, phase1_persons, bboxes)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    t_start_ext = time.perf_counter()

    for f_idx in range(FRAMES_TO_EVALUATE):
        ret, frame = cap.read()
        if not ret:
            break

        frame_h, frame_w = frame.shape[:2]
        
        # Prepare input for MoveNet
        input_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        input_image = cv2.resize(input_image, (256, 256))
        input_image = np.expand_dims(input_image, axis=0).astype(np.int32)
        
        # MoveNet inference
        input_name = engine.movenet.get_inputs()[0].name
        out = engine.movenet.run(None, {input_name: input_image})
        people = out[0][0]

        legacy_persons = []
        phase1_persons = []
        bboxes = []

        for i in range(6):
            person = people[i, :51].reshape(17, 3)
            conf = float(people[i, 55])
            if conf < 0.2:
                continue

            valid_kps = [kp for kp in person if kp[2] > 0.12]
            if len(valid_kps) < 3:
                continue

            has_hips = person[11, 2] > 0.12 and person[12, 2] > 0.12
            has_shoulders = person[5, 2] > 0.12 and person[6, 2] > 0.12

            # Legacy centroid (unmitigated anchor jump)
            if has_hips:
                legacy_c = ((person[11, 1] + person[12, 1]) / 2, (person[11, 0] + person[12, 0]) / 2)
            elif has_shoulders:
                legacy_c = ((person[5, 1] + person[6, 1]) / 2, (person[5, 0] + person[6, 0]) / 2)
            else:
                legacy_c = (float(np.mean([kp[1] for kp in valid_kps])), float(np.mean([kp[0] for kp in valid_kps])))

            # Phase 1 centroid (anatomical torso offset)
            if has_hips:
                phase1_c = ((person[11, 1] + person[12, 1]) / 2, (person[11, 0] + person[12, 0]) / 2)
            elif has_shoulders:
                sh_w = abs(person[5, 1] - person[6, 1])
                torso_offset_y = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
                sh_x = (person[5, 1] + person[6, 1]) / 2
                sh_y = (person[5, 0] + person[6, 0]) / 2
                phase1_c = (sh_x, min(1.0, sh_y + torso_offset_y))
            else:
                phase1_c = (float(np.mean([kp[1] for kp in valid_kps])), float(np.mean([kp[0] for kp in valid_kps])))

            bbox = MotionOptimizedEngine.compute_bbox_from_keypoints(person, (frame_h, frame_w))
            if bbox:
                bboxes.append([bbox[0], bbox[1], bbox[2], bbox[3], conf, 0.0])

            legacy_persons.append(TrackedPerson(
                stable_id=-1, raw_person_id=i, camera_id="cam14",
                keypoints=person, hip_centroid=legacy_c, confidence=conf,
                frame_number=f_idx, timestamp=f_idx / 30.0
            ))
            phase1_persons.append(TrackedPerson(
                stable_id=-1, raw_person_id=i, camera_id="cam14",
                keypoints=person, hip_centroid=phase1_c, confidence=conf,
                frame_number=f_idx, timestamp=f_idx / 30.0
            ))

        frames_data.append((f_idx, legacy_persons, phase1_persons, bboxes, frame))

    cap.release()
    ext_duration = time.perf_counter() - t_start_ext
    print(f"Extracted {len(frames_data)} frames in {ext_duration:.2f}s ({len(frames_data)/ext_duration:.1f} FPS MoveNet extraction).")

    # -------------------------------------------------------------
    # 1. Benchmark: Legacy Centroid Tracker
    # -------------------------------------------------------------
    print("\n[1/3] Benchmarking Legacy Centroid Tracker...")
    legacy_tracker = LegacyCentroidTracker(max_distance=120.0, grace_period=30)
    legacy_times = []
    
    t0 = time.perf_counter()
    for f_idx, legacy_persons, _, _, _ in frames_data:
        t_frame0 = time.perf_counter()
        legacy_tracker.update(legacy_persons, f_idx)
        legacy_times.append(time.perf_counter() - t_frame0)
    legacy_total_time = time.perf_counter() - t0
    
    legacy_unique_ids = legacy_tracker._next_id
    legacy_lat_ms = np.median(legacy_times) * 1000.0
    legacy_p95_ms = np.percentile(legacy_times, 95) * 1000.0

    # -------------------------------------------------------------
    # 2. Benchmark: Phase 1 Kalman + Hungarian Tracker
    # -------------------------------------------------------------
    print("[2/3] Benchmarking Phase 1 Kalman + Hungarian Tracker...")
    phase1_tracker = StableIDTracker(max_distance=120.0, grace_period=30)
    phase1_times = []

    t0 = time.perf_counter()
    for f_idx, _, phase1_persons, _, _ in frames_data:
        t_frame0 = time.perf_counter()
        phase1_tracker.update(phase1_persons, f_idx)
        phase1_times.append(time.perf_counter() - t_frame0)
    phase1_total_time = time.perf_counter() - t0

    phase1_unique_ids = phase1_tracker._next_id
    phase1_lat_ms = np.median(phase1_times) * 1000.0
    phase1_p95_ms = np.percentile(phase1_times, 95) * 1000.0

    # -------------------------------------------------------------
    # 3. Benchmark: YOLO Bounding Boxes + BYTETracker
    # -------------------------------------------------------------
    print("[3/3] Benchmarking BYTETracker (with DetectionsAdapter)...")
    args_bt = IterableSimpleNamespace(
        track_thresh=0.25,
        track_buffer=60,
        match_thresh=0.5,
        frame_rate=30,
        track_high_thresh=0.25,
        track_low_thresh=0.05,
        new_track_thresh=0.30,
        fuse_score=False
    )
    byte_tracker = BYTETracker(args_bt)
    byte_times = []
    byte_observed_ids = set()

    # Measure VRAM
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        vram_start_mb = torch.cuda.memory_allocated() / (1024 * 1024)
    else:
        vram_start_mb = 0.0

    t0 = time.perf_counter()
    for f_idx, _, _, bboxes, frame in frames_data:
        t_frame0 = time.perf_counter()
        if bboxes:
            boxes_arr = np.asarray(bboxes, dtype=np.float32)
            det = DetectionsAdapter(boxes_arr[:, :4], boxes_arr[:, 4], boxes_arr[:, 5])
            out = byte_tracker.update(det, frame)
        else:
            out = byte_tracker.update(DetectionsAdapter([], [], []), frame)
        byte_times.append(time.perf_counter() - t_frame0)
        for t in out:
            byte_observed_ids.add(int(t[4]))
    byte_total_time = time.perf_counter() - t0

    if torch.cuda.is_available():
        vram_peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)
        vram_reserved_mb = torch.cuda.max_memory_reserved() / (1024 * 1024)
    else:
        vram_peak_mb = 0.0
        vram_reserved_mb = 0.0

    byte_unique_ids = len(byte_observed_ids)
    byte_lat_ms = np.median(byte_times) * 1000.0
    byte_p95_ms = np.percentile(byte_times, 95) * 1000.0

    # -------------------------------------------------------------
    # Summary Report
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print("EMPIRICAL BENCHMARK RESULTS (900 Frames / 30s Real CCTV Footage)")
    print("=" * 70)
    print(f"{'Tracker Model':<30} | {'Unique IDs':<11} | {'Median Lat (ms)':<16} | {'p95 Lat (ms)':<14} | {'Track Speed (FPS)':<18}")
    print("-" * 95)
    print(f"{'Baseline Centroid (Legacy)':<30} | {legacy_unique_ids:<11} | {legacy_lat_ms:<16.3f} | {legacy_p95_ms:<14.3f} | {len(frames_data)/legacy_total_time:<18.1f}")
    print(f"{'Phase 1 Kalman + Hungarian':<30} | {phase1_unique_ids:<11} | {phase1_lat_ms:<16.3f} | {phase1_p95_ms:<14.3f} | {len(frames_data)/phase1_total_time:<18.1f}")
    print(f"{'ByteTrack (DetectionsAdapter)':<30} | {byte_unique_ids:<11} | {byte_lat_ms:<16.3f} | {byte_p95_ms:<14.3f} | {len(frames_data)/byte_total_time:<18.1f}")
    print("-" * 95)
    print(f"VRAM Peak (RTX 2050): {vram_peak_mb:.1f} MB (Reserved: {vram_reserved_mb:.1f} MB)")
    print(f"ID Flip Reduction: {legacy_unique_ids} -> {phase1_unique_ids} ({((legacy_unique_ids - phase1_unique_ids)/legacy_unique_ids)*100:.1f}% reduction in spurious IDs)")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
