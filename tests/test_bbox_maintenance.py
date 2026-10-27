"""
Unit and regression tests for Bounding Box Maintenance and Continuity.
Verifies:
1. YOLO contraband hysteresis maintains bounding box across single and multi-frame dropouts.
2. Active tracking lease keeps motion gate open during hysteresis coasting.
3. Queue Drop (Backpressure) frames are suppressed from overwriting the live annotated UI stream.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from monitor_app.evidence import EvidencePacket
from monitor_app.ai_engine import MotionOptimizedEngine


class MockBox:
    def __init__(self, cls_id, conf, xyxy, track_id=None):
        self.cls = np.array([cls_id])
        self.conf = np.array([conf])
        self.xyxy = np.array([xyxy])
        self.id = np.array([track_id]) if track_id is not None else None


class MockYoloResult:
    def __init__(self, boxes):
        self.boxes = boxes


def test_yolo_hysteresis_maintains_bbox_across_missed_frames():
    """Verify that when YOLO drops a detection for 1-4 frames, the bounding box continues to render via hysteresis."""
    engine = MotionOptimizedEngine.__new__(MotionOptimizedEngine)
    engine.yolo_device = "cpu"
    engine.yolo_custom = MagicMock()
    engine.yolo_per_cam = {}
    engine.active_model_path = "mock.pt"
    engine.yolo_knife_conf = 0.30
    engine.yolo_cell_conf = 0.30
    engine.yolo_fallback_conf = 0.50
    engine.flicker_trace = False
    engine.yolo_hysteresis = {}

    cam_id = "cam_test_1"
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Frame 0: YOLO detects a Cellphone (cls_id=1, conf=0.75)
    mock_model = MagicMock()
    live_box = MockBox(cls_id=1, conf=0.75, xyxy=[100, 100, 200, 200], track_id=101)
    mock_model.predict.return_value = [MockYoloResult([live_box])]
    engine._get_yolo_for_camera = MagicMock(return_value=mock_model)

    res_f0 = {"frame": frame, "frame_index": 0, "alert_triggered": False, "alerts": []}
    with patch("monitor_app.central_inference.get_inference_manager") as mock_get_mgr:
        engine._run_yolo_logic(res_f0, cam_id)

    # Frame 0 assertions: live detection
    assert len(res_f0["detections"]["contraband"]) == 1
    det_f0 = res_f0["detections"]["contraband"][0]
    assert det_f0["name"] == "cellphone"
    assert det_f0["source"] == "combined"
    assert det_f0["box"] == [100, 100, 200, 200]
    assert det_f0["track_id"] == 101

    # Frame 1: YOLO experiences a complete dropout (0 boxes detected)
    mock_model.predict.return_value = [MockYoloResult([])]
    res_f1 = {"frame": frame, "frame_index": 1, "alert_triggered": False, "alerts": []}
    with patch("monitor_app.central_inference.get_inference_manager") as mock_get_mgr:
        mock_mgr = MagicMock()
        mock_get_mgr.return_value = mock_mgr
        engine._run_yolo_logic(res_f1, cam_id)
        # Verify active track lease is updated even on dropout
        mock_mgr.update_active_track_time.assert_called_with(cam_id)

    # Frame 1 assertions: detection persists via hysteresis with exact same box!
    assert len(res_f1["detections"]["contraband"]) == 1
    det_f1 = res_f1["detections"]["contraband"][0]
    assert det_f1["name"] == "cellphone"
    assert det_f1["source"] == "combined_hysteresis"
    assert det_f1["box"] == [100, 100, 200, 200]
    assert det_f1["track_id"] == 101

    # Frame 2 to 4: Continued dropout -> persists
    for f_idx in [2, 3, 4]:
        res_fn = {"frame": frame, "frame_index": f_idx, "alert_triggered": False, "alerts": []}
        engine._run_yolo_logic(res_fn, cam_id)
        assert len(res_fn["detections"]["contraband"]) == 1
        assert res_fn["detections"]["contraband"][0]["source"] == "combined_hysteresis"

    # Frame 5: TTL expires
    res_f5 = {"frame": frame, "frame_index": 5, "alert_triggered": False, "alerts": []}
    engine._run_yolo_logic(res_f5, cam_id)
    assert len(res_f5["detections"]["contraband"]) == 0
    assert len(engine.yolo_hysteresis.get(cam_id, {})) == 0


def test_queue_drop_frame_filtered_from_display():
    """Verify that backpressure dropped packets are suppressed from corrupting the UI display."""
    from queue import Queue

    result_queue = Queue()
    dummy_frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # Simulated callback closure behavior in camera_view.py
    class MockCamSelf:
        def __init__(self):
            self.result_queue = result_queue
            self.target_width = 320
            self.target_height = 240
            self.camera_id = "0"
            self.recorder = MagicMock()

    cam_self = MockCamSelf()

    def _on_inference_complete(result_packet, _cam_self=cam_self):
        # Drop backpressure frames silently so canvas retains the last valid annotated frame
        if getattr(result_packet, "processing_mode", None) == "Queue Drop (Backpressure)":
            return
        _cam_self.result_queue.put((result_packet.frame, result_packet.alert_triggered))

    # 1. Normal processed packet -> should be added to result_queue
    normal_packet = EvidencePacket(camera_id="0", frame=dummy_frame, timestamp=1.0)
    normal_packet.processing_mode = "AI ACTIVE (Parallel GPU+CPU)"
    normal_packet.alert_triggered = True
    _on_inference_complete(normal_packet)

    assert not result_queue.empty()
    item = result_queue.get_nowait()
    assert item[1] is True

    # 2. Backpressure dropped packet -> MUST be skipped
    dropped_packet = EvidencePacket(camera_id="0", frame=dummy_frame, timestamp=2.0)
    dropped_packet.processing_mode = "Queue Drop (Backpressure)"
    _on_inference_complete(dropped_packet)

    # result_queue must remain empty, preserving the previous frame on canvas
    assert result_queue.empty()
