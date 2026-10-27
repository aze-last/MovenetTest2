import os
import sys
import time
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.abspath("."))
from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.evidence import TrackedPerson

class OldCentroidTracker:
    def __init__(self, max_distance=120.0, grace_period=30):
        self.max_distance = max_distance
        self.grace_period = grace_period
        self._tracks = {}
        self._next_id = 0

    def update(self, centroids, frame_number):
        possible_matches = []
        for p_idx, (cx, cy) in enumerate(centroids):
            for stable_id, data in self._tracks.items():
                ex, ey = data["hip_centroid"]
                # Old scaling
                is_norm_e = (-1.0 <= ex <= 2.0) and (-1.0 <= ey <= 2.0)
                is_norm_c = (-1.0 <= cx <= 2.0) and (-1.0 <= cy <= 2.0)
                ex_s = ex * 1920.0 if is_norm_e else ex
                ey_s = ey * 1080.0 if is_norm_e else ey
                cx_s = cx * 1920.0 if is_norm_c else cx
                cy_s = cy * 1080.0 if is_norm_c else cy
                dist = ((cx_s - ex_s)**2 + (cy_s - ey_s)**2)**0.5
                if dist < self.max_distance:
                    possible_matches.append((p_idx, stable_id, dist))

        possible_matches.sort(key=lambda x: x[2])
        matched_persons = set()
        matched_tracks = set()
        assigned_ids = {}

        for p_idx, stable_id, dist in possible_matches:
            if p_idx in matched_persons or stable_id in matched_tracks:
                continue
            assigned_ids[p_idx] = stable_id
            self._tracks[stable_id]["hip_centroid"] = centroids[p_idx]
            self._tracks[stable_id]["last_seen_frame"] = frame_number
            matched_persons.add(p_idx)
            matched_tracks.add(stable_id)

        new_creations = 0
        for p_idx in range(len(centroids)):
            if p_idx not in matched_persons:
                new_id = self._next_id
                self._next_id += 1
                new_creations += 1
                assigned_ids[p_idx] = new_id
                self._tracks[new_id] = {
                    "hip_centroid": centroids[p_idx],
                    "last_seen_frame": frame_number
                }

        stale = [sid for sid, d in self._tracks.items() if frame_number - d["last_seen_frame"] > self.grace_period]
        for sid in stale:
            del self._tracks[sid]

        return assigned_ids, new_creations

class KalmanPersonTrack:
    def __init__(self, track_id: int, centroid: tuple[float, float], frame_number: int):
        self.track_id = track_id
        # State: [x, y, vx, vy] in normalized [0, 1] space
        cx, cy = centroid
        self.x = np.array([cx, cy, 0.0, 0.0], dtype=np.float32)
        # Covariance
        self.P = np.diag([0.01, 0.01, 0.1, 0.1]).astype(np.float32)
        # Process noise: low acceleration variance
        self.Q = np.diag([1e-4, 1e-4, 1e-3, 1e-3]).astype(np.float32)
        # Measurement noise: MoveNet keypoint jitter (~2% of frame)
        self.R = np.diag([4e-4, 4e-4]).astype(np.float32)
        self.last_seen_frame = frame_number
        self.hits = 1

    def predict(self) -> tuple[float, float]:
        # F = [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]]
        F = np.array([
            [1.0, 0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]
        ], dtype=np.float32)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        return float(self.x[0]), float(self.x[1])

    def update(self, centroid: tuple[float, float], frame_number: int):
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
        self.hits += 1

class Phase1KalmanTracker:
    def __init__(self, max_gating_dist: float = 0.18, grace_frames: int = 30):
        # max_gating_dist is in normalized diagonal units (0.18 ~ 18% of frame)
        self.max_gating_dist = max_gating_dist
        self.grace_frames = grace_frames
        self.tracks = {}
        self.next_id = 0

    def update(self, centroids, frame_number):
        track_ids = list(self.tracks.keys())
        predictions = {tid: self.tracks[tid].predict() for tid in track_ids}
        
        N = len(centroids)
        M = len(track_ids)
        assigned_ids = {}
        new_creations = 0

        if N > 0 and M > 0:
            cost_matrix = np.zeros((N, M), dtype=np.float32)
            for i, (cx, cy) in enumerate(centroids):
                for j, tid in enumerate(track_ids):
                    px, py = predictions[tid]
                    dist = ((cx - px)**2 + (cy - py)**2)**0.5
                    cost_matrix[i, j] = dist

            row_inds, col_inds = linear_sum_assignment(cost_matrix)
            matched_det = set()
            matched_trk = set()

            for r, c in zip(row_inds, col_inds):
                dist = cost_matrix[r, c]
                if dist <= self.max_gating_dist:
                    tid = track_ids[c]
                    assigned_ids[r] = tid
                    self.tracks[tid].update(centroids[r], frame_number)
                    matched_det.add(r)
                    matched_trk.add(tid)
        else:
            matched_det = set()

        for i in range(N):
            if i not in matched_det:
                new_id = self.next_id
                self.next_id += 1
                new_creations += 1
                assigned_ids[i] = new_id
                self.tracks[new_id] = KalmanPersonTrack(new_id, centroids[i], frame_number)

        stale = [tid for tid, trk in self.tracks.items() if frame_number - trk.last_seen_frame > self.grace_frames]
        for tid in stale:
            del self.tracks[tid]

        return assigned_ids, new_creations

