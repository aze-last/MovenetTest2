import time
import pytest
import numpy as np
from monitor_app.evidence import EvidencePacket
from monitor_app.decision import DecisionEngine, get_dismissal_registry
from monitor_app.fusion import get_camera_fusion

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

def test_contraband_dismissal_type_normalization():
    """Verify that track_id can be dismissed as a string or int and matches regardless of type."""
    reg = get_dismissal_registry()
    reg.clear_all()
    engine = DecisionEngine()
    
    cam_id = "1"
    # Dismiss as string '1001'
    reg.dismiss_track(cam_id, "1001")
    
    # Frame contains int 1001
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    packet = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame)
    packet.detections = {
        "contraband": [
            {"name": "cellphone", "confidence": 0.85, "track_id": 1001, "box": [100, 100, 150, 150]}
        ],
        "behavior": []
    }
    packet.alerts = ["CONTRABAND: cellphone (ID: 1001)"]
    packet.alert_triggered = True
    
    assert reg.is_track_dismissed(cam_id, 1001) is True
    assert reg.is_track_dismissed(cam_id, "1001") is True
    assert engine.evaluate_trigger(packet) is False
    assert packet.alert_triggered is False

def test_camera_fusion_clear_zone_events_on_dismissal():
    """Verify that clearing zone events on dismissal allows subsequent camera detections in the zone to trigger."""
    reg = get_dismissal_registry()
    reg.clear_all()
    fusion = get_camera_fusion()
    fusion.clear_zone_events()
    engine = DecisionEngine()
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    p1 = EvidencePacket(camera_id="1", timestamp=time.time(), frame=dummy_frame)
    p1.alerts = ["CONTRABAND: cellphone (ID: 1001)"]
    p1.alert_triggered = True
    p1.detections = {"contraband": [{"name": "cellphone", "confidence": 0.85, "track_id": 1001, "box": [10, 10, 50, 50]}]}
    
    # Cam 1 triggers
    res1 = fusion.process_decision_trigger(p1, engine)
    assert res1 is True
    
    # Cam 2 in same zone triggers within dedup window -> corroborated/suppressed
    # Configure camera zones so cam 1 and cam 2 are in the same zone
    fusion.camera_zones["1"] = "CellBlockA"
    fusion.camera_zones["2"] = "CellBlockA"
    
    # Trigger on Cam 1 with CellBlockA zone
    p1_zone = EvidencePacket(camera_id="1", timestamp=time.time(), frame=dummy_frame)
    p1_zone.alerts = ["CONTRABAND: cellphone (ID: 1001)"]
    p1_zone.alert_triggered = True
    p1_zone.detections = {"contraband": [{"name": "cellphone", "confidence": 0.85, "track_id": 1001, "box": [10, 10, 50, 50]}]}
    fusion.clear_zone_events()
    assert fusion.process_decision_trigger(p1_zone, engine) is True
    
    # Cam 2 now triggers in same zone within dedup window -> suppressed
    p2 = EvidencePacket(camera_id="2", timestamp=time.time(), frame=dummy_frame)
    p2.alerts = ["CONTRABAND: cellphone (ID: 1002)"]
    p2.alert_triggered = True
    p2.detections = {"contraband": [{"name": "cellphone", "confidence": 0.85, "track_id": 1002, "box": [10, 10, 50, 50]}]}
    assert fusion.process_decision_trigger(p2, engine) is False
    
    # Operator dismisses cam 1 alert -> zone events cleared
    fusion.clear_zone_events(camera_id="1")
    
    # Now cam 2 detection must trigger cleanly!
    res2 = fusion.process_decision_trigger(p2, engine)
    assert res2 is True
