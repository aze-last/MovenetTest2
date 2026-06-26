import math
import time
import numpy as np
import pytest
from unittest.mock import patch

from monitor_app.evidence import EvidencePacket, TrackedPerson, BehaviorEvidence
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.behaviors.base import BehaviorDetector
from monitor_app.behaviors.concealment_detector import ConcealmentDetector
from monitor_app.behaviors.engine import BehaviorEngine
from monitor_app.monitor_logging import SystemEvents


def make_test_person(stable_id=-1, raw_person_id=0, camera_id="cam_01", left_wrist_conf=0.8, right_wrist_conf=0.8, yaw_type="frontal"):
    """
    Helper to generate a mock TrackedPerson.
    Keypoints: nose(0), l_shoulder(5), r_shoulder(6), l_hip(11), r_hip(12), l_wrist(9), r_wrist(10)
    MoveNet format: [y, x, conf] (normalized 0 to 1)
    """
    # Torso height is measured between shoulder midpoint and hip midpoint.
    # Shoulder width is measured between left and right shoulders.
    # Frontal: shoulder width (horizontal) is large.
    # Side-profile: shoulder width (horizontal) is small.
    if yaw_type == "frontal":
        # Left shoulder at x=0.4, Right shoulder at x=0.6 (Width = 0.2)
        # Hips at y=0.6, Shoulders at y=0.3 (Torso height = 0.3)
        # Yaw ratio = 0.2 / 0.3 = 0.66 (yaw angle ~48 deg)
        l_shoulder = [0.3, 0.4, 0.9]
        r_shoulder = [0.3, 0.6, 0.9]
        l_hip = [0.6, 0.4, 0.9]
        r_hip = [0.6, 0.6, 0.9]
    else:  # side-profile
        # Left shoulder at x=0.49, Right shoulder at x=0.51 (Width = 0.02)
        # Torso height = 0.3
        # Yaw ratio = 0.02 / 0.3 = 0.066 (yaw angle ~86 deg)
        l_shoulder = [0.3, 0.49, 0.9]
        r_shoulder = [0.3, 0.51, 0.9]
        l_hip = [0.6, 0.49, 0.9]
        r_hip = [0.6, 0.51, 0.9]
        
    kps = np.array([
        [0.1, 0.5, 0.9],  # Nose (0)
        [0.0, 0.0, 0.0],  # 1
        [0.0, 0.0, 0.0],  # 2
        [0.0, 0.0, 0.0],  # 3
        [0.0, 0.0, 0.0],  # 4
        l_shoulder,       # Left shoulder (5)
        r_shoulder,       # Right shoulder (6)
        [0.0, 0.0, 0.0],  # 7
        [0.0, 0.0, 0.0],  # 8
        [0.5, 0.4, left_wrist_conf],   # Left wrist (9)
        [0.5, 0.6, right_wrist_conf],  # Right wrist (10)
        l_hip,            # Left hip (11)
        r_hip,            # Right hip (12)
        [0.0, 0.0, 0.0],  # 13
        [0.0, 0.0, 0.0],  # 14
        [0.0, 0.0, 0.0],  # 15
        [0.0, 0.0, 0.0],  # 16
    ], dtype=float)

    return TrackedPerson(
        stable_id=stable_id,
        raw_person_id=raw_person_id,
        camera_id=camera_id,
        keypoints=kps,
        bbox=(100, 100, 200, 200),
        hip_centroid=(0.5, 0.6),
        confidence=0.85,
        frame_number=1,
        timestamp=time.time() if 'time' in globals() else 1.0,
    )


# ----------------------------------------------------
# 1. STABLE ID TESTS
# ----------------------------------------------------

