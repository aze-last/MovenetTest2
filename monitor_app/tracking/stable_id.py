from __future__ import annotations

import threading
import time
from typing import Dict, List, Tuple
import numpy as np
from scipy.optimize import linear_sum_assignment

from monitor_app.evidence import TrackedPerson
from monitor_app.config import get_config
from monitor_app.monitor_logging import SystemEvents


class KalmanCentroidTracker:
    """Linear 2D Kalman filter for centroid tracking [x, y, vx, vy] in normalized coordinates."""

    def __init__(self, x: float, y: float):
        # State vector: [x, y, vx, vy]
        self.state = np.array([x, y, 0.0, 0.0], dtype=np.float32)
        # State covariance P
        self.P = np.diag([1e-2, 1e-2, 1.0, 1.0]).astype(np.float32)
        # Process noise Q
        self.Q = np.diag([1e-4, 1e-4, 1e-2, 1e-2]).astype(np.float32)
        # Measurement noise R
        self.R = np.diag([1e-3, 1e-3]).astype(np.float32)
        # Measurement matrix H
        self.H = np.array([[1.0, 0.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0, 0.0]], dtype=np.float32)

    def predict(self, dt: float = 1.0) -> Tuple[float, float]:
        """Predicts the next state and covariance with velocity damping."""
        decay = 0.95
        F = np.array([
            [1.0, 0.0, dt * decay, 0.0],
            [0.0, 1.0, 0.0, dt * decay],
            [0.0, 0.0, decay, 0.0],
            [0.0, 0.0, 0.0, decay]
        ], dtype=np.float32)
        self.state = F @ self.state
        self.P = F @ self.P @ F.T + self.Q
        return float(self.state[0]), float(self.state[1])

    def update(self, z_x: float, z_y: float):
        """Updates state with observed measurement [z_x, z_y]."""
        z = np.array([z_x, z_y], dtype=np.float32)
        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        det = S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0]
        if abs(det) < 1e-9:
            S_inv = np.diag([1.0 / max(1e-6, S[0, 0]), 1.0 / max(1e-6, S[1, 1])]).astype(np.float32)
        else:
            S_inv = (1.0 / det) * np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]], dtype=np.float32)
        K = self.P @ self.H.T @ S_inv
        self.state = self.state + K @ y
        I = np.eye(4, dtype=np.float32)
        self.P = (I - K @ self.H) @ self.P


