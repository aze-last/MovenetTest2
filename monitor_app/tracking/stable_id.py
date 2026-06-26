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
        matched_ids = set()
        camera_id = persons[0].camera_id if persons else "-"

        for person in persons:
            centroid = person.hip_centroid or (0.0, 0.0)
            best_id = None
            best_dist = self.max_distance

            for stable_id, data in self._tracks.items():
                if stable_id in matched_ids:
                    continue
                existing_centroid = data.get("hip_centroid", (0.0, 0.0))
                if not isinstance(existing_centroid, tuple):
                    existing_centroid = tuple(existing_centroid)
                ex, ey = existing_centroid
                cx, cy = centroid
                dist = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_id = stable_id

            if best_id is not None:
                person.stable_id = best_id
                self._tracks[best_id]["hip_centroid"] = centroid
                self._tracks[best_id]["last_seen_frame"] = frame_number
                matched_ids.add(best_id)
            else:
                person.stable_id = self._next_id
                self._tracks[person.stable_id] = {
                    "hip_centroid": centroid,
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
