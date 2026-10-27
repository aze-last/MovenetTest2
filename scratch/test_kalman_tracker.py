import os
import sys
import time
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.abspath("."))
from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.evidence import TrackedPerson
from monitor_app.tracking.stable_id import StableIDTracker

class KalmanPersonTrack:
    def __init__(self, track_id: int, centroid: tuple[float, float], frame_number: int, timestamp: float):
        self.track_id = track_id
        # State: [x, y, vx, vy]
        cx, cy = centroid
        self.x = np.array([cx, cy, 0.0, 0.0], dtype=np.float32)
        # Covariance
        self.P = np.diag([10.0, 10.0, 50.0, 50.0]).astype(np.float32)
        # Process noise
        self.Q = np.diag([1.0, 1.0, 4.0, 4.0]).astype(np.float32)
        # Measurement noise
        self.R = np.diag([4.0, 4.0]).astype(np.float32)
        
        self.last_seen_frame = frame_number
        self.last_seen_time = timestamp
        self.hits = 1
        self.age = 1

    def predict(self, dt: float = 1.0) -> tuple[float, float]:
        # F = [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]]
        F = np.array([
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]
        ], dtype=np.float32)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        self.age += 1
        return float(self.x[0]), float(self.x[1])

    def update(self, centroid: tuple[float, float], frame_number: int, timestamp: float):
        z = np.array([centroid[0], centroid[1]], dtype=np.float32)
        H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0]
        ], dtype=np.float32)
        y = z - (H @ self.x)
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + (K @ y)
        self.P = (np.eye(4, dtype=np.float32) - K @ H) @ self.P
        self.last_seen_frame = frame_number
        self.last_seen_time = timestamp
        self.hits += 1

class KalmanHungarianTracker:
    def __init__(self, max_distance_norm: float = 0.15, grace_frames: int = 30):
        self.max_dist_norm = max_distance_norm
        self.grace_frames = grace_frames
        self.tracks: dict[int, KalmanPersonTrack] = {}
        self.next_id = 0

    def update(self, persons: list[TrackedPerson], frame_number: int, timestamp: float = None) -> list[TrackedPerson]:
        if timestamp is None:
            timestamp = time.time()

        # Step 1: Kalman Predict for all active tracks
        track_ids = list(self.tracks.keys())
        predicted_positions = {}
        for tid in track_ids:
            predicted_positions[tid] = self.tracks[tid].predict(dt=1.0)

        # Step 2: Build Cost Matrix (Normalized Euclidean Distance)
        N = len(persons)
        M = len(track_ids)
        if N > 0 and M > 0:
            cost_matrix = np.zeros((N, M), dtype=np.float32)
            for i, p in enumerate(persons):
                cx, cy = p.hip_centroid or (0.0, 0.0)
                for j, tid in enumerate(track_ids):
                    px, py = predicted_positions[tid]
                    dist = ((cx - px)**2 + (cy - py)**2)**0.5
                    cost_matrix[i, j] = dist

            # Step 3: Optimal Global Bipartite Assignment via Hungarian Algorithm
            row_inds, col_inds = linear_sum_assignment(cost_matrix)
            matched_det = set()
            matched_trk = set()

            for r, c in zip(row_inds, col_inds):
                dist = cost_matrix[r, c]
                if dist <= self.max_dist_norm:
                    tid = track_ids[c]
                    person = persons[r]
                    person.stable_id = tid
                    self.tracks[tid].update(person.hip_centroid or (0.0, 0.0), frame_number, timestamp)
                    matched_det.add(r)
                    matched_trk.add(tid)
        else:
            matched_det = set()
            matched_trk = set()

        # Step 4: Unmatched detections get new tracks
        for i, person in enumerate(persons):
            if i not in matched_det:
                person.stable_id = self.next_id
                self.tracks[self.next_id] = KalmanPersonTrack(
                    track_id=self.next_id,
                    centroid=person.hip_centroid or (0.0, 0.0),
                    frame_number=frame_number,
                    timestamp=timestamp
                )
                self.next_id += 1

        # Step 5: Prune stale tracks
        stale = [
            tid for tid, trk in self.tracks.items()
            if frame_number - trk.last_seen_frame > self.grace_frames
        ]
        for tid in stale:
            del self.tracks[tid]

        return persons

def benchmark_trackers(video_path, max_frames=900):
    print(f"Benchmarking Trackers on {max_frames} frames of {video_path}...")
    cap = cv2.VideoCapture(video_path)
    engine = MotionOptimizedEngine()
    engine.enable_movenet = True
    engine.enable_yolo = False

    t_orig = StableIDTracker(max_distance=120.0, grace_period=30)
    t_kalman = KalmanHungarianTracker(max_distance_norm=0.15, grace_frames=30)

    orig_creations = 0
    kalman_creations = 0

    fidx = 0
    while cap.isOpened() and fidx < max_frames:
        ret, frame = cap.read()
        if not ret: break
        fidx += 1

        res = engine.run_movenet_only(frame, camera_id="cam1", frame_index=fidx, draw=False)
        tps = res.get("tracked_persons", [])
        
        # Test 1: Original Centroid Tracker
        before_orig = set(t_orig._tracks.keys())
        t_orig.update(tps, fidx)
        orig_creations += sum(1 for p in tps if p.stable_id not in before_orig)

        # Apply projected anchor to tps
        for p in tps:
            kps = p.keypoints
            has_hips = kps[11, 2] > 0.10 and kps[12, 2] > 0.10
            has_shoulders = kps[5, 2] > 0.10 and kps[6, 2] > 0.10
            if not has_hips and has_shoulders:
                sh_x = (kps[5, 1] + kps[6, 1]) / 2.0
                sh_y = (kps[5, 0] + kps[6, 0]) / 2.0
                sh_w = abs(kps[5, 1] - kps[6, 1])
                torso_offset_y = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
                p.hip_centroid = (sh_x, min(1.0, sh_y + torso_offset_y))

        # Test 2: Kalman + Hungarian Tracker
        before_kalman = set(t_kalman.tracks.keys())
        t_kalman.update(tps, fidx)
        kalman_creations += sum(1 for p in tps if p.stable_id not in before_kalman)

    cap.release()
    print(f"\n--- RESULTS OVER {fidx} FRAMES ---")
    print(f"Original Centroid Tracker New IDs: {orig_creations}")
    print(f"Kalman + Hungarian Tracker New IDs: {kalman_creations}")
    reduction = ((orig_creations - kalman_creations) / orig_creations) * 100 if orig_creations else 0
    print(f"ID Flip Reduction: {reduction:.1f}%")

if __name__ == "__main__":
    benchmark_trackers(r"recordings\cam_14\2026-08-25\event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4", max_frames=900)
