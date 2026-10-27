import time
import numpy as np
import pytest

from monitor_app.evidence import EvidencePacket
from monitor_app.fusion import CameraFusion
from monitor_app.events import get_event_bus


class MockDecisionEngine:
    def __init__(self, should_trigger=True, event_type="cellphone", conf_scores=None, severity="HIGH"):
        self.should_trigger = should_trigger
        self.event_type = event_type
        self.conf_scores = conf_scores or {"cellphone": 0.85}
        self.severity = severity

    def evaluate_trigger(self, packet):
        return self.should_trigger

    def get_event_details(self, packet):
        return self.event_type, self.conf_scores

    def get_severity(self, packet):
        return self.severity


def _make_packet(camera_id, timestamp=100.0):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    return EvidencePacket(camera_id=camera_id, timestamp=timestamp, frame=frame)


def test_zone_mapping_resolution():
    fusion = CameraFusion()
    fusion.camera_zones = {"cam1": "Cell_Block_A", "cam2": "Cell_Block_A"}
    
    assert fusion.resolve_zone("cam1") == "Cell_Block_A"
    assert fusion.resolve_zone("cam2") == "Cell_Block_A"
    # Unmapped camera falls back to Zone_<cam_id>
    assert fusion.resolve_zone("cam99") == "Zone_cam99"


def test_cross_camera_zone_dedup_suppresses_alarm_storm():
    fusion = CameraFusion()
    fusion.camera_zones = {"cam1": "Cell_Block_A", "cam2": "Cell_Block_A"}
    fusion.zone_dedup_window_s = 7.0

    bus = get_event_bus()
    emitted_events = []

    def on_trigger(camera_id, event_type, severity, **kwargs):
        emitted_events.append((camera_id, event_type, severity))

    bus.subscribe("DECISION_TRIGGER", on_trigger)

    try:
        dec = MockDecisionEngine(should_trigger=True, event_type="cellphone", severity="HIGH")

        # 1. Camera 1 detects contraband in Cell_Block_A at t=100.0
        pkt1 = _make_packet("cam1", timestamp=100.0)
        res1 = fusion.process_decision_trigger(pkt1, dec, ai_results={})
        
        # Must emit DECISION_TRIGGER for Camera 1
        assert res1 is True
        assert len(emitted_events) == 1
        assert emitted_events[0] == ("cam1", "cellphone", "HIGH")

        # 2. Camera 2 detects contraband in SAME Cell_Block_A at t=102.5 (within 7.0s window)
        pkt2 = _make_packet("cam2", timestamp=102.5)
        res2 = fusion.process_decision_trigger(pkt2, dec, ai_results={})

        # Must SUPPRESS duplicate trigger (prevent audio alarm storm)
        assert res2 is False
        assert len(emitted_events) == 1  # No new event emitted

        # Corroborating evidence is recorded
        zone_event = fusion.get_active_zone_event("Cell_Block_A", "cellphone")
        assert zone_event is not None
        assert "cam2" in zone_event["corroborating_cameras"]

    finally:
        bus.unsubscribe("DECISION_TRIGGER", on_trigger)


def test_zone_dedup_window_expiration():
    fusion = CameraFusion()
    fusion.camera_zones = {"cam1": "Cell_Block_A", "cam2": "Cell_Block_A"}
    fusion.zone_dedup_window_s = 5.0

    bus = get_event_bus()
    emitted_events = []

    def on_trigger(camera_id, event_type, severity, **kwargs):
        emitted_events.append((camera_id, event_type, severity))

    bus.subscribe("DECISION_TRIGGER", on_trigger)

    try:
        dec = MockDecisionEngine(should_trigger=True, event_type="fight", severity="CRITICAL")

        # Event 1 at t=100.0
        pkt1 = _make_packet("cam1", timestamp=100.0)
        fusion.process_decision_trigger(pkt1, dec, ai_results={})
        assert len(emitted_events) == 1

        # Event 2 at t=106.0 (> 5.0s window expired)
        pkt2 = _make_packet("cam2", timestamp=106.0)
        res2 = fusion.process_decision_trigger(pkt2, dec, ai_results={})

        # New incident triggered after window expired
        assert res2 is True
        assert len(emitted_events) == 2
        assert emitted_events[1] == ("cam2", "fight", "CRITICAL")

    finally:
        bus.unsubscribe("DECISION_TRIGGER", on_trigger)
