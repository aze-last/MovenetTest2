import pytest
import time
from monitor_app.evidence import EvidencePacket
from monitor_app.decision import get_dismissal_registry, DecisionEngine


def test_dynamic_contraband_tracker_allocates_new_id_on_new_object():
    """
    Verify that when an object leaves the field of view and another object appears
    in the same general region, the tracker assigns a NEW unique track ID
    instead of statically reusing the dismissed ID.
    """
    from monitor_app.ai_engine import DynamicContrabandTracker

    tracker = DynamicContrabandTracker(iou_thresh=0.3, max_lost_frames=5)
    cam_id = "1"

    # Frame 1: Vape presented at [100, 100, 200, 200]
    boxes_f1 = [[100, 100, 200, 200]]
    scores_f1 = [0.85]
    classes_f1 = [1] # cellphone/vape
    tracks_f1 = tracker.update(cam_id, boxes_f1, scores_f1, classes_f1)
    
    assert len(tracks_f1) == 1
    vape_id = tracks_f1[0]["track_id"]
    assert vape_id is not None
    assert vape_id > 0

    # Frame 2: Vape sustained in same spot
    boxes_f2 = [[102, 101, 201, 199]]
    tracks_f2 = tracker.update(cam_id, boxes_f2, scores_f1, classes_f1)
    assert len(tracks_f2) == 1
    assert tracks_f2[0]["track_id"] == vape_id, "Sustained object should keep its track ID"

    # Operator dismisses the vape
    reg = get_dismissal_registry()
    reg.clear_all()
    reg.dismiss_track(cam_id, vape_id)
    assert reg.is_track_dismissed(cam_id, vape_id) is True

    # Frames 3-10: Vape removed (no detections for > max_lost_frames)
    for _ in range(7):
        tracker.update(cam_id, [], [], [])

    # Frame 11: User now presents their PHONE in the same general region [105, 105, 205, 205]
    boxes_f11 = [[105, 105, 205, 205]]
    tracks_f11 = tracker.update(cam_id, boxes_f11, scores_f1, classes_f1)
    assert len(tracks_f11) == 1
    phone_id = tracks_f11[0]["track_id"]

    # Invariant: phone MUST get a distinct, new track ID so it is NOT dismissed!
    assert phone_id != vape_id, f"New object must get a new ID, got {phone_id} == {vape_id}"
    assert reg.is_track_dismissed(cam_id, phone_id) is False, "New object ID must NOT be dismissed"


def test_dismissal_differentiation_with_decision_engine():
    """
    Verify DecisionEngine suppresses the dismissed vape ID but triggers for the new phone ID.
    """
    engine = DecisionEngine()
    reg = get_dismissal_registry()
    reg.clear_all()
    cam_id = "1"

    import numpy as np
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # 1. Vape packet with ID 1001
    vape_packet = EvidencePacket(
        camera_id=cam_id,
        timestamp=time.time(),
        frame=dummy_frame,
        detections={"contraband": [{"name": "cellphone", "confidence": 0.88, "box": [100, 100, 200, 200], "track_id": 1001}]},
        alerts=["CONTRABAND: cellphone (ID: 1001)"],
        alert_triggered=True
    )
    assert engine.evaluate_trigger(vape_packet) is True

    # Operator dismisses vape ID 1001
    reg.dismiss_track(cam_id, 1001)

    # Re-evaluate same vape ID 1001 -> suppressed!
    vape_packet_2 = EvidencePacket(
        camera_id=cam_id,
        timestamp=time.time(),
        frame=dummy_frame,
        detections={"contraband": [{"name": "cellphone", "confidence": 0.88, "box": [100, 100, 200, 200], "track_id": 1001}]},
        alerts=["CONTRABAND: cellphone (ID: 1001)"],
        alert_triggered=True
    )
    assert engine.evaluate_trigger(vape_packet_2) is False

    # 2. Phone packet arrives with brand new ID 1002 -> MUST trigger!
    phone_packet = EvidencePacket(
        camera_id=cam_id,
        timestamp=time.time(),
        frame=dummy_frame,
        detections={"contraband": [{"name": "cellphone", "confidence": 0.92, "box": [100, 100, 200, 200], "track_id": 1002}]},
        alerts=["CONTRABAND: cellphone (ID: 1002)"],
        alert_triggered=True
    )
    assert engine.evaluate_trigger(phone_packet) is True
    assert "CONTRABAND: cellphone (ID: 1002)" in phone_packet.alerts


def test_central_inference_in_flight_pacing():
    """
    Verify CentralInferenceManager tracks per-camera in-flight tasks
    to prevent queue overflow backpressure storms.
    """
    from monitor_app.central_inference import CentralInferenceManager

    manager = CentralInferenceManager()
    cam_id = "2"

    assert manager.has_in_flight_task(cam_id) is False

    manager.mark_task_in_flight(cam_id)
    assert manager.has_in_flight_task(cam_id) is True
    assert manager.has_in_flight_task("3") is False, "Other cameras should not be marked in-flight"

    manager.clear_task_in_flight(cam_id)
    assert manager.has_in_flight_task(cam_id) is False
