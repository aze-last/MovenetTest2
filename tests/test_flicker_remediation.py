"""
Regression tests for the bounding-box flicker remediation (implementation_plan.md).

Covers the two independent render paths separately, matching the investigation:
  - Phase B (YOLO contraband boxes): per-camera ByteTrack isolation (B1), stable untracked
    cache key (B2), and config-driven tracker YAML generation (B3).
  - Phase C (MoveNet person boxes): render-side detection hysteresis / box coasting (C1) and
    alert-colour latching (C3).

These exercise the pure logic pieces without loading YOLO/ONNX models or the GPU.
"""
import numpy as np
import pytest
import yaml

from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.central_inference import CentralInferenceManager
from monitor_app.evidence import EvidencePacket, TrackedPerson, BehaviorEvidence


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _bare_engine():
    """A MotionOptimizedEngine instance WITHOUT running __init__ (no model loading)."""
    eng = object.__new__(MotionOptimizedEngine)
    eng.yolo_per_cam = {}
    eng.active_model_path = "C:/fake/best.engine"
    eng.yolo_custom = object()  # sentinel for the shared model
    eng._tracker_yaml_path = None
    return eng


def _person(stable_id=0, raw_id=0, camera_id="0"):
    """A frontal person whose shoulders+hips are confident enough to yield a bbox."""
    kps = np.zeros((17, 3), dtype=float)
    kps[0] = [0.1, 0.5, 0.9]    # nose
    kps[5] = [0.3, 0.4, 0.9]    # l_shoulder
    kps[6] = [0.3, 0.6, 0.9]    # r_shoulder
    kps[11] = [0.6, 0.4, 0.9]   # l_hip
    kps[12] = [0.6, 0.6, 0.9]   # r_hip
    return TrackedPerson(
        stable_id=stable_id, raw_person_id=raw_id, camera_id=camera_id,
        keypoints=kps, hip_centroid=(0.5, 0.6), confidence=0.85,
    )


def _packet(persons, camera_id="0", behavior_evidence=None, behavior_dets=None):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    pkt = EvidencePacket(camera_id=camera_id, timestamp=1.0, frame=frame,
                         tracked_persons=list(persons))
    pkt.behavior_evidence = list(behavior_evidence or [])
    pkt.detections = {"behavior": list(behavior_dets or []), "contraband": []}
    return pkt


class _StubEngine:
    """Stands in for MotionOptimizedEngine in the render path (no draw_skeleton)."""
    pass


# --------------------------------------------------------------------------------------
# Phase B1 — per-camera ByteTrack isolation
# --------------------------------------------------------------------------------------
def test_per_camera_yolo_isolation_distinct_instances(monkeypatch):
    created = []

    class FakeYOLO:
        def __init__(self, path):
            created.append(path)

    monkeypatch.setattr("monitor_app.ai_engine.YOLO", FakeYOLO)
    monkeypatch.setattr("monitor_app.ai_engine.get_config",
                        lambda s, k=None, d=None: "per_camera" if k == "tracker_isolation" else d)

    eng = _bare_engine()
    m0 = eng._get_yolo_for_camera("0")
    m1 = eng._get_yolo_for_camera("1")
    m0_again = eng._get_yolo_for_camera("0")

    # Two cameras -> two isolated tracker instances; same camera -> cached instance reused.
    assert m0 is not m1
    assert m0 is m0_again
    assert len(created) == 2


def test_shared_isolation_returns_single_model(monkeypatch):
    monkeypatch.setattr("monitor_app.ai_engine.get_config",
                        lambda s, k=None, d=None: "shared" if k == "tracker_isolation" else d)
    eng = _bare_engine()
    m0 = eng._get_yolo_for_camera("0")
    m1 = eng._get_yolo_for_camera("1")
    # Legacy behaviour: all cameras share the one loaded model.
    assert m0 is m1 is eng.yolo_custom
    assert eng.yolo_per_cam == {}


# --------------------------------------------------------------------------------------
# Phase B2 — stable untracked cache key (spatial bucketing defeats jitter)
# --------------------------------------------------------------------------------------
def test_untracked_cache_key_stable_under_jitter():
    # Small per-frame jitter within the same grid cell -> identical key.
    k1 = MotionOptimizedEngine._untracked_cache_key(0, 100, 100, 150, 200, grid_px=96)
    k2 = MotionOptimizedEngine._untracked_cache_key(0, 104, 97, 153, 203, grid_px=96)
    assert k1 == k2


def test_untracked_cache_key_separates_distant_objects():
    k1 = MotionOptimizedEngine._untracked_cache_key(0, 100, 100, 150, 200, grid_px=96)
    k_far = MotionOptimizedEngine._untracked_cache_key(0, 500, 100, 550, 200, grid_px=96)
    k_cls = MotionOptimizedEngine._untracked_cache_key(1, 100, 100, 150, 200, grid_px=96)
    assert k1 != k_far          # different location -> different key
    assert k1 != k_cls          # different class -> different key


