import os
import sqlite3
import numpy as np
import pytest
from monitor_app.incident_record import IncidentRecorder
from monitor_app.utils import normalize_cam_id

def test_incident_recorder_int_camera_id(tmp_path):
    db_file = str(tmp_path / "test_incidents.db")
    rec_dir = str(tmp_path / "recordings")
    
    # Initialize with integer camera_id (like from app_state.db)
    recorder = IncidentRecorder(camera_id=1, recordings_dir=rec_dir, db_path=db_file)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Trigger with string "1" (like from AlertManager / EventBus)
    recorder.handle_incident_start(
        camera_id="1",
        incident_id="INC_INT_TEST_001",
        event_type="Cellphone",
        frame=dummy_frame,
        ai_results={},
        severity="MEDIUM"
    )

    print("Recorder state after handle_incident_start:", recorder.state)
    print("Recorder event ID:", recorder.current_event_id)
    assert recorder.state == recorder.RECORDING
    assert recorder.current_event_id == "INC_INT_TEST_001"

    recorder.stop_recording()
    assert recorder.state == recorder.COOLDOWN

    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("SELECT event_id, camera_id, event_type FROM incidents WHERE event_id = 'INC_INT_TEST_001'")
    row = c.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "INC_INT_TEST_001"
    print("Incident properly saved in DB:", row)

if __name__ == "__main__":
    import tempfile
    import pathlib
    td = tempfile.mkdtemp()
    test_incident_recorder_int_camera_id(pathlib.Path(td))

