import time
import pytest
import numpy as np
from monitor_app.evidence import EvidencePacket
from monitor_app.decision import DecisionEngine, get_dismissal_registry

def test_contraband_dismissal_registry_lifecycle():
    """Verify dismiss_track, is_track_dismissed, touch_track, and stale pruning."""
    reg = get_dismissal_registry()
    reg.clear_all()
    
    cam_id = "1"
    track_id_1 = 101
    track_id_2 = 102
    
    assert not reg.is_track_dismissed(cam_id, track_id_1)
    
    # Dismiss track 101
    reg.dismiss_track(cam_id, track_id_1)
    assert reg.is_track_dismissed(cam_id, track_id_1)
    assert not reg.is_track_dismissed(cam_id, track_id_2)
    assert not reg.is_track_dismissed("2", track_id_1)  # Different camera
    
    # Sustained detection: touching track keeps it active
    reg.touch_track(cam_id, track_id_1)
    assert reg.is_track_dismissed(cam_id, track_id_1)
    
    # Pruning with tiny TTL
    reg.prune_stale(ttl=0.01)
    time.sleep(0.02)
    reg.prune_stale(ttl=0.01)
    assert not reg.is_track_dismissed(cam_id, track_id_1)

def test_decision_engine_suppresses_dismissed_contraband():
    """Verify that when a light source / cellphone is dismissed by ID, it does not re-trigger alerts."""
    reg = get_dismissal_registry()
    reg.clear_all()
    engine = DecisionEngine()
    
    cam_id = "1"
    stationary_glare_track_id = 999
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    packet1 = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame)
    packet1.detections = {
        "contraband": [
            {"name": "cellphone", "confidence": 0.85, "track_id": stationary_glare_track_id, "box": [100, 100, 150, 150]}
        ],
        "behavior": []
    }
    packet1.alerts = ["CONTRABAND: cellphone (ID: 999)"]
    packet1.alert_triggered = True
    
    # Initial sighting should trigger
    assert engine.evaluate_trigger(packet1) is True
    
    # Operator clicks Dismiss on ID 999
    reg.dismiss_track(cam_id, stationary_glare_track_id)
    assert reg.is_track_dismissed(cam_id, stationary_glare_track_id)
    
    # Next frame arrives with the exact same stationary glare / light emitter (ID 999)
    packet2 = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame)
    packet2.detections = {
        "contraband": [
            {"name": "cellphone", "confidence": 0.87, "track_id": stationary_glare_track_id, "box": [100, 100, 150, 150]}
        ],
        "behavior": []
    }
    packet2.alerts = ["CONTRABAND: cellphone (ID: 999)"]
    packet2.alert_triggered = True
    
    # Must be suppressed!
    assert engine.evaluate_trigger(packet2) is False
    assert packet2.detections["contraband"][0].get("dismissed") is True
    assert len(packet2.alerts) == 0

def test_decision_engine_triggers_on_new_contraband_id():
    """Verify that a brand new contraband ID still triggers even while another ID is dismissed."""
    reg = get_dismissal_registry()
    reg.clear_all()
    engine = DecisionEngine()
    
    cam_id = "1"
    dismissed_id = 999
    new_inmate_phone_id = 1001
    
    reg.dismiss_track(cam_id, dismissed_id)
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    packet = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame)
    packet.detections = {
        "contraband": [
            {"name": "cellphone", "confidence": 0.85, "track_id": dismissed_id, "box": [100, 100, 150, 150]},
            {"name": "cellphone", "confidence": 0.90, "track_id": new_inmate_phone_id, "box": [300, 300, 350, 350]}
        ],
        "behavior": []
    }
    packet.alerts = [
        "CONTRABAND: cellphone (ID: 999)",
        "CONTRABAND: cellphone (ID: 1001)"
    ]
    packet.alert_triggered = True
    
    # Must trigger because 1001 is a new un-dismissed contraband item!
    assert engine.evaluate_trigger(packet) is True
    # Alert list should retain the new phone alert and remove the dismissed one
    assert any("1001" in a for a in packet.alerts)
    assert not any("999" in a for a in packet.alerts)

