import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
from scipy.optimize import linear_sum_assignment

# Let's inspect the exact frames_data from run_mot_benchmark_rtx2050
from scratch.run_mot_benchmark_rtx2050 import LegacyCentroidTracker, VIDEO_PATH
from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.evidence import TrackedPerson
import cv2

cap = cv2.VideoCapture(VIDEO_PATH)
engine = MotionOptimizedEngine()
input_name = engine.movenet.get_inputs()[0].name

frames = []
for f_idx in range(450):
    ret, frame = cap.read()
    if not ret: break
    frame_h, frame_w = frame.shape[:2]
    inp = np.expand_dims(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (256, 256)), 0).astype(np.int32)
    out = engine.movenet.run(None, {input_name: inp})
    people = out[0][0]
    p_list = []
    for i in range(6):
        person = people[i, :51].reshape(17, 3)
        conf = float(people[i, 55])
        if conf < 0.2: continue
        valid_kps = [kp for kp in person if kp[2] > 0.12]
        if len(valid_kps) < 3: continue
        has_hips = person[11, 2] > 0.12 and person[12, 2] > 0.12
        has_shoulders = person[5, 2] > 0.12 and person[6, 2] > 0.12
        if has_hips:
            c = ((person[11, 1] + person[12, 1]) / 2, (person[11, 0] + person[12, 0]) / 2)
        elif has_shoulders:
            sh_w = abs(person[5, 1] - person[6, 1])
            torso_offset_y = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
            sh_x = (person[5, 1] + person[6, 1]) / 2
            sh_y = (person[5, 0] + person[6, 0]) / 2
            c = (sh_x, min(1.0, sh_y + torso_offset_y))
        else:
            c = (float(np.mean([kp[1] for kp in valid_kps])), float(np.mean([kp[0] for kp in valid_kps])))
        p_list.append(TrackedPerson(
            stable_id=-1, raw_person_id=i, camera_id="cam14",
            keypoints=person, hip_centroid=c, confidence=conf,
            frame_number=f_idx, timestamp=f_idx/30.0
        ))
    frames.append((f_idx, p_list))
cap.release()

print(f"Captured {len(frames)} frames. Testing tracker variants...")

# Variant A: Legacy Centroid
legacy = LegacyCentroidTracker(max_distance=120.0, grace_period=30)
for f_idx, plist in frames:
    legacy.update(plist, f_idx)
print(f"Legacy Unique IDs: {legacy._next_id}")

# Variant B: Kalman with velocity damping and min(dist_pred, dist_last)
class TunedKalmanTracker:
    def __init__(self, max_distance=140.0, grace_period=30):
        self.max_distance = max_distance
        self.grace_period = grace_period
        self._tracks = {}
        self._next_id = 0

    def update(self, persons, frame_number):
        track_ids = list(self._tracks.keys())
        if track_ids and persons:
            cost_matrix = np.zeros((len(track_ids), len(persons)), dtype=np.float32)
            for i, sid in enumerate(track_ids):
                data = self._tracks[sid]
                last_x, last_y = data["hip_centroid"]
                vx, vy = data["vx"], data["vy"]
                # Damped prediction
                pred_x = last_x + vx * 0.7
                pred_y = last_y + vy * 0.7
                for j, p in enumerate(persons):
                    det_x, det_y = p.hip_centroid
                    # Distance to prediction AND distance to last seen
                    d_pred = (((pred_x - det_x)*1920.0)**2 + ((pred_y - det_y)*1080.0)**2)**0.5
                    d_last = (((last_x - det_x)*1920.0)**2 + ((last_y - det_y)*1080.0)**2)**0.5
                    cost_matrix[i, j] = min(d_pred, d_last)

            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            matched_tracks = set()
            matched_persons = set()
            for r, c in zip(row_ind, col_ind):
                if cost_matrix[r, c] <= self.max_distance:
                    sid = track_ids[r]
                    p = persons[c]
                    p.stable_id = sid
                    prev_x, prev_y = self._tracks[sid]["hip_centroid"]
                    cur_x, cur_y = p.hip_centroid
                    # Update velocity with EMA
                    self._tracks[sid]["vx"] = 0.5 * (cur_x - prev_x) + 0.5 * self._tracks[sid]["vx"]
                    self._tracks[sid]["vy"] = 0.5 * (cur_y - prev_y) + 0.5 * self._tracks[sid]["vy"]
                    self._tracks[sid]["hip_centroid"] = p.hip_centroid
                    self._tracks[sid]["last_seen_frame"] = frame_number
                    matched_tracks.add(sid)
                    matched_persons.add(c)

            for j, p in enumerate(persons):
                if j not in matched_persons:
                    p.stable_id = self._next_id
                    self._tracks[self._next_id] = {
                        "hip_centroid": p.hip_centroid,
                        "vx": 0.0, "vy": 0.0,
                        "last_seen_frame": frame_number
                    }
                    self._next_id += 1
        else:
            for p in persons:
                p.stable_id = self._next_id
                self._tracks[self._next_id] = {
                    "hip_centroid": p.hip_centroid,
                    "vx": 0.0, "vy": 0.0,
                    "last_seen_frame": frame_number
                }
                self._next_id += 1

        stale = [sid for sid, d in self._tracks.items() if frame_number - d["last_seen_frame"] > self.grace_period]
        for sid in stale: del self._tracks[sid]
        return persons

tuned = TunedKalmanTracker(max_distance=140.0, grace_period=30)
for f_idx, plist in frames:
    tuned.update(plist, f_idx)
print(f"Tuned Kalman Unique IDs: {tuned._next_id}")
