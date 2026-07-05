from __future__ import annotations

from typing import List, Optional

from monitor_app.config import get_concealment_config
from monitor_app.evidence import (
    BehaviorEvidence,
    FusedConcealmentObservation,
    HandObservationState,
)
from monitor_app.behaviors.base import BehaviorDetector
from monitor_app.monitor_logging import SystemEvents


class ConcealmentDetector(BehaviorDetector):
    """
    Sustained concealment detector driven by multi-camera fused hand observations.
    """

    name: str = "concealment"

    def __init__(self):
        self._load_config()
        self.states: dict[tuple[str, int], dict[str, int]] = {}

    def _load_config(self):
        behavior = get_concealment_config("behavior", {}) or {}
        self.duration_frames = int(behavior.get("duration_frames", 27))
        self.cooldown_frames = int(behavior.get("cooldown_frames", 60))
        self.decay_frames = int(behavior.get("decay_frames", 1))
        fusion = get_concealment_config("fusion", {}) or {}
        self.min_fused_confidence = float(fusion.get("min_fused_confidence", 0.75))

    def detect(self, person, frame_index: int, sensitivity: str):
        """Legacy per-person interface — concealment now uses process_fused()."""
        return None

    def process_fused(
        self,
        fused_observations: List[FusedConcealmentObservation],
        frame_index: int,
        sensitivity: str,
        camera_id: str,
        timestamp: float,
    ) -> List[BehaviorEvidence]:
        evidence_list: List[BehaviorEvidence] = []

        concealed_hands = [
            obs
            for obs in fused_observations
            if obs.fused_state == HandObservationState.CONCEALED
            and obs.fused_confidence >= self.min_fused_confidence
            and camera_id in obs.supporting_cameras
        ]

        active_keys = set()
        for fused in concealed_hands:
            state_key = (fused.zone_id, fused.subject_slot)
            active_keys.add(state_key)
            state = self._get_state(state_key)

            if frame_index < state["cooldown_until"]:
                continue

            state["occlusion_counter"] += 1
            SystemEvents.behavior_rejected(
                camera_id,
                fused.camera_stable_ids.get(camera_id, fused.subject_slot),
                "concealment",
                (
                    f"Fused {fused.hand.value} concealed | "
                    f"Counter: {state['occlusion_counter']}/{self.duration_frames} | "
                    f"Support: {fused.supporting_cameras}"
                ),
            )

            if state["occlusion_counter"] < self.duration_frames:
                continue

            state["occlusion_counter"] = 0
            state["cooldown_until"] = frame_index + self.cooldown_frames

            confidence = self._sensitivity_confidence(sensitivity, fused.fused_confidence)
            stable_id = int(fused.camera_stable_ids.get(camera_id, fused.subject_slot))
            reason = (
                f"Multi-camera fused {fused.hand.value} hand concealed | "
                f"Support: {', '.join(fused.supporting_cameras)} | "
                f"Duration: {self.duration_frames} frames"
            )

            evidence = BehaviorEvidence(
                behavior_type="concealment",
                stable_id=stable_id,
                confidence=confidence,
                frame_number=frame_index,
                timestamp=timestamp,
                sustained_frames=self.duration_frames,
                metadata={
                    "fusion_confirmed": True,
                    "zone_id": fused.zone_id,
                    "subject_slot": fused.subject_slot,
                    "hand": fused.hand.value,
                    "supporting_cameras": list(fused.supporting_cameras),
                },
                camera_id=camera_id,
                supporting_metrics={
                    "fused_confidence": fused.fused_confidence,
                    "supporting_cameras": list(fused.supporting_cameras),
                    "vetoing_cameras": list(fused.vetoing_cameras),
                    "unknown_cameras": list(fused.unknown_cameras),
                },
                reason=reason,
            )
            SystemEvents.behavior_detected(camera_id, stable_id, "concealment", reason)
            evidence_list.append(evidence)

        for state_key, state in list(self.states.items()):
            if state_key in active_keys:
                continue
            if state["occlusion_counter"] > 0:
                state["occlusion_counter"] = max(
                    0, state["occlusion_counter"] - self.decay_frames
                )

        return evidence_list

    def _get_state(self, state_key: tuple[str, int]) -> dict[str, int]:
        if state_key not in self.states:
            self.states[state_key] = {"occlusion_counter": 0, "cooldown_until": 0}
        return self.states[state_key]

    @staticmethod
    def _sensitivity_confidence(sensitivity: str, fused_confidence: float) -> float:
        base = max(0.75, min(0.95, fused_confidence))
        if sensitivity == "high":
            return min(0.95, base + 0.05)
        if sensitivity == "low":
            return max(0.70, base - 0.05)
        return base


_detector: Optional[ConcealmentDetector] = None


def get_concealment_detector() -> ConcealmentDetector:
    global _detector
    if _detector is None:
        _detector = ConcealmentDetector()
    return _detector
