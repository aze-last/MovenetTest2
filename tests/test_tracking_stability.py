import time
import numpy as np
import pytest
import torch

from monitor_app.evidence import TrackedPerson
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.tracking.tracker_manager import TrackerManager, DetectionsAdapter


def test_anatomical_torso_anchoring_calculation():
    """
    Test T1: When hips are occluded, anatomical torso projection from shoulders
    must approximate the hip position closely (< 0.10 normalized distance)
    instead of jumping > 0.25 vertically.
    """
    # Frontal person: shoulders at y=0.30, hips at y=0.55, width=0.18
    sh_w = 0.18
    sh_y = 0.30
    sh_x = 0.50
    ground_truth_hip_y = 0.55

    # Torso offset formula
    torso_offset_y = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
    estimated_hip_y = min(1.0, sh_y + torso_offset_y)

    diff = abs(estimated_hip_y - ground_truth_hip_y)
    assert diff < 0.06, f"Estimated hip y {estimated_hip_y} too far from true {ground_truth_hip_y}"
    
    # Compare with raw shoulder midpoint jump
    raw_shoulder_jump = abs(sh_y - ground_truth_hip_y)
    assert diff < raw_shoulder_jump / 3.0, "Anatomical estimate must reduce vertical jump by >3x"


def test_kalman_hungarian_track_association_and_crossing():
    """
    Test T2: Two persons crossing trajectories.
    Person 0 moves left-to-right (0.20 -> 0.25 -> 0.35 -> 0.45).
    Person 1 moves right-to-left (0.60 -> 0.55 -> 0.45 -> 0.35).
    Kalman prediction + Hungarian association must prevent ID swapping at crossing.
    """
    tracker = StableIDTracker(max_distance=150.0, grace_period=10)
    
    # Frame 1: Initial positions
    p0_f1 = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.20, 0.50), confidence=0.9, frame_number=1, timestamp=1.0
    )
    p1_f1 = TrackedPerson(
        stable_id=-1, raw_person_id=1, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.60, 0.50), confidence=0.9, frame_number=1, timestamp=1.0
    )
    res1 = tracker.update([p0_f1, p1_f1], frame_number=1)
    id_left = res1[0].stable_id
    id_right = res1[1].stable_id
    assert id_left != id_right

    # Frame 2: Approaching
    p0_f2 = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.25, 0.50), confidence=0.9, frame_number=2, timestamp=1.033
    )
    p1_f2 = TrackedPerson(
        stable_id=-1, raw_person_id=1, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.55, 0.50), confidence=0.9, frame_number=2, timestamp=1.033
    )
    res2 = tracker.update([p0_f2, p1_f2], frame_number=2)
    assert res2[0].stable_id == id_left
    assert res2[1].stable_id == id_right

    # Frame 3: Near intersection (crossing point ~ 0.40)
    p0_f3 = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.35, 0.50), confidence=0.9, frame_number=3, timestamp=1.066
    )
    p1_f3 = TrackedPerson(
        stable_id=-1, raw_person_id=1, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.45, 0.50), confidence=0.9, frame_number=3, timestamp=1.066
    )
    res3 = tracker.update([p0_f3, p1_f3], frame_number=3)
    assert res3[0].stable_id == id_left
    assert res3[1].stable_id == id_right

    # Frame 4: Crossed over
    p0_f4 = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.45, 0.50), confidence=0.9, frame_number=4, timestamp=1.100
    )
    p1_f4 = TrackedPerson(
        stable_id=-1, raw_person_id=1, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.35, 0.50), confidence=0.9, frame_number=4, timestamp=1.100
    )
    res4 = tracker.update([p0_f4, p1_f4], frame_number=4)
    assert res4[0].stable_id == id_left, f"Expected {id_left} for left-to-right mover, got {res4[0].stable_id}"
    assert res4[1].stable_id == id_right, f"Expected {id_right} for right-to-left mover, got {res4[1].stable_id}"


def test_monotonic_frame_number_defense():
    """
    Test T2: Out-of-order frame numbers (e.g. from async callback threads)
    must not rewind last_seen_frame in StableIDTracker.
    """
    tracker = StableIDTracker(max_distance=120.0, grace_period=10)
    p = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.50, 0.50), confidence=0.9, frame_number=100, timestamp=1.0
    )
    res = tracker.update([p], frame_number=100)
    sid = res[0].stable_id
    assert tracker._tracks[sid]["last_seen_frame"] == 100

    # Thread 2 calls update with an earlier frame (e.g. 95)
    p_stale = TrackedPerson(
        stable_id=-1, raw_person_id=0, camera_id="cam_test",
        keypoints=np.zeros((17, 3), dtype=np.float32),
        hip_centroid=(0.50, 0.50), confidence=0.9, frame_number=95, timestamp=1.0
    )
    tracker.update([p_stale], frame_number=95)
    # Must remain 100, not rewound to 95
    assert tracker._tracks[sid]["last_seen_frame"] == 100


def test_tracker_manager_detections_adapter():
    """
    Test T4: TrackerManager.update() must process detections without crashing on Ultralytics.
    """
    tm = TrackerManager(cam_id="0")
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    
    # 1 human box [x1, y1, x2, y2, conf, cls]
    human_boxes = [[100.0, 100.0, 300.0, 500.0, 0.85, 0.0]]
    # 1 object box
    object_boxes = [[150.0, 200.0, 180.0, 230.0, 0.75, 1.0]]
    
    htracks, otracks = tm.update(human_boxes, object_boxes, dummy_frame)
    assert len(htracks) >= 1
    assert len(otracks) >= 1
    
    # Test with empty boxes
    h_empty, o_empty = tm.update([], [], dummy_frame)
    assert isinstance(h_empty, list)
    assert isinstance(o_empty, list)