def test_stable_id_proximity_and_grace_period():
    """Verify single person tracking maintains ID and handles grace period exit/entry."""
    tracker = StableIDTracker(max_distance=100.0, grace_period=3)
    
    # Initial Frame
    p1 = make_test_person(raw_person_id=0)
    persons = tracker.update([p1], frame_number=1)
    assert persons[0].stable_id == 0
    
    # Next Frame: Slightly moved hip (still within distance)
    p2 = make_test_person(raw_person_id=0)
    p2.hip_centroid = (0.52, 0.61)
    persons = tracker.update([p2], frame_number=2)
    assert persons[0].stable_id == 0
    
    # Exits frame briefly: empty list
    persons = tracker.update([], frame_number=3)
    assert len(persons) == 0
    
    # Reappears within grace period: should reuse ID 0
    p3 = make_test_person(raw_person_id=0)
    p3.hip_centroid = (0.53, 0.62)
    persons = tracker.update([p3], frame_number=4)
    assert persons[0].stable_id == 0
    
    # Exits longer than grace period: empty lists for 3 frames
    tracker.update([], frame_number=5)
    tracker.update([], frame_number=6)
    tracker.update([], frame_number=7)
    tracker.update([], frame_number=8)
    
    # Reappears after grace period: should assign a new ID
    p4 = make_test_person(raw_person_id=0)
    p4.hip_centroid = (0.53, 0.62)
    persons = tracker.update([p4], frame_number=9)
    assert persons[0].stable_id == 1


def test_stable_id_two_people_crossing():
    """Verify two people crossing trajectories maintain correct independent IDs."""
    tracker = StableIDTracker(max_distance=50.0, grace_period=10)
    
    # Frame 1: Separate positions
    p1 = make_test_person(raw_person_id=0)
    p1.hip_centroid = (10.0, 10.0)
    p2 = make_test_person(raw_person_id=1)
    p2.hip_centroid = (100.0, 10.0)
    
    res = tracker.update([p1, p2], frame_number=1)
    assert res[0].stable_id == 0
    assert res[1].stable_id == 1
    
    # Frame 2: Crossing closely
    p1_next = make_test_person(raw_person_id=0)
    p1_next.hip_centroid = (50.0, 10.0)
    p2_next = make_test_person(raw_person_id=1)
    p2_next.hip_centroid = (60.0, 10.0)
    
    res = tracker.update([p1_next, p2_next], frame_number=2)
    assert res[0].stable_id == 0
    assert res[1].stable_id == 1


# ----------------------------------------------------
# 2. YAW GATE TESTS
# ----------------------------------------------------

def mock_get_config(section, key, default=None):
    # Custom config for testing
    cfg = {
        "tracking": {"stable_id": {"max_distance": 120.0, "grace_frames": 30}},
        "behavior": {
            "concealment": {
                "duration_frames": 3,
                "cooldown_frames": 5,
                "yaw_gate_threshold": 30.0,
                "wrist_confidence_threshold": 0.2
            }
        }
    }
    return cfg.get(section, {}).get(key, default)


@patch("monitor_app.behaviors.concealment_detector.get_config", side_effect=mock_get_config)
def test_yaw_gate_suppression(mock_cfg):
    """Verify that frontal views allow detection, while side profiles suppress it."""
    detector = ConcealmentDetector()
    
    # 1. Frontal View, single wrist hidden (l_conf=0.8, r_conf=0.0)
    p_front = make_test_person(stable_id=0, left_wrist_conf=0.8, right_wrist_conf=0.0, yaw_type="frontal")
    # Precompute metrics (usually done by BehaviorEngine)
    p_front.torso_height = 100.0
    p_front.shoulder_width = 70.0 # yaw ratio = 0.7 -> cos_yaw = 0.7 -> angle ~45 deg
    
    # Overriding the detector threshold for testing or configuring it
    detector.yaw_gate_threshold = 50.0
    
    # Should increment counter because 45 < 50
    evidence = detector.detect(p_front, frame_index=1, sensitivity="medium")
    assert detector.states[0]["occlusion_counter"] == 1
    
    # 2. Side-profile View, single wrist hidden
    p_side = make_test_person(stable_id=1, left_wrist_conf=0.8, right_wrist_conf=0.0, yaw_type="side")
    p_side.torso_height = 100.0
    p_side.shoulder_width = 10.0 # yaw ratio = 0.1 -> cos_yaw = 0.1 -> angle ~84 deg
    
    # Should suppress (84 >= 50) and not increment counter
    detector.states[1] = {"occlusion_counter": 2, "cooldown_until": 0}
    evidence = detector.detect(p_side, frame_index=1, sensitivity="medium")
    assert detector.states[1]["occlusion_counter"] == 1 # Decrements/resets
    assert evidence is None


