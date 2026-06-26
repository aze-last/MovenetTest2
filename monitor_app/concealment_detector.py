from __future__ import annotations

from typing import Optional

from monitor_app.evidence import BehaviorEvidence, TrackedPerson


class ConcealmentDetector:
    """Simple detector that flags suspicious concealment when wrists appear missing."""

    def __init__(self, sensitivity: str = "medium"):
        self.sensitivity = sensitivity

    def analyze(self, person: TrackedPerson, sensitivity: str | None = None) -> Optional[BehaviorEvidence]:
        sensitivity = sensitivity or self.sensitivity
        keypoints = person.keypoints
        if keypoints is None or len(keypoints) <= 10:
            return None

        left_wrist = keypoints[9]
        right_wrist = keypoints[10]
        left_missing = float(left_wrist[2]) < 0.2
        right_missing = float(right_wrist[2]) < 0.2

        if not (left_missing or right_missing):
            return None

        confidence = 0.6 if sensitivity == "low" else 0.75 if sensitivity == "high" else 0.7
        return BehaviorEvidence(
            behavior_type="concealment",
            stable_id=person.stable_id,
            confidence=confidence,
            frame_number=person.frame_number,
            timestamp=person.timestamp,
            sustained_frames=1,
            metadata={"missing_wrists": [left_missing, right_missing]},
        )


def analyze(person: TrackedPerson, sensitivity: str = "medium") -> Optional[BehaviorEvidence]:
    return ConcealmentDetector(sensitivity=sensitivity).analyze(person, sensitivity=sensitivity)
