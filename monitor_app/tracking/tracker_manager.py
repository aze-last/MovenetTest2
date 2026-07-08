import torch
from ultralytics.utils import IterableSimpleNamespace
from ultralytics.trackers.byte_tracker import BYTETracker
from monitor_app.config import get_config
from monitor_app.events import get_event_bus, TRACK_CREATED, TRACK_UPDATED, TRACK_LOST, TRACK_RECOVERED, TRACK_TERMINATED

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
            track_thresh=human_cfg.get("track_thresh", 0.50),
            track_buffer=human_cfg.get("track_buffer", 30),
            match_thresh=human_cfg.get("match_thresh", 0.8),
            frame_rate=30,
            track_high_thresh=human_cfg.get("track_thresh", 0.5),
            track_low_thresh=0.1,
            new_track_thresh=human_cfg.get("track_thresh", 0.5) + 0.1,
            fuse_score=False
        )
        self.human_tracker = BYTETracker(args_human)
        
        # Setup Object Tracker
        args_obj = IterableSimpleNamespace(
            track_thresh=object_cfg.get("track_thresh", 0.3),
            track_buffer=object_cfg.get("track_buffer", 10),
            match_thresh=object_cfg.get("match_thresh", 0.8),
            frame_rate=15,
            track_high_thresh=object_cfg.get("track_thresh", 0.3),
            track_low_thresh=0.1,
            new_track_thresh=object_cfg.get("track_thresh", 0.3) + 0.1,
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
            hb_tensor = torch.tensor(human_boxes, dtype=torch.float32)
            human_tracks = self.human_tracker.update(hb_tensor, frame)
        else:
            # Step tracker with empty tensor to decay lost tracks
            self.human_tracker.update(torch.empty((0, 6)), frame)
            
        # Process Object Tracks
        if self.object_tracking_enabled and object_boxes:
            ob_tensor = torch.tensor(object_boxes, dtype=torch.float32)
            object_tracks = self.object_tracker.update(ob_tensor, frame)
        elif self.object_tracking_enabled:
            self.object_tracker.update(torch.empty((0, 6)), frame)

        # Emit events
        self.active_human_ids = self._detect_state_changes(human_tracks, self.active_human_ids, "human")
        self.active_object_ids = self._detect_state_changes(object_tracks, self.active_object_ids, "object")

        return human_tracks, object_tracks
