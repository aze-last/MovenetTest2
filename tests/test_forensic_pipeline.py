import pytest
from monitor_app.evidence import EvidencePacket, BehaviorEvidence, IncidentType, SnapshotResult
from monitor_app.decision import get_decision_engine
import numpy as np

def test_generate_incident_record_cellphone():
    engine = get_decision_engine()
    
    # Mock cellphone packet
    packet = EvidencePacket(
        camera_id="cam_1", 
        timestamp=100.5,
        frame=np.zeros((10,10,3), dtype=np.uint8)
    )
    packet.detections = {
        "behavior": [],
        "contraband": [{"name": "cellphone", "confidence": 0.85, "track_id": 42}]
    }
    
    incident = engine.generate_incident_record(packet, "TEST_SESSION", 15, "00:00:15")
    
    assert incident.incident_type == IncidentType.CELLPHONE
    assert incident.snapshot_required is True
    assert incident.subject_track_id == 42
    assert incident.raw_score == 0.85
    assert incident.normalized_score == 0.85
    assert incident.snapshot_result == SnapshotResult.PENDING
    assert incident.snapshot_filename == "TEST_SESSION_f15.jpg"

def test_generate_incident_record_aggression():
    engine = get_decision_engine()
    
    # Mock behavior packet
    b_evidence = BehaviorEvidence(
        behavior_type="Aggressive / Fighting",
        stable_id=19,
        confidence=153.36,
        frame_number=15,
        timestamp=100.5,
        sustained_frames=5
    )
    
    packet = EvidencePacket(
        camera_id="cam_1", 
        timestamp=100.5,
        frame=np.zeros((10,10,3), dtype=np.uint8),
        behavior_evidence=[b_evidence]
    )
    
    incident = engine.generate_incident_record(packet, "TEST_SESSION", 15, "00:00:15")
    
    assert incident.incident_type == IncidentType.AGGRESSION
    assert incident.snapshot_required is True
    assert incident.subject_track_id == 19
    assert incident.raw_score == 153.36
    # Normalized score should be capped at 1.0 based on logic 153.36/200.0 = 0.7668
    assert incident.normalized_score < 1.0 
    assert incident.snapshot_filename == "TEST_SESSION_f15.jpg"

def test_generate_incident_record_unknown():
    engine = get_decision_engine()
    
    packet = EvidencePacket(
        camera_id="cam_1", 
        timestamp=100.5,
        frame=np.zeros((10,10,3), dtype=np.uint8)
    )
    
    incident = engine.generate_incident_record(packet, "TEST_SESSION", 15, "00:00:15")
    
    assert incident.incident_type == IncidentType.UNKNOWN
    assert incident.snapshot_required is False
    assert incident.snapshot_filename == ""
