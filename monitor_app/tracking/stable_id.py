from __future__ import annotations

import threading
import time
from typing import Dict, List

from monitor_app.evidence import TrackedPerson
from monitor_app.config import get_config
from monitor_app.monitor_logging import SystemEvents


class StableIDTracker:
    """Assigns stable IDs to detected persons using hip-centroid proximity."""

    def __init__(self, max_distance: float = None, grace_period: int = None):
        if max_distance is None:
            max_distance = get_config("tracking", "stable_id", {}).get("max_distance", 120.0)
        if grace_period is None:
            grace_period = get_config("tracking", "stable_id", {}).get("grace_frames", 30)

        self.max_distance = max_distance
        self.grace_period = grace_period
        self._tracks: Dict[int, Dict[str, object]] = {}
        self._next_id = 0
        # RC-1 fix: update() is entered concurrently from the MoveNet executor thread
        # (ai_engine._run_movenet_logic, update #1) and the central worker thread
        # (behaviors/engine.analyze_packet, update #2) — proven by the A5 harness
        # (tests/diag_rc1_concurrency.py: 103 overlaps / 10s pre-fix). The lock makes
        # the double-update safe; collapsing it to a single update remains deferred (C4).
        self._update_lock = threading.Lock()
        # Phase A4 diagnostics
        self._trace = bool(get_config("debug", "flicker_trace", False))
        self._last_frame_number = None
        # Phase A5 diagnostics: prove/refute concurrent entry into update() from two
        # threads (RC-1). _inside tracks how many threads are currently executing
        # update(); any observation of _inside > 0 on entry is a concurrency overlap.
        self._inside = 0
        self._overlap_count = 0

    def update(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        with self._update_lock:
            return self._update_locked(persons, frame_number)

    def _update_locked(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        camera_id = persons[0].camera_id if persons else "-"

        # Phase A5: concurrency evidence (RC-1). Reads/writes of _inside are themselves
        # unsynchronized on purpose — this instrument must not introduce the very lock
        # whose absence it is trying to prove matters.
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

        # 1. Compute all pairwise distances
        possible_matches = []
        for p_idx, person in enumerate(persons):
            centroid = person.hip_centroid or (0.0, 0.0)
            cx, cy = centroid

            for stable_id, data in self._tracks.items():
                existing_centroid = data.get("hip_centroid", (0.0, 0.0))
                if not isinstance(existing_centroid, tuple):
                    existing_centroid = tuple(existing_centroid)
                ex, ey = existing_centroid

                # Check if coordinates are normalized (with margin for out-of-bounds tracking near edges)
                # while allowing large pixel coordinates (e.g. in tests) to remain unscaled.
                is_normalized_e = (-1.0 <= ex <= 2.0) and (-1.0 <= ey <= 2.0)
                is_normalized_c = (-1.0 <= cx <= 2.0) and (-1.0 <= cy <= 2.0)

                ex_scaled = ex * 1920.0 if is_normalized_e else ex
                ey_scaled = ey * 1080.0 if is_normalized_e else ey
                cx_scaled = cx * 1920.0 if is_normalized_c else cx
                cy_scaled = cy * 1080.0 if is_normalized_c else cy

                dist = ((cx_scaled - ex_scaled) ** 2 + (cy_scaled - ey_scaled) ** 2) ** 0.5
                if dist < self.max_distance:
                    possible_matches.append((p_idx, stable_id, dist))

        # 2. Sort matches by distance
        possible_matches.sort(key=lambda x: x[2])

        # 3. Match by minimum distance order
        matched_persons = set()
        matched_tracks = set()

        trace_matches = []  # Phase A4: (raw_person_id -> stable_id, dist)
        for p_idx, stable_id, dist in possible_matches:
            if p_idx in matched_persons or stable_id in matched_tracks:
                continue

            person = persons[p_idx]
            person.stable_id = stable_id
            self._tracks[stable_id]["hip_centroid"] = person.hip_centroid or (0.0, 0.0)
            self._tracks[stable_id]["last_seen_frame"] = frame_number

            matched_persons.add(p_idx)
            matched_tracks.add(stable_id)
            if self._trace:
                trace_matches.append((person.raw_person_id, stable_id, round(dist, 1)))

        # 4. Assign new IDs to remaining unmatched persons
        for p_idx, person in enumerate(persons):
            if p_idx not in matched_persons:
                person.stable_id = self._next_id
                self._tracks[person.stable_id] = {
                    "hip_centroid": person.hip_centroid or (0.0, 0.0),
                    "last_seen_frame": frame_number,
                }
                SystemEvents.stable_id_created(camera_id, person.stable_id)
                self._next_id += 1

        stale_ids = [
            sid for sid, data in self._tracks.items()
            if frame_number - int(data.get("last_seen_frame", 0)) > self.grace_period
        ]
        for sid in stale_ids:
            SystemEvents.stable_id_lost(camera_id, sid)
            del self._tracks[sid]

        # Phase A4: trace matches/creates/deletes + detect frame-number leaps past the grace
        # window (a motion-gate-skip streak that would strand tracks and force fresh IDs).
        if self._trace:
            new_ids = [p.stable_id for i, p in enumerate(persons) if i not in matched_persons]
            frame_delta = None if self._last_frame_number is None else (frame_number - self._last_frame_number)
            leap = frame_delta is not None and frame_delta > self.grace_period
            print(f"[FLICKER-A4] cam={camera_id} frame={frame_number} d_frame={frame_delta} "
                  f"{'LEAP>grace ' if leap else ''}matches={trace_matches} new_ids={new_ids} "
                  f"stale_deleted={stale_ids} live_tracks={sorted(self._tracks.keys())}", flush=True)
        self._last_frame_number = frame_number

        # Phase A5: exit marker (paired with the entry instrument above)
        if self._trace:
            self._inside -= 1
            print(f"[FLICKER-A5] exit  cam={camera_id} thread={threading.get_ident()} "
                  f"t={time.perf_counter():.6f} frame={frame_number}", flush=True)

        return persons
