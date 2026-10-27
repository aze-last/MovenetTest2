import time
import numpy as np
import pytest

from monitor_app.tracking.face_binder import OpportunisticFaceBinder


def test_face_binding_disabled_by_default(monkeypatch):
    """
    Test T1: When face_recognition.enabled is false (or not set),
    binder must not run face inference or bind profiles.
    """
    binder = OpportunisticFaceBinder()
    # Mock config returning enabled=False
    monkeypatch.setattr(binder, "is_enabled", lambda: False)
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    head_bbox = [100, 100, 200, 200]
    result = binder.probe_track(
        camera_id="cam_01",
        stable_id=1,
        frame=dummy_frame,
        head_bbox=head_bbox,
        current_time=time.time()
    )
    assert result is None
    assert binder.get_bound_identity(camera_id="cam_01", stable_id=1) is None


def test_face_binding_k_of_n_confirmation(monkeypatch):
    """
    Test T1: Face binding requires k=3 of N=5 consecutive matches above threshold (0.363)
    to confirm an identity.
    """
    binder = OpportunisticFaceBinder()
    monkeypatch.setattr(binder, "is_enabled", lambda: True)
    
    # Synthetic enrolled subject with normalized 128-d embedding
    feat_inmate1 = np.zeros((1, 128), dtype=np.float32)
    feat_inmate1[0, 0] = 1.0  # unit vector along dim 0
    binder.enroll_feature("INM-001", "John Doe", feat_inmate1)
    
    # Mock face extraction to return a feature with cosine similarity 0.85
    test_feat = np.zeros((1, 128), dtype=np.float32)
    test_feat[0, 0] = 0.85
    test_feat[0, 1] = np.sqrt(1.0 - 0.85**2)
    monkeypatch.setattr(binder, "_extract_face_feature", lambda frame, bbox: test_feat)

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    head_bbox = [100, 100, 200, 200]
    t0 = 1000.0

    # Probe 1: match 1/5 -> unconfirmed
    res1 = binder.probe_track("cam_01", 1, dummy_frame, head_bbox, t0)
    assert res1 is None
    assert binder.get_bound_identity("cam_01", 1) is None

    # Probe 2 (1.1s later): match 2/5 -> unconfirmed
    res2 = binder.probe_track("cam_01", 1, dummy_frame, head_bbox, t0 + 1.1)
    assert res2 is None
    assert binder.get_bound_identity("cam_01", 1) is None

    # Probe 3 (2.2s later): match 3/5 -> CONFIRMED!
    res3 = binder.probe_track("cam_01", 1, dummy_frame, head_bbox, t0 + 2.2)
    assert res3 == "INM-001"
    bound = binder.get_bound_identity("cam_01", 1)
    assert bound is not None
    assert bound["subject_id"] == "INM-001"
    assert bound["name"] == "John Doe"


def test_face_binding_anti_collision(monkeypatch):
    """
    Test T1: Anti-collision invariant.
    One inmate identity cannot be simultaneously bound to two different tracks in the same camera view.
    """
    binder = OpportunisticFaceBinder()
    monkeypatch.setattr(binder, "is_enabled", lambda: True)
    
    feat_inmate = np.zeros((1, 128), dtype=np.float32)
    feat_inmate[0, 0] = 1.0
    binder.enroll_feature("INM-001", "John Doe", feat_inmate)
    
    test_feat = feat_inmate.copy()
    monkeypatch.setattr(binder, "_extract_face_feature", lambda frame, bbox: test_feat)
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    head_bbox = [100, 100, 200, 200]
    t0 = 1000.0

    # Confirm Track 1 as INM-001
    for step in range(3):
        binder.probe_track("cam_01", stable_id=1, frame=dummy_frame, head_bbox=head_bbox, current_time=t0 + step * 1.1)
    
    assert binder.get_bound_identity("cam_01", stable_id=1)["subject_id"] == "INM-001"

    # Now Track 2 attempts to match INM-001 on the SAME camera
    for step in range(4):
        binder.probe_track("cam_01", stable_id=2, frame=dummy_frame, head_bbox=head_bbox, current_time=t0 + step * 1.1)
    
    # Track 2 must NOT collide/bind to INM-001
    assert binder.get_bound_identity("cam_01", stable_id=2) is None


def test_face_binding_cosine_threshold_rejection(monkeypatch):
    """
    Test T1: Cosine similarity below threshold (< 0.363) is rejected.
    """
    binder = OpportunisticFaceBinder(cosine_threshold=0.363)
    monkeypatch.setattr(binder, "is_enabled", lambda: True)
    
    feat_inmate = np.zeros((1, 128), dtype=np.float32)
    feat_inmate[0, 0] = 1.0
    binder.enroll_feature("INM-001", "John Doe", feat_inmate)
    
    # Low similarity: cosine = 0.20
    low_feat = np.zeros((1, 128), dtype=np.float32)
    low_feat[0, 0] = 0.20
    low_feat[0, 1] = np.sqrt(1.0 - 0.20**2)
    monkeypatch.setattr(binder, "_extract_face_feature", lambda frame, bbox: low_feat)

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    head_bbox = [100, 100, 200, 200]
    t0 = 1000.0

    for step in range(5):
        binder.probe_track("cam_01", stable_id=1, frame=dummy_frame, head_bbox=head_bbox, current_time=t0 + step * 1.1)
    
    assert binder.get_bound_identity("cam_01", stable_id=1) is None
