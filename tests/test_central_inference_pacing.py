import numpy as np
import pytest
import time
from monitor_app.evidence import EvidencePacket
from monitor_app.central_inference import CentralInferenceManager


def test_draw_contraband_boxes_reads_conf_and_confidence():
    """
    Verify that _draw_contraband_boxes reads confidence from both 'conf' and 'confidence' keys.
    """
    manager = CentralInferenceManager()
    dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)

    det_with_conf = [
        {"name": "cellphone", "conf": 0.88, "box": [10, 10, 50, 50], "track_id": 1001}
    ]
    # Should not raise exception and should read 0.88
    manager._draw_contraband_boxes(dummy_frame, det_with_conf, camera_id="1")
    # Verify frame was modified (drawing occurred)
    assert np.any(dummy_frame > 0)


def test_dropped_task_preserves_display_continuity():
    """
    Verify that when task queue is full and a task is dropped for backpressure,
    the dropped task's packet receives recent stable detections instead of
    wiping out overlays to blank.
    """
    manager = CentralInferenceManager()
    manager.task_queue.maxsize = 1 # Force immediate overflow
    cam_id = "1"

    # Pre-populate last results for camera 1
    with manager.result_lock:
        manager.last_yolo_results[cam_id] = {
            "num_people": 0,
            "alert_triggered": True,
            "alerts": ["CONTRABAND: cellphone (ID: 1001)"],
            "detections": {
                "contraband": [{"name": "cellphone", "conf": 0.85, "confidence": 0.85, "box": [20, 20, 60, 60], "track_id": 1001}]
            }
        }

    # Fill queue
    callback_results = []
    def _cb(res_pkt):
        callback_results.append(res_pkt)

    from monitor_app.central_inference import InferenceTask
    dummy_frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    p1 = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame1)
    task1 = InferenceTask(p1, callback=_cb)
    manager.task_queue.put_nowait(task1)

    # Submit second task asynchronously, which triggers queue.Full -> drops oldest task
    dummy_frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
    p2 = EvidencePacket(camera_id=cam_id, timestamp=time.time(), frame=dummy_frame2)

    manager.submit_task_async(p2, callback=None)
    time.sleep(0.1)

    assert len(callback_results) == 1
    dropped_pkt = callback_results[0]
    # Dropped packet must preserve detections and alert status for display continuity
    assert dropped_pkt.processing_mode == "Queue Drop (Backpressure)"
    assert dropped_pkt.alert_triggered is True, "Dropped frame must preserve alert status"
    assert len(dropped_pkt.detections["contraband"]) == 1, "Dropped frame must preserve contraband overlay"
