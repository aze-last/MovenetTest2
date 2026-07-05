import os
import time
import json
import shutil
import pytest
from monitor_app.benchmark.session_manager import BenchmarkSession, BenchmarkSessionManager

def test_async_session_logger():
    # Setup temp runs directory for test
    test_base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_runs")
    os.makedirs(test_base_dir, exist_ok=True)
    
    try:
        session = BenchmarkSession(run_id="test_run_123", base_dir=test_base_dir)
        
        # Log multiple events quickly to test thread queueing
        session.log_benchmark("INFO", "TEST", "test_module", "Message 1")
        session.log_telemetry(time.time(), {"cpu": 45.2, "ram": 8.1})
        
        payload = {
            "yolo_boxes": [{"stable_id": 1, "bbox": [10, 20, 100, 200], "confidence": 0.85}],
            "movenet_keypoints": [[[10, 20, 0.9], [15, 25, 0.8]]]
        }
        session.log_event(
            timestamp=time.time(),
            event_type="FRAME_AI_VAL",
            camera_id="cam_0",
            confidence=0.85,
            latency_ms=22.5,
            message="Frame 1 processed",
            payload=payload
        )
        
        session.log_error(time.time(), "test_module", "Some error occurred", "Traceback here...")
        
        # Stop session logger and wait for queue flush
        session.stop_writer()
        
        # Verify files were created
        assert os.path.exists(session.benchmark_log_path)
        assert os.path.exists(session.telemetry_log_path)
        assert os.path.exists(session.events_log_path)
        assert os.path.exists(session.errors_log_path)
        
        # Verify content
        with open(session.benchmark_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            assert "INFO" in lines[0]
            assert "Message 1" in lines[0]
            
        with open(session.events_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["event_type"] == "FRAME_AI_VAL"
            assert entry["camera_id"] == "cam_0"
            assert entry["payload"]["yolo_boxes"][0]["stable_id"] == 1
            assert entry["payload"]["movenet_keypoints"][0][0][2] == 0.9

    finally:
        # Cleanup temp directory
        if os.path.exists(test_base_dir):
            shutil.rmtree(test_base_dir)

def test_event_bus_unsubscribe():
    from monitor_app.events import get_event_bus
    bus = get_event_bus()
    
    events_received = []
    cb = lambda payload: events_received.append(payload)
    
    bus.subscribe("TEST_UNSUB_EVENT", cb)
    bus.publish("TEST_UNSUB_EVENT", "Hello")
    assert len(events_received) == 1
    assert events_received[0] == "Hello"
    
    bus.unsubscribe("TEST_UNSUB_EVENT", cb)
    bus.publish("TEST_UNSUB_EVENT", "World")
    # Should not have received "World"
    assert len(events_received) == 1
