# scratch/patch_dynamic_tracking.py
import re

with open("monitor_app/ai_engine.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Define DynamicContrabandTracker class
tracker_class = '''
class DynamicContrabandTracker:
    """
    Per-camera dynamic contraband tracker with IoU and spatial proximity association.
    Assigns a stable, monotonic track ID to sustained contraband detections.
    When an object leaves the field of view and another object appears,
    a NEW unique track ID is allocated (e.g. 1001, 1002, 1003...).
    This prevents operator dismissals of one object (e.g. vape/glare) from colliding
    with subsequent real objects (e.g. phone) presented in the same field of view.
    """
    def __init__(self, iou_thresh: float = 0.25, max_lost_frames: int = 15):
        import threading
        self.iou_thresh = iou_thresh
        self.max_lost_frames = max_lost_frames
        self.lock = threading.Lock()
        self._next_track_id = 1001
        # cam_id -> {track_id: {"box": list, "score": float, "cls_id": int, "lost_count": int}}
        self.camera_tracks = {}

    @staticmethod
    def _calc_iou(box_a, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def update(self, camera_id, boxes, scores, class_ids):
        cam_str = str(camera_id)
        with self.lock:
            if cam_str not in self.camera_tracks:
                self.camera_tracks[cam_str] = {}
            active_tracks = self.camera_tracks[cam_str]

            matched_track_ids = set()
            results = []

            for box, score, cls_id in zip(boxes, scores, class_ids):
                best_match_id = None
                best_iou = self.iou_thresh

                for tid, trk in active_tracks.items():
                    if tid in matched_track_ids or trk["cls_id"] != cls_id:
                        continue
                    iou = self._calc_iou(box, trk["box"])
                    if iou > best_iou:
                        best_iou = iou
                        best_match_id = tid

                # Centroid proximity fallback if box shifted rapidly (within 90 px)
                if best_match_id is None:
                    bx_c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                    best_dist = 90.0
                    for tid, trk in active_tracks.items():
                        if tid in matched_track_ids or trk["cls_id"] != cls_id:
                            continue
                        tx_c = ((trk["box"][0] + trk["box"][2]) / 2, (trk["box"][1] + trk["box"][3]) / 2)
                        dist = ((bx_c[0] - tx_c[0])**2 + (bx_c[1] - tx_c[1])**2)**0.5
                        if dist < best_dist:
                            best_dist = dist
                            best_match_id = tid

                if best_match_id is not None:
                    active_tracks[best_match_id]["box"] = box
                    active_tracks[best_match_id]["score"] = score
                    active_tracks[best_match_id]["lost_count"] = 0
                    matched_track_ids.add(best_match_id)
                    assigned_id = best_match_id
                else:
                    assigned_id = self._next_track_id
                    self._next_track_id += 1
                    active_tracks[assigned_id] = {
                        "box": box,
                        "score": score,
                        "cls_id": cls_id,
                        "lost_count": 0
                    }
                    matched_track_ids.add(assigned_id)

                results.append({
                    "track_id": assigned_id,
                    "box": box,
                    "score": score,
                    "cls_id": cls_id
                })

            # Age unmatched tracks
            dead_tids = []
            for tid, trk in active_tracks.items():
                if tid not in matched_track_ids:
                    trk["lost_count"] += 1
                    if trk["lost_count"] >= self.max_lost_frames:
                        dead_tids.append(tid)

            for tid in dead_tids:
                del active_tracks[tid]

            return results
'''

# Insert tracker class right before MotionOptimizedEngine
if "class DynamicContrabandTracker:" not in content:
    target_cls = "class MotionOptimizedEngine:"
    content = content.replace(target_cls, tracker_class + "\n\n" + target_cls, 1)

# In MotionOptimizedEngine.__init__, add self.contraband_tracker
if "self.contraband_tracker" not in content:
    init_target = "self.yolo_hysteresis = {}"
    content = content.replace(init_target, init_target + "\n        self.contraband_tracker = DynamicContrabandTracker()", 1)

# In _run_yolo_logic, replace the static hash with DynamicContrabandTracker
old_untracked_block = """                                if track_id != -1:
                                    cache_key = track_id
                                    effective_track_id = track_id
                                else:
                                    grid_px = get_config("yolo", "untracked_grid_px", 96)
                                    cache_key = self._untracked_cache_key(cls_id, x1, y1, x2, y2, grid_px)
                                    effective_track_id = abs(hash(cache_key)) % 9000 + 1000"""

new_untracked_block = """                                if track_id != -1:
                                    cache_key = track_id
                                    effective_track_id = track_id
                                else:
                                    # Dynamic tracking fallback: assigns monotonic, stable track IDs
                                    # that never collide between different objects shown in the same spot
                                    trk_res = self.contraband_tracker.update(
                                        cam_id, [[x1, y1, x2, y2]], [conf], [cls_id]
                                    )
                                    effective_track_id = trk_res[0]["track_id"] if trk_res else (abs(hash((cls_id, x1, y1))) % 9000 + 1000)
                                    cache_key = effective_track_id"""

if old_untracked_block in content:
    content = content.replace(old_untracked_block, new_untracked_block, 1)
    print("Replaced untracked block successfully!")
else:
    print("WARNING: old_untracked_block not found in content!")

with open("monitor_app/ai_engine.py", "w", encoding="utf-8") as f:
    f.write(content)

print("monitor_app/ai_engine.py updated successfully!")

