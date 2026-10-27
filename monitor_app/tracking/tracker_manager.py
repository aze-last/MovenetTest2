import numpy as np
import torch
from ultralytics.utils import IterableSimpleNamespace
from ultralytics.trackers.byte_tracker import BYTETracker
from monitor_app.config import get_config
from monitor_app.events import get_event_bus, TRACK_CREATED, TRACK_UPDATED, TRACK_LOST, TRACK_RECOVERED, TRACK_TERMINATED


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

class TrackerManager:
    def __init__(self, cam_id):
        self.cam_id = cam_id
        
        # Load configs
        trk_cfg = get_config("tracking")
        human_cfg = trk_cfg.get("human_tracking", {})
        object_cfg = trk_cfg.get("object_tracking", {})
        
        self.include_classes = object_cfg.get("include_classes", ["cellphone", "knife"])
        self.exclude_classes = object_cfg.get("exclude_classes", ["person"])
        self.object_tracking_enabled = object_cfg.get("enabled", True)
        
        # Setup Human Tracker
        args_human = IterableSimpleNamespace(
            track_thresh=human_cfg.get("track_thresh", 0.25),
            track_buffer=human_cfg.get("track_buffer", 60),
            match_thresh=human_cfg.get("match_thresh", 0.5),
            frame_rate=30,
            track_high_thresh=human_cfg.get("track_thresh", 0.25),
            track_low_thresh=0.05,
            new_track_thresh=human_cfg.get("track_thresh", 0.25) + 0.05,
            fuse_score=False
        )
        self.human_tracker = BYTETracker(args_human)
        
        # Setup Object Tracker
        args_obj = IterableSimpleNamespace(
            track_thresh=object_cfg.get("track_thresh", 0.20),
            track_buffer=object_cfg.get("track_buffer", 45),
            match_thresh=object_cfg.get("match_thresh", 0.5),
            frame_rate=15,
            track_high_thresh=object_cfg.get("track_thresh", 0.20),
            track_low_thresh=0.05,
            new_track_thresh=object_cfg.get("track_thresh", 0.20) + 0.05,
            fuse_score=False
        )
        self.object_tracker = BYTETracker(args_obj)
        
        # State tracking for events
        self.active_human_ids = set()
        self.active_object_ids = set()

    def _detect_state_changes(self, current_tracks, previous_ids, track_type):
        bus = get_event_bus()
        current_ids = {int(t[4]) for t in current_tracks}  # track_id is at index 4
        
        # New tracks
        for tid in current_ids - previous_ids:
            bus.publish(TRACK_CREATED, cam_id=self.cam_id, track_id=tid, type=track_type)
            
        # Lost tracks
        for tid in previous_ids - current_ids:
            bus.publish(TRACK_LOST, cam_id=self.cam_id, track_id=tid, type=track_type)
            
        # Updated tracks
        for tid in current_ids.intersection(previous_ids):
            bus.publish(TRACK_UPDATED, cam_id=self.cam_id, track_id=tid, type=track_type)
            
        return current_ids

    def update(self, human_boxes, object_boxes, frame):
        """
        Updates both trackers and fires events.
        human_boxes, object_boxes: list of [x1, y1, x2, y2, conf, cls_id]
        Returns tuple of (human_tracks, object_tracks)
        where each track is [x1, y1, x2, y2, track_id, conf, cls_id, idx]
        """
        human_tracks = []
        object_tracks = []

        # Process Human Tracks
        if human_boxes:
            boxes_arr = np.asarray(human_boxes, dtype=np.float32)
            xyxy = boxes_arr[:, :4]
            conf = boxes_arr[:, 4] if boxes_arr.shape[1] > 4 else np.ones(len(boxes_arr), dtype=np.float32)
            cls = boxes_arr[:, 5] if boxes_arr.shape[1] > 5 else np.zeros(len(boxes_arr), dtype=np.float32)
            det = DetectionsAdapter(xyxy, conf, cls)
            human_tracks = self.human_tracker.update(det, frame)
        else:
            # Step tracker with empty adapter to decay lost tracks
            human_tracks = self.human_tracker.update(DetectionsAdapter([], [], []), frame)
            
        # Process Object Tracks
        if self.object_tracking_enabled and object_boxes:
            boxes_arr = np.asarray(object_boxes, dtype=np.float32)
            xyxy = boxes_arr[:, :4]
            conf = boxes_arr[:, 4] if boxes_arr.shape[1] > 4 else np.ones(len(boxes_arr), dtype=np.float32)
            cls = boxes_arr[:, 5] if boxes_arr.shape[1] > 5 else np.ones(len(boxes_arr), dtype=np.float32)
            det = DetectionsAdapter(xyxy, conf, cls)
            object_tracks = self.object_tracker.update(det, frame)
        elif self.object_tracking_enabled:
            object_tracks = self.object_tracker.update(DetectionsAdapter([], [], []), frame)

        # Emit events
        self.active_human_ids = self._detect_state_changes(human_tracks, self.active_human_ids, "human")
        self.active_object_ids = self._detect_state_changes(object_tracks, self.active_object_ids, "object")

        return list(human_tracks), list(object_tracks)
