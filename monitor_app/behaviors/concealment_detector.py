import math
from typing import Optional
from monitor_app.config import get_config
from monitor_app.evidence import BehaviorEvidence, TrackedPerson
from monitor_app.behaviors.base import BehaviorDetector
from monitor_app.monitor_logging import SystemEvents

class ConcealmentDetector(BehaviorDetector):
    """
    Sustained One-Hand Occlusion Detector.
    Tracks wrist occlusion over time, ignoring side-profile angles using a normalized yaw gate.
    """
    name: str = "concealment"

    def __init__(self):
        # Configuration
        self.duration_frames = get_config("behavior", "concealment", {}).get("duration_frames", 27)
        self.cooldown_frames = get_config("behavior", "concealment", {}).get("cooldown_frames", 60)
        self.yaw_gate_threshold = get_config("behavior", "concealment", {}).get("yaw_gate_threshold", 30.0)
        self.wrist_confidence_threshold = get_config("behavior", "concealment", {}).get("wrist_confidence_threshold", 0.2)
        
        # State tracking: stable_id -> {"occlusion_counter": 0, "cooldown_until": 0}
        self.states = {}

    def detect(self, person: TrackedPerson, frame_index: int, sensitivity: str) -> Optional[BehaviorEvidence]:
        stable_id = person.stable_id
        camera_id = person.camera_id
        
        # Initialize state for this track if missing
        if stable_id not in self.states:
            self.states[stable_id] = {
                "occlusion_counter": 0,
                "cooldown_until": 0
            }
            
        state = self.states[stable_id]
        
        # Check cooldown
        if frame_index < state["cooldown_until"]:
            return None

        # Keypoints: nose(0), l_shoulder(5), r_shoulder(6), l_hip(11), r_hip(12), l_wrist(9), r_wrist(10)
        kps = person.keypoints
        if kps is None or len(kps) <= 12:
            return None
            
        # Get wrist confidences
        l_wrist_conf = kps[9, 2]
        r_wrist_conf = kps[10, 2]
        
        l_missing = l_wrist_conf < self.wrist_confidence_threshold
        r_missing = r_wrist_conf < self.wrist_confidence_threshold
        
        # Calculate yaw using pre-computed torso height and shoulder width
        yaw_ratio = 0.0
        yaw_angle = 0.0
        
        if person.torso_height > 0:
            yaw_ratio = person.shoulder_width / person.torso_height
            # Estimate angle in degrees (0 is front-facing, 90 is side profile)
            # Reference ratio: fully frontal shoulder width / torso height is ~1.0
            cos_yaw = min(1.0, max(0.0, yaw_ratio))
            yaw_angle = math.acos(cos_yaw) * 180.0 / math.pi

        # Yaw gate suppression: Only run occlusion check if frontal/rear facing
        is_frontal = yaw_angle < self.yaw_gate_threshold
        
        # Exactly one wrist is hidden
        one_wrist_occluded = (l_missing != r_missing)
        
        if is_frontal:
            if one_wrist_occluded:
                state["occlusion_counter"] += 1
                SystemEvents.behavior_rejected(
                    camera_id, stable_id, "concealment",
                    f"Wrist occluded (L: {l_missing}, R: {r_missing}) | Counter: {state['occlusion_counter']}/{self.duration_frames}"
                )
            else:
                # Reset counter if both are visible or both are missing (not suspicious)
                if state["occlusion_counter"] > 0:
                    state["occlusion_counter"] = max(0, state["occlusion_counter"] - 1)
        else:
            # Person is in side profile, suppress alerts and reset counter
            if state["occlusion_counter"] > 0:
                state["occlusion_counter"] = max(0, state["occlusion_counter"] - 1)
            SystemEvents.behavior_rejected(
                camera_id, stable_id, "concealment",
                f"Yaw gate suppression active | Yaw angle: {yaw_angle:.1f}° >= {self.yaw_gate_threshold}°"
            )

        # Trigger check
        if state["occlusion_counter"] >= self.duration_frames:
            # Confirm behavior
            state["occlusion_counter"] = 0
            state["cooldown_until"] = frame_index + self.cooldown_frames
            
            # Confidence score dependent on active sensitivity level
            confidence = 0.85
            if sensitivity == "high":
                confidence = 0.90
            elif sensitivity == "low":
                confidence = 0.75
                
            reason = f"Single wrist hidden, Yaw angle = {yaw_angle:.1f}°, Duration = {self.duration_frames} frames"
            
            evidence = BehaviorEvidence(
                behavior_type="concealment",
                stable_id=stable_id,
                confidence=confidence,
                frame_number=frame_index,
                timestamp=person.timestamp,
                sustained_frames=self.duration_frames,
                metadata={"missing_wrists": [l_missing, r_missing], "yaw_angle": yaw_angle},
                camera_id=camera_id,
                supporting_metrics={
                    "yaw_angle": yaw_angle,
                    "yaw_ratio": yaw_ratio,
                    "left_wrist_conf": float(l_wrist_conf),
                    "right_wrist_conf": float(r_wrist_conf)
                },
                reason=reason
            )
            
            SystemEvents.behavior_detected(camera_id, stable_id, "concealment", reason)
            return evidence

        return None