def run_comparison(video_p, max_frames=900):
    cap = cv2.VideoCapture(video_p)
    engine = MotionOptimizedEngine()
    engine.enable_movenet = True
    engine.enable_yolo = False

    t_old = OldCentroidTracker(max_distance=120.0, grace_period=30)
    t_phase1 = Phase1KalmanTracker(max_gating_dist=0.18, grace_frames=30)

    total_old_new_ids = 0
    total_phase1_new_ids = 0

    fidx = 0
    while cap.isOpened() and fidx < max_frames:
        ret, frame = cap.read()
        if not ret: break
        fidx += 1

        img_input = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_input = cv2.resize(img_input, (256, 256))
        input_data = np.expand_dims(img_input, axis=0).astype(np.int32)
        input_name = engine.movenet.get_inputs()[0].name
        outputs = engine.movenet.run(None, {input_name: input_data})
        people = outputs[0][0]

        # Extract raw keypoints passing ghost filter
        centroids_old = []
        centroids_proj = []

        for i in range(6):
            person = people[i, :51].reshape(17, 3)
            conf = np.mean(person[:, 2])
            if conf < 0.15: continue
            
            valid_kps = [kp for kp in person if kp[2] > 0.15]
            if len(valid_kps) < 4: continue

            has_hips = person[11, 2] > 0.15 and person[12, 2] > 0.15
            has_shoulders = person[5, 2] > 0.15 and person[6, 2] > 0.15

            # 1. Old Anchor (switching abruptly to shoulder or mean)
            if has_hips:
                c_old = ((person[11, 1] + person[12, 1])/2.0, (person[11, 0] + person[12, 0])/2.0)
            elif has_shoulders:
                c_old = ((person[5, 1] + person[6, 1])/2.0, (person[5, 0] + person[6, 0])/2.0)
            else:
                c_old = (float(np.mean([kp[1] for kp in valid_kps])), float(np.mean([kp[0] for kp in valid_kps])))
            centroids_old.append(c_old)

            # 2. Projected Anatomical Anchor (Task 1.1)
            if has_hips:
                c_proj = ((person[11, 1] + person[12, 1])/2.0, (person[11, 0] + person[12, 0])/2.0)
            elif has_shoulders:
                sh_x = (person[5, 1] + person[6, 1])/2.0
                sh_y = (person[5, 0] + person[6, 0])/2.0
                sh_w = abs(person[5, 1] - person[6, 1])
                torso_offset = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
                c_proj = (sh_x, min(1.0, sh_y + torso_offset))
            else:
                c_proj = (float(np.mean([kp[1] for kp in valid_kps])), float(np.mean([kp[0] for kp in valid_kps])))
            centroids_proj.append(c_proj)

        _, n_old = t_old.update(centroids_old, fidx)
        _, n_p1 = t_phase1.update(centroids_proj, fidx)

        total_old_new_ids += n_old
        total_phase1_new_ids += n_p1

    cap.release()
    print(f"\n=======================================================")
    print(f" COMPARISON OVER {fidx} FRAMES (60.0s of real CCTV footage)")
    print(f"=======================================================")
    print(f"Old Centroid Tracker (Root Causes A, G, C active) : {total_old_new_ids} New IDs spawned")
    print(f"Phase 1 Kalman + Anatomical Anchor Tracker       : {total_phase1_new_ids} New IDs spawned")
    pct_reduction = ((total_old_new_ids - total_phase1_new_ids) / total_old_new_ids) * 100.0
    print(f"Identity Flip / Fragmentation Reduction          : {pct_reduction:.1f}%")
    print(f"=======================================================")

if __name__ == "__main__":
    run_comparison(r"recordings\cam_14\2026-08-25\event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4", 900)
