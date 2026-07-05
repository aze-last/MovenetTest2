from __future__ import annotations

import math
from typing import List, Optional

from monitor_app.config import get_concealment_config
from monitor_app.evidence import (
    HandObservation,
    HandObservationState,
    HandSide,
    TrackedPerson,
)


class HandObservationClassifier:
    """Classify per-camera hand states from MoveNet keypoints."""

    def __init__(self):
        self._load_config()

    def _load_config(self):
        per_camera = get_concealment_config("per_camera", {}) or {}
        self.wrist_visible_threshold = float(
            per_camera.get("wrist_visible_threshold", 0.35)
        )
        self.wrist_missing_threshold = float(
            per_camera.get("wrist_missing_threshold", 0.20)
        )
        self.yaw_gate_threshold = float(per_camera.get("yaw_gate_threshold", 30.0))
        self.min_pose_confidence = float(per_camera.get("min_pose_confidence", 0.25))

    def classify_person(
        self, person: TrackedPerson, frame_index: int
    ) -> List[HandObservation]:
        kps = person.keypoints
        if kps is None or len(kps) <= 12:
            return []

        l_wrist_conf = float(kps[9, 2])
        r_wrist_conf = float(kps[10, 2])
        yaw_angle, view_quality = self._compute_view_metrics(person)

        l_visible = l_wrist_conf >= self.wrist_visible_threshold
        r_visible = r_wrist_conf >= self.wrist_visible_threshold
        l_missing = l_wrist_conf < self.wrist_missing_threshold
        r_missing = r_wrist_conf < self.wrist_missing_threshold
        is_frontal = yaw_angle < self.yaw_gate_threshold
        both_missing = l_missing and r_missing

        observations = []
        for hand, wrist_conf, visible, missing, other_missing in (
            (HandSide.LEFT, l_wrist_conf, l_visible, l_missing, r_missing),
            (HandSide.RIGHT, r_wrist_conf, r_visible, r_missing, l_missing),
        ):
            state, confidence = self._classify_hand(
                visible=visible,
                missing=missing,
                other_missing=other_missing,
                both_missing=both_missing,
                is_frontal=is_frontal,
                wrist_conf=wrist_conf,
                view_quality=view_quality,
            )
            observations.append(
                HandObservation(
                    camera_id=str(person.camera_id),
                    stable_id=int(person.stable_id),
                    hand=hand,
                    state=state,
                    confidence=confidence,
                    timestamp=float(person.timestamp),
                    frame_index=int(frame_index),
                    view_quality=view_quality,
                    hip_centroid=person.hip_centroid,
                    sources={
                        "wrist_conf": wrist_conf,
                        "yaw_angle": yaw_angle,
                        "is_frontal": is_frontal,
                        "both_missing": both_missing,
                    },
                )
            )
        return observations

    def _compute_view_metrics(self, person: TrackedPerson) -> tuple[float, float]:
        yaw_angle = 90.0
        if person.torso_height > 0:
            yaw_ratio = person.shoulder_width / person.torso_height
            cos_yaw = min(1.0, max(0.0, yaw_ratio))
            yaw_angle = math.acos(cos_yaw) * 180.0 / math.pi
        view_quality = max(0.0, min(1.0, 1.0 - (yaw_angle / 90.0)))
        return yaw_angle, view_quality

    def _classify_hand(
        self,
        visible: bool,
        missing: bool,
        other_missing: bool,
        both_missing: bool,
        is_frontal: bool,
        wrist_conf: float,
        view_quality: float,
    ) -> tuple[HandObservationState, float]:
        if not is_frontal:
            return HandObservationState.UNKNOWN, 0.0

        if both_missing:
            return HandObservationState.UNKNOWN, 0.0

        if visible:
            return HandObservationState.VISIBLE, wrist_conf

        if missing and not other_missing:
            conceal_conf = max(0.0, min(1.0, 1.0 - wrist_conf))
            if view_quality >= float(
                (get_concealment_config("fusion", {}) or {}).get(
                    "min_frontal_quality", 0.60
                )
            ):
                return HandObservationState.CONCEALED, conceal_conf

        return HandObservationState.UNKNOWN, 0.0


_classifier: Optional[HandObservationClassifier] = None


def get_hand_observation_classifier() -> HandObservationClassifier:
    global _classifier
    if _classifier is None:
        _classifier = HandObservationClassifier()
    return _classifier
