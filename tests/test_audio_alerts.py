import time
from monitor_app.alert_manager import SoundAlertManager, get_sound_alert_manager, get_alert_manager
from monitor_app.decision import get_decision_engine
from monitor_app.evidence import EvidencePacket, BehaviorEvidence

def test_sound_alert_manager_rate_limiting():
    mgr = SoundAlertManager()
    mgr.enabled = True
    mgr.min_interval = 0.5
    
    # First play should succeed and update last_played_time
    t0 = time.time()
    mgr.play_alert("CRITICAL")
    assert mgr.last_played_time >= t0
    
    saved_time = mgr.last_played_time
    # Rapid second play should be throttled
    mgr.play_alert("CRITICAL")
    assert mgr.last_played_time == saved_time

def test_decision_engine_severity_calculation():
    engine = get_decision_engine()
    
    import numpy as np
    dummy_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    # 1. Contraband only -> MEDIUM
    pkt_medium = EvidencePacket(
        camera_id="0",
        timestamp=time.time(),
        frame=dummy_frame,
        detections={"contraband": [{"name": "cellphone", "confidence": 0.85}], "behavior": []}
    )
    assert engine.get_severity(pkt_medium) == "MEDIUM"
    
    # 2. Behavior only -> HIGH
    b_ev = BehaviorEvidence(
        behavior_type="aggression",
        confidence=190.0,
        stable_id=1,
        frame_number=1,
        timestamp=time.time(),
        sustained_frames=5
    )
    pkt_high = EvidencePacket(
        camera_id="0",
        timestamp=time.time(),
        frame=dummy_frame,
        behavior_evidence=[b_ev]
    )
    assert engine.get_severity(pkt_high) == "HIGH"

    
    # 3. Contraband + Behavior -> CRITICAL
    pkt_critical = EvidencePacket(
        camera_id="0",
        timestamp=time.time(),
        frame=dummy_frame,
        detections={"contraband": [{"name": "knife", "confidence": 0.90}], "behavior": []},
        behavior_evidence=[b_ev]
    )
    assert engine.get_severity(pkt_critical) == "CRITICAL"