# ----------------------------------------------------
# 3. OCCLUSION AND COOLDOWN TESTS
# ----------------------------------------------------

@patch("monitor_app.behaviors.concealment_detector.get_config", side_effect=mock_get_config)
def test_occlusion_and_cooldown_cycles(mock_cfg):
    """Verify wrist occlusion conditions: one wrist missing, both missing, and cooldown cycle."""
    detector = ConcealmentDetector()
    detector.duration_frames = 3
    detector.cooldown_frames = 5
    
    # Frontal setup
    p_ok = make_test_person(stable_id=0, left_wrist_conf=0.8, right_wrist_conf=0.8)
    p_ok.torso_height = 100.0
    p_ok.shoulder_width = 90.0 # ~25 deg
    
    # Both visible: counter stays at 0
    assert detector.detect(p_ok, 1, "medium") is None
    assert detector.states[0]["occlusion_counter"] == 0
    
    # Both wrists missing (both conf = 0.0): should reset/decrement counter
    detector.states[0]["occlusion_counter"] = 2
    p_both_missing = make_test_person(stable_id=0, left_wrist_conf=0.0, right_wrist_conf=0.0)
    p_both_missing.torso_height = 100.0
    p_both_missing.shoulder_width = 90.0
    assert detector.detect(p_both_missing, 2, "medium") is None
    assert detector.states[0]["occlusion_counter"] == 1
    
    # Single wrist missing: counter increases
    p_one_missing = make_test_person(stable_id=0, left_wrist_conf=0.8, right_wrist_conf=0.0)
    p_one_missing.torso_height = 100.0
    p_one_missing.shoulder_width = 90.0
    
    # Frame 3: Counter goes 1 -> 2
    assert detector.detect(p_one_missing, 3, "medium") is None
    assert detector.states[0]["occlusion_counter"] == 2
    
    # Frame 4: Counter goes 2 -> 3 -> Triggers Alert!
    evidence = detector.detect(p_one_missing, 4, "medium")
    assert evidence is not None
    assert evidence.behavior_type == "concealment"
    assert evidence.reason != ""
    assert detector.states[0]["occlusion_counter"] == 0
    assert detector.states[0]["cooldown_until"] == 4 + 5 # cooldown_until = 9
    
    # Frame 5: Still occluded, but in cooldown
    evidence = detector.detect(p_one_missing, 5, "medium")
    assert evidence is None
    
    # Frame 9: Cooldown expired
    evidence = detector.detect(p_one_missing, 9, "medium")
    assert detector.states[0]["occlusion_counter"] == 1


# ----------------------------------------------------
# 4. PIPELINE / BEHAVIOR ENGINE INTEGRATION
# ----------------------------------------------------

@patch("monitor_app.behaviors.concealment_detector.get_config", side_effect=mock_get_config)
@patch("monitor_app.tracking.stable_id.get_config", side_effect=mock_get_config)
def test_behavior_engine_integration(mock_tracker_cfg, mock_det_cfg):
    """Test full integration: BehaviorEngine handles frame and runs registry."""
    engine = BehaviorEngine()
    
    # Create mock frame of size 640x480
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # Generate packet
    p = make_test_person(stable_id=-1, raw_person_id=0, left_wrist_conf=0.8, right_wrist_conf=0.0)
    packet = EvidencePacket(
        camera_id="01",
        timestamp=1.0,
        frame=frame,
        tracked_persons=[p]
    )
    
    # Run BehaviorEngine
    packet = engine.analyze_packet(packet, frame_index=1, sensitivity="medium")
    
    # Assertions
    assert len(packet.tracked_persons) == 1
    person = packet.tracked_persons[0]
    assert person.stable_id == 0 # Assigned by StableIDTracker
    assert person.torso_height > 0.0 # Computed in pixel coordinates
    assert person.shoulder_width > 0.0 # Computed in pixel coordinates
