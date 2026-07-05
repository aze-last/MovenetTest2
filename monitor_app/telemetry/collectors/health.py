import collections
import threading
import time
import psutil
from typing import Dict

class HealthCollector:
    """
    Failure-first health collector.
    Tracks reconnection spikes, model errors, database retries, and
    calculates memory/thread accumulation trends.
    Enforces a strict 500-sample historical memory.
    """
    def __init__(self, max_samples: int = 500, max_duration_sec: float = 300.0):
        self.max_samples = max_samples
        self.max_duration_sec = max_duration_sec
        self.lock = threading.Lock()
        
        # Deque of (timestamp, memory_bytes, thread_count)
        self.resource_history = collections.deque(maxlen=max_samples)
        
        # Failure tracking counters
        self.failures = {
            "camera_reconnects": 0,
            "inference_failures": 0,
            "yolo_load_failures": 0,
            "movenet_exceptions": 0,
            "dropped_events": 0,
            "database_retries": 0,
            "recorder_failures": 0
        }
        
        # First Failure Point tracing
        self.first_failure = None

    def on_event(self, event_name: str, payload: dict):
        now = time.time()
        
        # Track failure signals
        if event_name == "TELEM_HEALTH_ALERT":
            alert_type = payload.get("alert_type")
            with self.lock:
                # Record first failure point
                if self.first_failure is None:
                    self.first_failure = {
                        "timestamp": now,
                        "event": event_name,
                        "type": alert_type,
                        "camera_id": payload.get("camera_id"),
                        "message": payload.get("message", "Health alert raised")
                    }

                if alert_type == "CAMERA_RECONNECT":
                    self.failures["camera_reconnects"] += 1
                elif alert_type == "INFERENCE_FAIL":
                    self.failures["inference_failures"] += 1
                elif alert_type == "YOLO_LOAD_FAIL":
                    self.failures["yolo_load_failures"] += 1
                elif alert_type == "MOVENET_EXCEPTION":
                    self.failures["movenet_exceptions"] += 1
                elif alert_type == "DB_RETRY":
                    self.failures["database_retries"] += 1
                elif alert_type == "RECORDER_FAIL":
                    self.failures["recorder_failures"] += 1
                    
        elif event_name == "TELEM_FRAME_DROPPED":
            with self.lock:
                if self.first_failure is None:
                    self.first_failure = {
                        "timestamp": now,
                        "event": event_name,
                        "type": "FRAME_DROPPED",
                        "camera_id": payload.get("camera_id"),
                        "message": f"Frame dropped due to: {payload.get('reason', 'unknown')}"
                    }
                self.failures["dropped_events"] += 1
                
        elif event_name == "TELEM_SYSTEM_TICK":
            # Track memory/thread allocations to measure leak rates
            process = psutil.Process()
            try:
                mem_bytes = process.memory_info().rss
                threads = process.num_threads()
                with self.lock:
                    self.resource_history.append((now, mem_bytes, threads))
            except Exception:
                pass

    def _prune_old_data(self, now: float):
        cutoff = now - self.max_duration_sec
        while self.resource_history and self.resource_history[0][0] < cutoff:
            self.resource_history.popleft()

    def clear(self):
        with self.lock:
            self.resource_history.clear()
            for k in self.failures:
                self.failures[k] = 0
            self.first_failure = None

    def _calculate_slope(self) -> float:
        """Calculates memory growth slope (MB per minute) over the history window."""
        if len(self.resource_history) < 10:
            return 0.0
            
        t0, m0, _ = self.resource_history[0]
        tn, mn, _ = self.resource_history[-1]
        
        dt_min = (tn - t0) / 60.0
        if dt_min <= 0:
            return 0.0
            
        d_mem_mb = (mn - m0) / (1024 * 1024)
        return round(d_mem_mb / dt_min, 3)

    def get_stats(self) -> dict:
        now = time.time()
        with self.lock:
            self._prune_old_data(now)
            
            # Leak indicators
            mem_slope = self._calculate_slope()
            
            latest_threads = 0
            if self.resource_history:
                latest_threads = self.resource_history[-1][2]
                
            # Detect thread leaks (linear increase)
            thread_leak_detected = False
            if len(self.resource_history) >= 10:
                t0_threads = self.resource_history[0][2]
                if latest_threads - t0_threads > 15:
                    thread_leak_detected = True
            
            return {
                "failures": self.failures.copy(),
                "first_failure": self.first_failure.copy() if self.first_failure else None,
                "memory_leak_slope_mb_min": mem_slope,
                "thread_count": latest_threads,
                "thread_leak_detected": thread_leak_detected
            }
