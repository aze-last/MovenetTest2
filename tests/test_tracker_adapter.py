import numpy as np
import pytest
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace

class DetectionsAdapter:
    """
    Adapter satisfying Ultralytics BYTETracker input protocol.
    Converts [x1, y1, x2, y2] input into center-based [cx, cy, w, h] format
    expected by parse_bboxes().
    """
    def __init__(self, xyxy, conf, cls):
        xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)
        
        # Convert xyxy [x1, y1, x2, y2] to center-based xywh [cx, cy, w, h]
        if len(xyxy) > 0:
            w = xyxy[:, 2] - xyxy[:, 0]
            h = xyxy[:, 3] - xyxy[:, 1]
            cx = xyxy[:, 0] + w / 2.0
            cy = xyxy[:, 1] + h / 2.0
            self.xywh = np.stack([cx, cy, w, h], axis=-1)
        else:
            self.xywh = np.empty((0, 4), dtype=np.float32)

    def __len__(self):
        return len(self.conf)

    def __getitem__(self, mask):
        res = DetectionsAdapter(np.empty((0, 4)), [], [])
        res.xywh = self.xywh[mask]
        res.conf = self.conf[mask]
        res.cls = self.cls[mask]
        return res

def test_detections_adapter_non_square_box_tracking():
    args = IterableSimpleNamespace(
        track_thresh=0.25,
        track_buffer=30,
        match_thresh=0.8,
        frame_rate=30,
        track_high_thresh=0.25,
        track_low_thresh=0.05,
        new_track_thresh=0.3,
        fuse_score=False
    )
    bt = BYTETracker(args)
    
    # Non-square bounding box: x1=120, y1=80, x2=360 (w=240), y2=560 (h=480)
    input_box = [120.0, 80.0, 360.0, 560.0]
    conf = 0.92
    cls_id = 0
    
    det = DetectionsAdapter([input_box], [conf], [cls_id])
    assert det.xywh.shape == (1, 4)
    # Check center-based xywh conversion
    assert np.isclose(det.xywh[0, 0], 240.0)  # cx = 120 + 240/2 = 240
    assert np.isclose(det.xywh[0, 1], 320.0)  # cy = 80 + 480/2 = 320
    assert np.isclose(det.xywh[0, 2], 240.0)  # w = 360 - 120 = 240
    assert np.isclose(det.xywh[0, 3], 480.0)  # h = 560 - 80 = 480
    
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    output = bt.update(det, frame)
    
    assert len(output) == 1
    # output format: [x1, y1, x2, y2, track_id, score, cls, idx]
    out_x1, out_y1, out_x2, out_y2, track_id, score, out_cls, idx = output[0]
    assert np.isclose(out_x1, 120.0, atol=1.0)
    assert np.isclose(out_y1, 80.0, atol=1.0)
    assert np.isclose(out_x2, 360.0, atol=1.0)
    assert np.isclose(out_y2, 560.0, atol=1.0)
    assert track_id == 1
    assert np.isclose(score, conf)
    assert out_cls == cls_id

def test_detections_adapter_empty_handling():
    args = IterableSimpleNamespace(
        track_thresh=0.25,
        track_buffer=30,
        match_thresh=0.8,
        frame_rate=30,
        track_high_thresh=0.25,
        track_low_thresh=0.05,
        new_track_thresh=0.3,
        fuse_score=False
    )
    bt = BYTETracker(args)
    det = DetectionsAdapter([], [], [])
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    output = bt.update(det, frame)
    assert len(output) == 0