# --------------------------------------------------------------------------------------
# Phase B3 — tracker YAML generated from config (previously-inert track_thresh now applied)
# --------------------------------------------------------------------------------------
def test_tracker_yaml_generated_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "monitor_app.ai_engine.get_config",
        lambda s, k=None, d=None: {
            "track_high_thresh": 0.2, "track_low_thresh": 0.1, "new_track_thresh": 0.25,
            "track_buffer": 30, "match_thresh": 0.8, "fuse_score": True,
        } if k == "tracker" else d,
    )
    # Redirect the generated YAML into the module dir's models/ — write is allowed there,
    # but assert on the parsed content rather than the location.
    eng = _bare_engine()
    path = eng._get_tracker_yaml()
    with open(path) as f:
        doc = yaml.safe_load(f)
    assert doc["tracker_type"] == "bytetrack"
    assert doc["track_high_thresh"] == 0.2   # the formerly-dead TRACKER_CFG value, now live
    assert doc["track_buffer"] == 30
    # cached on second call
    assert eng._get_tracker_yaml() is path


# --------------------------------------------------------------------------------------
# Ghost-filter relaxation — a single shoulder dip must NOT collapse the detection
# --------------------------------------------------------------------------------------
def test_ghost_filter_accepts_mixed_torso_pair():
    # One shoulder + one hip visible (torso_count=2) — previously REJECTED (no complete pair),
    # now accepted at the default ghost_min_torso_keypoints=2. This is the core flicker fix.
    assert MotionOptimizedEngine._passes_ghost_filter(
        n_valid=6, torso_count=2, ghost_min_kp=5, ghost_min_torso=2) is True


def test_ghost_filter_still_rejects_single_anchor_and_sparse():
    # Only one torso anchor -> still rejected (ghost protection retained).
    assert MotionOptimizedEngine._passes_ghost_filter(
        n_valid=6, torso_count=1, ghost_min_kp=5, ghost_min_torso=2) is False
    # Too few total keypoints -> rejected regardless of torso.
    assert MotionOptimizedEngine._passes_ghost_filter(
        n_valid=4, torso_count=4, ghost_min_kp=5, ghost_min_torso=2) is False


def test_ghost_filter_backcompat_full_pair_still_passes():
    # Both shoulders (torso_count>=2) — accepted, same as before.
    assert MotionOptimizedEngine._passes_ghost_filter(
        n_valid=5, torso_count=2, ghost_min_kp=5, ghost_min_torso=2) is True


# --------------------------------------------------------------------------------------
# Phase C1 — box coasting: a person's box persists across a brief detection dropout
# --------------------------------------------------------------------------------------
def test_box_coasts_then_evicts(monkeypatch):
    monkeypatch.setattr("monitor_app.central_inference.get_config",
                        lambda s, k=None, d=None: 8 if k == "detection_hysteresis_frames" else d)
    mgr = CentralInferenceManager()
    mgr.engine = _StubEngine()

    # Frame 1: person present -> cached, misses reset.
    mgr._render_person_boxes(_packet([_person(stable_id=0)]))
    assert 0 in mgr.box_hysteresis["0"]
    assert mgr.box_hysteresis["0"][0]["misses"] == 0

    # Person drops out. Box should coast for exactly hyst_frames (8) frames...
    for expected_miss in range(1, 9):
        mgr._render_person_boxes(_packet([], camera_id="0"))
        assert 0 in mgr.box_hysteresis["0"], f"box evicted too early at miss {expected_miss}"
        assert mgr.box_hysteresis["0"][0]["misses"] == expected_miss

    # ...then evict on the 9th consecutive miss.
    mgr._render_person_boxes(_packet([], camera_id="0"))
    assert 0 not in mgr.box_hysteresis["0"]


# --------------------------------------------------------------------------------------
# Phase C3 — alert colour latch: single-frame evidence gap does not strobe red<->green
# --------------------------------------------------------------------------------------
def test_alert_colour_latches_across_gap(monkeypatch):
    monkeypatch.setattr("monitor_app.central_inference.get_config",
                        lambda s, k=None, d=None: 8 if k == "detection_hysteresis_frames" else d)
    mgr = CentralInferenceManager()
    mgr.engine = _StubEngine()

    ev = BehaviorEvidence(behavior_type="aggression", stable_id=0, confidence=0.9,
                          frame_number=1, timestamp=1.0, sustained_frames=3)

    # Frame with alert evidence -> latched alert.
    mgr._render_person_boxes(_packet([_person(stable_id=0)], behavior_evidence=[ev]))
    assert mgr.box_hysteresis["0"][0]["is_alert"] is True
    assert mgr.box_hysteresis["0"][0]["alert_hold"] == 8

    # Next frame: same person present but NO evidence -> colour must stay alert (latched),
    # not immediately flip back to green.
    mgr._render_person_boxes(_packet([_person(stable_id=0)]))
    assert mgr.box_hysteresis["0"][0]["is_alert"] is True
    assert mgr.box_hysteresis["0"][0]["alert_hold"] == 7
