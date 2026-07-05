import sys
import os
import time
import pytest
from typing import Dict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_app.telemetry.context import TelemetryContext
from monitor_app.telemetry.collectors.camera import CameraCollector
from monitor_app.telemetry.collectors.ai import AICollector
from monitor_app.telemetry.engine import TelemetryEngine

def test_telemetry_context():
    ctx = TelemetryContext(camera_id="cam_test", sequence_num=101)
    assert ctx.camera_id == "cam_test"
    assert "cam_test_frame_101_" in ctx.frame_uuid
    assert "camera_read_start" in ctx.timestamps
    
    time.sleep(0.01)
    ctx.mark("camera_read_end")
    latency = ctx.get_duration("camera_read_start", "camera_read_end")
    assert latency > 0.0
    
    d = ctx.to_dict()
    assert d["frame_uuid"] == ctx.frame_uuid
    assert d["sequence_num"] == 101

def test_camera_collector():
    collector = CameraCollector()
    
    # Simulate frame reads
    now = time.time()
    collector.on_event("TELEM_FRAME_READ", {
        "camera_id": "0",
        "timestamps": {"camera_read_end": now}
    })
    collector.on_event("TELEM_FRAME_READ", {
        "camera_id": "0",
        "timestamps": {"camera_read_end": now + 0.033}
    })
    
    # Simulate failures
    collector.on_event("TELEM_FRAME_DROPPED", {"camera_id": "0", "reason": "queue_full"})
    collector.on_event("TELEM_HEALTH_ALERT", {"camera_id": "0", "alert_type": "CAMERA_RECONNECT"})
    
    # Simulate queue complete with wait time
    collector.on_event("TELEM_PIPELINE_COMPLETE", {
        "camera_id": "0",
        "timestamps": {
            "queue_enter": 100.0,
            "queue_exit": 100.025  # 25 ms delay
        }
    })

    stats = collector.get_stats()
    cam_stats = stats.get("0")
    assert cam_stats is not None
    assert cam_stats["dropped_frames"] == 1
    assert cam_stats["reconnects"] == 1
    assert cam_stats["avg_queue_delay_ms"] == 25.0

def test_ai_collector():
    collector = AICollector()
    
    # Feed 10 samples of varying YOLO latencies
    # Timings: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100] ms
    for i in range(1, 11):
        collector.on_event("TELEM_PIPELINE_COMPLETE", {
            "timestamps": {
                "yolo_start": 0.0,
                "yolo_end": i * 0.010
            }
        })
        
    stats = collector.get_stats()
    yolo_stats = stats.get("yolo")
    assert yolo_stats is not None
    assert yolo_stats["min"] == 10.0
    assert yolo_stats["max"] == 100.0
    assert yolo_stats["avg"] == 55.0
    assert yolo_stats["p95"] == 100.0  # ceil(0.95 * 10) = 10th index = 100ms

class MockCollector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
    def on_event(self, event, payload):
        with self.lock:
            self.events.append((event, payload))

import threading
def test_telemetry_engine():
    engine = TelemetryEngine(max_queue_size=10)
    mock = MockCollector()
    engine.register_collector(mock)
    
    engine.start()
    
    # Publish events to EventBus
    from monitor_app.events import get_event_bus
    bus = get_event_bus()
    bus.publish("TELEM_SYSTEM_TICK", "TELEM_SYSTEM_TICK", {"test": "val"})
    
    # Wait for worker thread to process
    time.sleep(0.5)
    
    engine.stop()
    
    assert len(mock.events) >= 1
    assert mock.events[0][0] == "TELEM_SYSTEM_TICK"
    assert mock.events[0][1]["test"] == "val"
