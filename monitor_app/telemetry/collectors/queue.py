import collections
import threading
import time

class QueueCollector:
    """
    Monitors inference queue usage, backlog sizes, and peak backlog depths.
    Enforces a strict 1000-sample ring buffer.
    """
    def __init__(self, max_samples: int = 1000, max_duration_sec: float = 300.0):
        self.max_samples = max_samples
        self.max_duration_sec = max_duration_sec
        self.lock = threading.Lock()
        
        # Deque of (timestamp, queue_size)
        self.history = collections.deque(maxlen=max_samples)
        
        self.peak_size = 0
        self.overflow_events = 0

    def on_event(self, event_name: str, payload: dict):
        now = time.time()
        
        if event_name == "TELEM_QUEUE_TICK":
            size = payload.get("queue_size", 0)
            with self.lock:
                self.history.append((now, size))
                if size > self.peak_size:
                    self.peak_size = size
                    
        elif event_name == "TELEM_FRAME_DROPPED":
            reason = payload.get("reason", "")
            if "queue" in reason.lower() or "backpressure" in reason.lower():
                with self.lock:
                    self.overflow_events += 1

    def _prune_old_data(self, now: float):
        cutoff = now - self.max_duration_sec
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()

    def clear(self):
        with self.lock:
            self.history.clear()
            self.peak_size = 0
            self.overflow_events = 0

    def get_stats(self) -> dict:
        now = time.time()
        with self.lock:
            self._prune_old_data(now)
            
            sizes = [h[1] for h in self.history]
            avg_size = sum(sizes) / len(sizes) if sizes else 0.0
            current_size = sizes[-1] if sizes else 0
            
            return {
                "current_queue_size": current_size,
                "avg_queue_size": round(avg_size, 2),
                "peak_queue_size": self.peak_size,
                "overflow_events": self.overflow_events
            }
            
    def get_history(self) -> list:
        now = time.time()
        with self.lock:
            self._prune_old_data(now)
            return list(self.history)
