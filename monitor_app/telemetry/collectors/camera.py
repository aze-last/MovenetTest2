import collections
import threading
import time
from typing import Dict

class CameraCollector:
    """
    Tracks camera-specific metrics: FPS, read latency, reconnects, 
    dropped frames, signal lost, and queue delay per stream.
    Enforces a strict 5000-frame ring buffer per camera stream.
    """
    def __init__(self, max_frames: int = 5000, max_duration_sec: float = 300.0):
        self.max_frames = max_frames
        self.max_duration_sec = max_duration_sec
        self.lock = threading.Lock()
        
        # Deque of (timestamp, value) per camera
        self.frame_read_times = collections.defaultdict(lambda: collections.deque(maxlen=max_frames))
        self.queue_delays = collections.defaultdict(lambda: collections.deque(maxlen=max_frames))
        
        # Failure/Incident Counters
        self.reconnect_counts = collections.defaultdict(int)
        self.dropped_frames = collections.defaultdict(int)
        self.signal_lost_counts = collections.defaultdict(int)

    def on_event(self, event_name: str, payload: dict):
        camera_id = payload.get("camera_id")
        if not camera_id:
            return
        
        now = time.time()
        
        if event_name == "TELEM_FRAME_READ":
            with self.lock:
                self.frame_read_times[camera_id].append((now, payload.get("timestamps", {}).get("camera_read_end", now)))
                
        elif event_name == "TELEM_FRAME_DROPPED":
            with self.lock:
                self.dropped_frames[camera_id] += 1
                
        elif event_name == "TELEM_PIPELINE_COMPLETE":
            with self.lock:
                # Calculate Queue Wait Delay
                timestamps = payload.get("timestamps", {})
                enter = timestamps.get("queue_enter")
                exit = timestamps.get("queue_exit")
                if enter is not None and exit is not None:
                    delay_ms = (exit - enter) * 1000.0
                    self.queue_delays[camera_id].append((now, delay_ms))
                    
        elif event_name == "TELEM_HEALTH_ALERT":
            alert_type = payload.get("alert_type")
            if alert_type == "CAMERA_RECONNECT":
                with self.lock:
                    self.reconnect_counts[camera_id] += 1
            elif alert_type == "SIGNAL_LOST":
                with self.lock:
                    self.signal_lost_counts[camera_id] += 1

    def _prune_old_data(self, dq: collections.deque, now: float):
        """Remove entries older than the max duration (5 minutes)."""
        cutoff = now - self.max_duration_sec
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def clear(self):
        with self.lock:
            self.frame_read_times.clear()
            self.queue_delays.clear()
            self.reconnect_counts.clear()
            self.dropped_frames.clear()
            self.signal_lost_counts.clear()

    def get_stats(self) -> dict:
        now = time.time()
        stats = {}
        with self.lock:
            for cam_id in list(self.frame_read_times.keys()):
                # Prune and calculate FPS
                reads = self.frame_read_times[cam_id]
                self._prune_old_data(reads, now)
                
                fps = 0.0
                if len(reads) > 1:
                    span = now - reads[0][0]
                    if span > 0:
                        fps = len(reads) / span
                
                # Prune and calculate Queue Delay
                delays = self.queue_delays[cam_id]
                self._prune_old_data(delays, now)
                
                delay_vals = [d[1] for d in delays]
                avg_delay = sum(delay_vals) / len(delay_vals) if delay_vals else 0.0
                max_delay = max(delay_vals) if delay_vals else 0.0
                
                stats[cam_id] = {
                    "fps": round(fps, 2),
                    "dropped_frames": self.dropped_frames[cam_id],
                    "reconnects": self.reconnect_counts[cam_id],
                    "signal_lost": self.signal_lost_counts[cam_id],
                    "avg_queue_delay_ms": round(avg_delay, 2),
                    "max_queue_delay_ms": round(max_delay, 2)
                }
        return stats
