import time
import numpy as np
import pytest
from unittest.mock import patch

from monitor_app.evidence import (
    FusedConcealmentObservation,
    HandObservation,
    HandObservationState,
    HandSide,
)
from monitor_app.hand_observation import HandObservationClassifier
from monitor_app.concealment_fusion import ConcealmentFusionEngine
from monitor_app.behaviors.concealment_detector import ConcealmentDetector
from tests.test_concealment_tracking import make_test_person


MOCK_CONCEALMENT_CONFIG = {
    "enabled": True,
    "per_camera": {
        "wrist_visible_threshold": 0.35,
        "wrist_missing_threshold": 0.20,
        "yaw_gate_threshold": 30.0,
        "min_pose_confidence": 0.25,
    },
    "fusion": {
        "single_camera_insufficient": True,
        "side_view_never_confirms": True,
        "min_supporting_cameras": 2,
        "min_frontal_quality": 0.60,
        "min_fused_confidence": 0.75,
        "veto_visible_threshold": 0.70,
        "unknown_is_neutral": True,
        "association_max_hip_distance_norm": 0.15,
        "fusion_stale_ms": 5000,
    },
    "behavior": {
        "duration_frames": 3,
        "cooldown_frames": 5,
        "decay_frames": 1,
    },
    "zones": {
        "default": {
            "cameras": ["cam_a", "cam_b", "cam_c"],
            "max_occupancy_for_auto_merge": 2,
        }
    },
}


def mock_get_concealment_config(key=None, default=None):
    if key is None:
        return MOCK_CONCEALMENT_CONFIG
    return MOCK_CONCEALMENT_CONFIG.get(key, default)


def _make_obs(
    camera_id,
    stable_id,
    hand,
    state,
    confidence=0.8,
    view_quality=0.9,
    hip=(0.5, 0.6),
):
    return HandObservation(
        camera_id=camera_id,
        stable_id=stable_id,
        hand=hand,
        state=state,
        confidence=confidence,
        timestamp=time.time(),
        frame_index=1,
        view_quality=view_quality,
        hip_centroid=hip,
    )


@patch("monitor_app.hand_observation.get_concealment_config", side_effect=mock_get_concealment_config)
def test_hand_observation_frontal_one_wrist_missing(mock_cfg):
    classifier = HandObservationClassifier()
    person = make_test_person(
        stable_id=0,
        camera_id="cam_a",
        left_wrist_conf=0.8,
        right_wrist_conf=0.0,
        yaw_type="frontal",
    )
    person.torso_height = 100.0
    person.shoulder_width = 90.0

    observations = classifier.classify_person(person, 1)
    by_hand = {obs.hand: obs.state for obs in observations}
    assert by_hand[HandSide.LEFT] == HandObservationState.VISIBLE
    assert by_hand[HandSide.RIGHT] == HandObservationState.CONCEALED


@patch("monitor_app.hand_observation.get_concealment_config", side_effect=mock_get_concealment_config)
def test_hand_observation_side_profile_is_unknown(mock_cfg):
    classifier = HandObservationClassifier()
    person = make_test_person(
        stable_id=0,
        camera_id="cam_a",
        left_wrist_conf=0.8,
        right_wrist_conf=0.0,
        yaw_type="side",
    )
    person.torso_height = 100.0
    person.shoulder_width = 10.0

    observations = classifier.classify_person(person, 1)
    assert all(obs.state == HandObservationState.UNKNOWN for obs in observations)


@patch("monitor_app.concealment_fusion.get_concealment_config", side_effect=mock_get_concealment_config)
def test_fusion_visible_veto(mock_cfg):
    engine = ConcealmentFusionEngine()
    now = time.time()
    camera_obs = {
        "cam_a": (
            now,
            [
                _make_obs("cam_a", 0, HandSide.RIGHT, HandObservationState.CONCEALED),
            ],
        ),
        "cam_b": (
            now,
            [
                _make_obs("cam_b", 0, HandSide.RIGHT, HandObservationState.VISIBLE, confidence=0.9),
            ],
        ),
    }
    fused = engine.fuse_zone("default", camera_obs, ["cam_a", "cam_b"])
    right = next(f for f in fused if f.hand == HandSide.RIGHT)
    assert right.fused_state == HandObservationState.VISIBLE
    assert "cam_b" in right.vetoing_cameras


@patch("monitor_app.concealment_fusion.get_concealment_config", side_effect=mock_get_concealment_config)
def test_fusion_single_camera_insufficient(mock_cfg):
    engine = ConcealmentFusionEngine()
    now = time.time()
    camera_obs = {
        "cam_a": (
            now,
            [
                _make_obs("cam_a", 0, HandSide.RIGHT, HandObservationState.CONCEALED),
            ],
        ),
    }
    fused = engine.fuse_zone("default", camera_obs, ["cam_a", "cam_b"])
    right = next(f for f in fused if f.hand == HandSide.RIGHT)
    assert right.fused_state == HandObservationState.UNKNOWN


@patch("monitor_app.concealment_fusion.get_concealment_config", side_effect=mock_get_concealment_config)
def test_fusion_two_cameras_confirm(mock_cfg):
    engine = ConcealmentFusionEngine()
    now = time.time()
    camera_obs = {
        "cam_a": (
            now,
            [
                _make_obs("cam_a", 0, HandSide.RIGHT, HandObservationState.CONCEALED, confidence=0.85),
            ],
        ),
        "cam_b": (
            now,
            [
                _make_obs("cam_b", 0, HandSide.RIGHT, HandObservationState.CONCEALED, confidence=0.85),
            ],
        ),
    }
    fused = engine.fuse_zone("default", camera_obs, ["cam_a", "cam_b"])
    right = next(f for f in fused if f.hand == HandSide.RIGHT)
    assert right.fused_state == HandObservationState.CONCEALED
    assert len(right.supporting_cameras) >= 2


@patch("monitor_app.behaviors.concealment_detector.get_concealment_config", side_effect=mock_get_concealment_config)
def test_fused_concealment_sustain_and_cooldown(mock_cfg):
    detector = ConcealmentDetector()
    fused = FusedConcealmentObservation(
        zone_id="default",
        subject_slot=0,
        hand=HandSide.RIGHT,
        fused_state=HandObservationState.CONCEALED,
        fused_confidence=0.85,
        supporting_cameras=["cam_a", "cam_b"],
        camera_stable_ids={"cam_a": 0, "cam_b": 0},
    )

    assert detector.process_fused([fused], 1, "medium", "cam_a", 1.0) == []
    assert detector.process_fused([fused], 2, "medium", "cam_a", 2.0) == []
    evidence = detector.process_fused([fused], 3, "medium", "cam_a", 3.0)
    assert len(evidence) == 1
    assert evidence[0].metadata["fusion_confirmed"] is True

    assert detector.process_fused([fused], 4, "medium", "cam_a", 4.0) == []
    evidence = detector.process_fused([fused], 8, "medium", "cam_a", 8.0)
    assert len(evidence) == 0 or detector.states[("default", 0)]["occlusion_counter"] == 1