class StableIDTracker:
    """Assigns stable IDs to detected persons using Kalman-predicted motion and Hungarian association."""

    def __init__(self, max_distance: float = None, grace_period: int = None):
        if max_distance is None:
            max_distance = get_config("tracking", "stable_id", {}).get("max_distance", 120.0)
        if grace_period is None:
            grace_period = get_config("tracking", "stable_id", {}).get("grace_frames", 30)

        self.max_distance = max_distance
        self.grace_period = grace_period
        self._tracks: Dict[int, Dict[str, object]] = {}
        self._next_id = 0

        # Concurrency safety
        self._update_lock = threading.Lock()

        # Diagnostics
        self._trace = bool(get_config("debug", "flicker_trace", False))
        self._last_frame_number = None
        self._inside = 0
        self._overlap_count = 0

    @staticmethod
    def _normalize_coords(pt: Tuple[float, float]) -> Tuple[float, float]:
        """Converts coordinates to normalized [0, 1] space if passed in raw pixel space."""
        x, y = pt
        nx = x / 1920.0 if x > 2.0 else x
        ny = y / 1080.0 if y > 2.0 else y
        return float(nx), float(ny)

    def update(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        with self._update_lock:
            return self._update_locked(persons, frame_number)

    def _update_locked(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        camera_id = persons[0].camera_id if persons else "-"

        # Concurrency instrumentation
        if self._trace:
            tid = threading.get_ident()
            entered_while = self._inside
            self._inside += 1
            if entered_while > 0:
                self._overlap_count += 1
                print(f"[FLICKER-A5] OVERLAP #{self._overlap_count}: cam={camera_id} "
                      f"thread={tid} entered update() while {entered_while} other thread(s) "
                      f"inside, t={time.perf_counter():.6f} frame={frame_number}", flush=True)
            else:
                print(f"[FLICKER-A5] enter cam={camera_id} thread={tid} "
                      f"t={time.perf_counter():.6f} frame={frame_number}", flush=True)

        # Reference pixel distance threshold
        gate_threshold_px = self.max_distance * 1920.0 if self.max_distance <= 1.0 else self.max_distance

        # 1. Predict state for all active tracks
        track_ids = list(self._tracks.keys())
        predictions = {}
        for sid in track_ids:
            kf: KalmanCentroidTracker = self._tracks[sid].get("kf")
            if kf is None:
                # Lazy initialization for legacy tracks
                raw_c = self._tracks[sid].get("hip_centroid", (0.0, 0.0))
                nx, ny = self._normalize_coords(raw_c)
                kf = KalmanCentroidTracker(nx, ny)
                self._tracks[sid]["kf"] = kf
            pred_x, pred_y = kf.predict()
            predictions[sid] = (pred_x, pred_y)

        # 2. Extract and normalize detected centroids
        detections = []
        for person in persons:
            raw_c = person.hip_centroid or (0.0, 0.0)
            detections.append(self._normalize_coords(raw_c))

        matched_tracks = set()
        matched_persons = set()
        trace_matches = []

        # 3. Hungarian Association (scipy linear_sum_assignment)
        if track_ids and detections:
            cost_matrix = np.zeros((len(track_ids), len(detections)), dtype=np.float32)
            for i, sid in enumerate(track_ids):
                pred_x, pred_y = predictions[sid]
                for j, (det_x, det_y) in enumerate(detections):
                    dist_px = (((pred_x - det_x) * 1920.0) ** 2 + ((pred_y - det_y) * 1080.0) ** 2) ** 0.5
                    cost_matrix[i, j] = dist_px

            row_ind, col_ind = linear_sum_assignment(cost_matrix)

            for r, c in zip(row_ind, col_ind):
                dist_px = float(cost_matrix[r, c])
                if dist_px <= gate_threshold_px:
                    sid = track_ids[r]
                    person = persons[c]
                    person.stable_id = sid

                    # Update Kalman filter
                    det_x, det_y = detections[c]
                    kf: KalmanCentroidTracker = self._tracks[sid]["kf"]
                    kf.update(det_x, det_y)

                    self._tracks[sid]["hip_centroid"] = person.hip_centroid or (0.0, 0.0)
                    # Enforce monotonic frame numbering (prevent out-of-order rewinding)
                    curr_last = int(self._tracks[sid].get("last_seen_frame", 0))
                    self._tracks[sid]["last_seen_frame"] = max(curr_last, frame_number)

                    matched_tracks.add(sid)
                    matched_persons.add(c)
                    if self._trace:
                        trace_matches.append((person.raw_person_id, sid, round(dist_px, 1)))

        # 4. Assign new IDs to remaining unmatched persons
        for p_idx, person in enumerate(persons):
            if p_idx not in matched_persons:
                new_id = self._next_id
                person.stable_id = new_id
                det_x, det_y = detections[p_idx]
                self._tracks[new_id] = {
                    "hip_centroid": person.hip_centroid or (0.0, 0.0),
                    "last_seen_frame": frame_number,
                    "kf": KalmanCentroidTracker(det_x, det_y),
                }
                SystemEvents.stable_id_created(camera_id, new_id)
                self._next_id += 1

        # 5. Retire stale tracks exceeding grace period
        stale_ids = [
            sid for sid, data in self._tracks.items()
            if frame_number - int(data.get("last_seen_frame", 0)) > self.grace_period
        ]
        for sid in stale_ids:
            SystemEvents.stable_id_lost(camera_id, sid)
            del self._tracks[sid]

        # Diagnostics trace
        if self._trace:
            new_ids = [p.stable_id for i, p in enumerate(persons) if i not in matched_persons]
            frame_delta = None if self._last_frame_number is None else (frame_number - self._last_frame_number)
            leap = frame_delta is not None and frame_delta > self.grace_period
            print(f"[FLICKER-A4] cam={camera_id} frame={frame_number} d_frame={frame_delta} "
                  f"{'LEAP>grace ' if leap else ''}matches={trace_matches} new_ids={new_ids} "
                  f"stale_deleted={stale_ids} live_tracks={sorted(self._tracks.keys())}", flush=True)

        self._last_frame_number = frame_number

        if self._trace:
            self._inside -= 1
            print(f"[FLICKER-A5] exit  cam={camera_id} thread={threading.get_ident()} "
                  f"t={time.perf_counter():.6f} frame={frame_number}", flush=True)

        return persons
