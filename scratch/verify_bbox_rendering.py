import sys
import os
sys.path.insert(0, os.path.abspath("."))

import cv2
import numpy as np

from monitor_app.central_inference import CentralInferenceManager
from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.config import get_config

def test_bbox_enhancements():
    # 1. Test compute_bbox_from_keypoints padding
    kps = np.zeros((17, 3), dtype=np.float32)
    # Nose at (0.2, 0.5), ankles at (0.8, 0.4) and (0.8, 0.6)
    kps[0] = [0.2, 0.5, 0.9]
    kps[15] = [0.8, 0.4, 0.85]
    kps[16] = [0.8, 0.6, 0.88]

    bbox = MotionOptimizedEngine.compute_bbox_from_keypoints(kps, (1080, 1920))
    assert bbox is not None
    x1, y1, x2, y2 = bbox
    print(f"Computed bbox for 1920x1080: {bbox}")
    w = x2 - x1
    h = y2 - y1
    print(f"Bbox dimensions: {w}x{h} px")
    assert w > 0 and h > 0

    # 2. Test CentralInferenceManager drawing at various resolutions
    cim = CentralInferenceManager.__new__(CentralInferenceManager)

    for res in [(640, 480), (1280, 720), (1920, 1080)]:
        f_h, f_w = res[1], res[0]
        frame = np.zeros((f_h, f_w, 3), dtype=np.uint8)
        
        # Test person box
        cim._draw_person_box(frame, (50, 50, f_w - 50, f_h - 50), stable_id=4, is_alert=False)
        cim._draw_person_box(frame, (100, 100, 300, 400), stable_id=7, is_alert=True, alert_types=["FIGHTING"])

        # Test contraband box
        sample_dets = [{
            "name": "cellphone",
            "track_id": 12,
            "confidence": 0.92,
            "box": [150, 150, 250, 350]
        }]
        # Mock _contraband_for_render
        cim._contraband_for_render = lambda dets: dets
        cim._draw_contraband_boxes(frame, sample_dets)

        # Test downscaling
        cw, ch = 480, 270
        interp = cv2.INTER_AREA if (f_w > cw and f_h > ch) else cv2.INTER_LINEAR
        resized = cv2.resize(frame, (cw, ch), interpolation=interp)
        assert resized.shape == (ch, cw, 3)
        print(f"Tested resolution {f_w}x{f_h} -> downscaled to {cw}x{ch} successfully!")

    print("ALL BBOX RENDERING CHECKS PASSED.")

if __name__ == "__main__":
    test_bbox_enhancements()

