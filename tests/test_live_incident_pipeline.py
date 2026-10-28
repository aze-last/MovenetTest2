import os
import sqlite3
import time
import numpy as np
import pytest
from monitor_app.events import get_event_bus
from monitor_app.evidence import EvidencePacket
from monitor_app.incident_record import IncidentRecorder
from monitor_app.alert_manager import get_alert_manager, IncidentState, HysteresisState
from monitor_app.fusion import CameraFusion

def test_incident_recorder_handle_incident_start_with_severity(tmp_path):
    """Verify handle_incident_start accepts severity and **kwargs without TypeError."""
    db_file = str(tmp_path / "test_incidents.db")
    rec_dir = str(tmp_path / "recordings")
    recorder = IncidentRecorder(camera_id="1", recordings_dir=rec_dir, db_path=db_file)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # This call should succeed and not raise TypeError
    recorder.handle_incident_start(
        camera_id="1",
        incident_id="INC_TEST_001",
        event_type="Cellphone (50% >= 30%)",
        frame=dummy_frame,
        ai_results={},
        severity="HIGH",
        extra_param="future_compat"
    )

    assert recorder.state == recorder.RECORDING
    assert recorder.current_event_id == "INC_TEST_001"
    recorder.stop_recording()
    assert recorder.state == recorder.COOLDOWN
    recorder.close()

def test_camera_fusion_primary_camera_not_suppressed():
    """Verify primary camera ongoing frames are not suppressed by zone dedup."""
    fusion = CameraFusion()
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    class MockDecisionEngine:
        def evaluate_trigger(self, packet):
            return True
        def get_event_details(self, packet):
            return "Cellphone", [0.85]
        def get_severity(self, packet):
            return "MEDIUM"

    engine = MockDecisionEngine()
    pkt1 = EvidencePacket(camera_id="1", timestamp=time.time(), frame=dummy_frame)
    res1 = fusion.process_decision_trigger(pkt1, engine)
    assert res1 is True, "First detection in zone should trigger"

    # Frame 2 on same camera 0.1s later:
    pkt2 = EvidencePacket(camera_id="1", timestamp=time.time() + 0.1, frame=dummy_frame)
    res2 = fusion.process_decision_trigger(pkt2, engine)
    assert res2 is True, "Primary camera continuing detection must NOT be suppressed"

def test_end_to_end_decision_to_recording_and_db(tmp_path):
    """Verify end-to-end event chain from DECISION_TRIGGER -> AlertManager -> IncidentRecorder -> DB."""
    db_file = str(tmp_path / "incidents.db")
    rec_dir = str(tmp_path / "recordings")
    
    recorder = IncidentRecorder(camera_id="1", recordings_dir=rec_dir, db_path=db_file)
    alert_mgr = get_alert_manager()
    alert_mgr.camera_states["1"] = IncidentState("1")
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # 1. Fire DECISION_TRIGGER with HIGH severity (e.g. knife)
    get_event_bus().publish(
        "DECISION_TRIGGER",
        camera_id="1",
        event_type="Knife (80% >= 30%)",
        confidence_scores=[0.80],
        frame=dummy_frame,
        ai_results={},
        severity="HIGH"
    )
    
    # AlertManager should transition state to CONFIRMED and publish INCIDENT_START
    state = alert_mgr._get_state("1")
    assert state.state in (HysteresisState.CONFIRMED, HysteresisState.MAINTAINED)
    assert recorder.state == IncidentRecorder.RECORDING
    assert recorder.current_event_id.startswith("INC_")
    
    # 2. Stop incident and verify DB commit
    recorder.stop_recording()
    assert recorder.state == IncidentRecorder.COOLDOWN
    
    # 3. Verify SQLite record in DB
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("SELECT event_id, camera_id, escalation_level, operator_action_required FROM incidents")
    row = c.fetchone()
    conn.close()
    
    assert row is not None
    assert row[1] == "1"
    assert row[2] == "HIGH"
    assert row[3] == 1
    recorder.close()



def test_incident_recorder_close_finalizes_active_recording(tmp_path):
    """Verify that calling close() while recorder is actively RECORDING safely finalizes the video and commits the DB row."""
    db_file = str(tmp_path / "close_test.db")
    rec_dir = str(tmp_path / "recordings_close")
    recorder = IncidentRecorder(camera_id="1", recordings_dir=rec_dir, db_path=db_file)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    recorder.handle_incident_start(
        camera_id="1",
        incident_id="INC_CLOSE_TEST",
        event_type="Cellphone (45% >= 40%)",
        frame=dummy_frame,
        ai_results={},
        severity="MEDIUM"
    )
    assert recorder.state == recorder.RECORDING

    # Simulate user navigating away from Live Monitor: close() is called
    recorder.close()

    # DB record must exist despite early navigation away
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("SELECT event_id, camera_id, event_type, review_status FROM incidents WHERE event_id = 'INC_CLOSE_TEST'")
    row = c.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "INC_CLOSE_TEST"
    assert "Cellphone" in row[2]
    assert row[3] == "PENDING"


def test_contraband_medium_severity_confirms_immediately():
    """Verify MEDIUM severity events (cellphone detection) confirm immediately into CONFIRMED state."""
    state = IncidentState("2")
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    state.update("Cellphone (45% >= 40%)", [0.45], dummy_frame, {}, severity="MEDIUM")
    assert state.state in (HysteresisState.CONFIRMED, HysteresisState.MAINTAINED)
