from __future__ import annotations

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

    def update(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        camera_id = persons[0].camera_id if persons else "-"

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

        for p_idx, stable_id, dist in possible_matches:
            if p_idx in matched_persons or stable_id in matched_tracks:
                continue

            person = persons[p_idx]
            person.stable_id = stable_id
            self._tracks[stable_id]["hip_centroid"] = person.hip_centroid or (0.0, 0.0)
            self._tracks[stable_id]["last_seen_frame"] = frame_number

            matched_persons.add(p_idx)
            matched_tracks.add(stable_id)

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

        return persons
