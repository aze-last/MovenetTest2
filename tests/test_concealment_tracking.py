import math
import time
import numpy as np
import pytest
from unittest.mock import patch

from monitor_app.evidence import EvidencePacket, TrackedPerson, BehaviorEvidence
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.behaviors.base import BehaviorDetector
from monitor_app.behaviors.engine import BehaviorEngine
from monitor_app.monitor_logging import SystemEvents


def make_test_person(stable_id=-1, raw_person_id=0, camera_id="cam_01", left_wrist_conf=0.8, right_wrist_conf=0.8, yaw_type="frontal"):
    """
    Helper to generate a mock TrackedPerson.
    Keypoints: nose(0), l_shoulder(5), r_shoulder(6), l_hip(11), r_hip(12), l_wrist(9), r_wrist(10)
    MoveNet format: [y, x, conf] (normalized 0 to 1)
    """
    if yaw_type == "frontal":
        l_shoulder = [0.3, 0.4, 0.9]
        r_shoulder = [0.3, 0.6, 0.9]
        l_hip = [0.6, 0.4, 0.9]
        r_hip = [0.6, 0.6, 0.9]
    else:
        l_shoulder = [0.3, 0.49, 0.9]
        r_shoulder = [0.3, 0.51, 0.9]
        l_hip = [0.6, 0.49, 0.9]
        r_hip = [0.6, 0.51, 0.9]
        
    kps = np.array([
        [0.1, 0.5, 0.9],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        l_shoulder,
        r_shoulder,
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.5, 0.4, left_wrist_conf],
        [0.5, 0.6, right_wrist_conf],
        l_hip,
        r_hip,
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
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


def test_stable_id_proximity_and_grace_period():
    tracker = StableIDTracker(max_distance=100.0, grace_period=3)
    
    p1 = make_test_person(raw_person_id=0)
    persons = tracker.update([p1], frame_number=1)
    assert persons[0].stable_id == 0
    
    p2 = make_test_person(raw_person_id=0)
    p2.hip_centroid = (0.52, 0.61)
    persons = tracker.update([p2], frame_number=2)
    assert persons[0].stable_id == 0
    
    persons = tracker.update([], frame_number=3)
    assert len(persons) == 0
    
    p3 = make_test_person(raw_person_id=0)
    p3.hip_centroid = (0.53, 0.62)
    persons = tracker.update([p3], frame_number=4)
    assert persons[0].stable_id == 0
    
    tracker.update([], frame_number=5)
    tracker.update([], frame_number=6)
    tracker.update([], frame_number=7)
    tracker.update([], frame_number=8)
    
    p4 = make_test_person(raw_person_id=0)
    p4.hip_centroid = (0.53, 0.62)
    persons = tracker.update([p4], frame_number=9)
    assert persons[0].stable_id == 1


def test_stable_id_two_people_crossing():
    tracker = StableIDTracker(max_distance=50.0, grace_period=10)
    
    p1 = make_test_person(raw_person_id=0)
    p1.hip_centroid = (10.0, 10.0)
    p2 = make_test_person(raw_person_id=1)
    p2.hip_centroid = (100.0, 10.0)
    
    res = tracker.update([p1, p2], frame_number=1)
    assert res[0].stable_id == 0
    assert res[1].stable_id == 1
    
    p1_next = make_test_person(raw_person_id=0)
    p1_next.hip_centroid = (50.0, 10.0)
    p2_next = make_test_person(raw_person_id=1)
    p2_next.hip_centroid = (60.0, 10.0)
    
    res = tracker.update([p1_next, p2_next], frame_number=2)
    assert res[0].stable_id == 0
    assert res[1].stable_id == 1


def test_stable_id_mixed_normalized_and_pixel_centroids():
    tracker = StableIDTracker(max_distance=120.0, grace_period=10)

    existing = make_test_person(raw_person_id=0)
    existing.hip_centroid = (0.5, 0.6)
    tracker.update([existing], frame_number=1)

    incoming = make_test_person(raw_person_id=1)
    incoming.hip_centroid = (1000.0, 1200.0)

    matched = tracker.update([incoming], frame_number=2)

    assert matched[0].stable_id == 1


def mock_get_config(section, key, default=None):
    cfg = {
        "tracking": {"stable_id": {"max_distance": 120.0, "grace_frames": 30}},
    }
    return cfg.get(section, {}).get(key, default)


@patch("monitor_app.tracking.stable_id.get_config", side_effect=mock_get_config)
def test_behavior_engine_integration(mock_tracker_cfg):
    """BehaviorEngine assigns stable IDs and body metrics; concealment runs via fusion."""
    engine = BehaviorEngine()
    
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    p = make_test_person(stable_id=-1, raw_person_id=0, left_wrist_conf=0.8, right_wrist_conf=0.0)
    packet = EvidencePacket(
        camera_id="01",
        timestamp=1.0,
        frame=frame,
        tracked_persons=[p]
    )
    
    packet = engine.analyze_packet(packet, frame_index=1, sensitivity="medium")
    
    assert len(packet.tracked_persons) == 1
    person = packet.tracked_persons[0]
    assert person.stable_id == 0
    assert person.torso_height > 0.0
    assert person.shoulder_width > 0.0
    assert packet.behavior_evidence == []
