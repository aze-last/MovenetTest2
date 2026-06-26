import math
import numpy as np
from typing import Dict, List
from monitor_app.evidence import EvidencePacket, TrackedPerson, BehaviorEvidence
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.behaviors.registry import get_active_detectors

class BehaviorEngine:
    """
    Coordinates stable tracking, pre-computing body metrics, 
    and executing behavior detectors.
    """
    def __init__(self):
        # Maps camera_id -> StableIDTracker instance
        self.trackers: Dict[str, StableIDTracker] = {}
        # List of instantiated behavior detectors
        self.detectors = get_active_detectors()

    def _get_tracker(self, camera_id: str) -> StableIDTracker:
        if camera_id not in self.trackers:
            self.trackers[camera_id] = StableIDTracker()
        return self.trackers[camera_id]

    def analyze_packet(self, packet: EvidencePacket, frame_index: int, sensitivity: str) -> EvidencePacket:
        if not packet.tracked_persons:
            return packet

        # 1. Update stable tracking IDs
        tracker = self._get_tracker(packet.camera_id)
        tracked_persons = tracker.update(packet.tracked_persons, frame_index)
        packet.tracked_persons = tracked_persons

        # 2. Pre-calculate torso height and shoulder width in pixel space
        frame_h, frame_w = packet.frame.shape[:2]
        
        for person in tracked_persons:
            kps = person.keypoints
            if kps is not None and len(kps) > 12:
                # Scaled keypoints: [y, x, conf] * [frame_h, frame_w, 1]
                scaled_y = kps[:, 0] * frame_h
                scaled_x = kps[:, 1] * frame_w
                
                # Shoulders (index 5 & 6)
                ls_x, ls_y = scaled_x[5], scaled_y[5]
                rs_x, rs_y = scaled_x[6], scaled_y[6]
                
                # Hips (index 11 & 12)
                lh_x, lh_y = scaled_x[11], scaled_y[11]
                rh_x, rh_y = scaled_x[12], scaled_y[12]
                
                # Pre-compute Shoulder Width
                shoulder_width = math.sqrt((ls_x - rs_x) ** 2 + (ls_y - rs_y) ** 2)
                
                # Pre-compute Torso Height (midpoint shoulder to midpoint hip)
                mid_shoulder_x = (ls_x + rs_x) / 2.0
                mid_shoulder_y = (ls_y + rs_y) / 2.0
                mid_hip_x = (lh_x + rh_x) / 2.0
                mid_hip_y = (lh_y + rh_y) / 2.0
                
                torso_height = math.sqrt((mid_shoulder_x - mid_hip_x) ** 2 + (mid_shoulder_y - mid_hip_y) ** 2)
                
                person.shoulder_width = shoulder_width
                person.torso_height = torso_height

        # 3. Execute all active behavior detectors
        for person in tracked_persons:
            for detector in self.detectors:
                evidence = detector.detect(person, frame_index, sensitivity)
                if evidence is not None:
                    packet.behavior_evidence.append(evidence)

        return packet

# Global singleton
_behavior_engine = BehaviorEngine()

def get_behavior_engine() -> BehaviorEngine:
    return _behavior_engine
