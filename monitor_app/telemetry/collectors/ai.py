import collections
import math
import threading
import time
from typing import Dict, List, Tuple

class AICollector:
    """
    Tracks stage-by-stage latency timings (Camera Read, Motion Gate, MoveNet,
    YOLO, Fusion, Behavior Modules, Decision Engine, Recorder, Database).
    Enforces a strict 5000-frame ring buffer of latency measurements.
    """
    STAGES = [
        ("camera_read", "camera_read_start", "camera_read_end"),
        ("motion_gate", "motion_gate_start", "motion_gate_end"),
        ("movenet", "movenet_start", "movenet_end"),
        ("yolo", "yolo_start", "yolo_end"),
        ("fusion", "fusion_start", "fusion_end"),
        ("behavior", "behavior_start", "behavior_end"),
        ("decision", "decision_start", "decision_end"),
        ("recorder", "recorder_write_start", "recorder_write_end"),
        ("database", "database_write_start", "database_write_end")
    ]

    def __init__(self, max_frames: int = 5000, max_duration_sec: float = 300.0):
        self.max_frames = max_frames
        self.max_duration_sec = max_duration_sec
        self.lock = threading.Lock()
        
        # Deque of (timestamp, latency_dict)
        self.history = collections.deque(maxlen=max_frames)

        # Register metrics dynamically
        from monitor_app.telemetry.registry import get_registry
        reg = get_registry()
        for stage_name, _, _ in self.STAGES:
            reg.register_metric(
                f"{stage_name}_latency",
                f"{stage_name.replace('_', ' ').title()} Latency",
                "ms",
                "ai_pipeline"
            )

    def on_event(self, event_name: str, payload: dict):
        if event_name != "TELEM_PIPELINE_COMPLETE":
            return
            
        timestamps = payload.get("timestamps", {})
        if not timestamps:
            return
            
        now = time.time()
        stage_latencies = {}
        
        for stage_name, start_key, end_key in self.STAGES:
            start = timestamps.get(start_key)
            end = timestamps.get(end_key)
            if start is not None and end is not None:
                stage_latencies[stage_name] = (end - start) * 1000.0  # ms
            else:
                stage_latencies[stage_name] = 0.0

        with self.lock:
            self.history.append((now, stage_latencies))

    def _prune_old_data(self, now: float):
        cutoff = now - self.max_duration_sec
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()

    def clear(self):
        with self.lock:
            self.history.clear()

    def _calculate_metrics(self, values: List[float]) -> dict:
        if not values:
            return {"avg": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "p95": 0.0, "p99": 0.0, "stddev": 0.0}
            
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        
        avg = sum(sorted_vals) / n
        minimum = sorted_vals[0]
        maximum = sorted_vals[-1]
        
        # Median
        if n % 2 == 1:
            median = sorted_vals[n // 2]
        else:
            median = (sorted_vals[(n // 2) - 1] + sorted_vals[n // 2]) / 2.0
            
        # Percentiles
        p95_idx = max(0, min(n - 1, int(math.ceil(0.95 * n)) - 1))
        p99_idx = max(0, min(n - 1, int(math.ceil(0.99 * n)) - 1))
        p95 = sorted_vals[p95_idx]
        p99 = sorted_vals[p99_idx]
        
        # Std Dev
        variance = sum((x - avg) ** 2 for x in sorted_vals) / n
        stddev = math.sqrt(variance)
        
        return {
            "avg": round(avg, 2),
            "median": round(median, 2),
            "min": round(minimum, 2),
            "max": round(maximum, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "stddev": round(stddev, 2)
        }

    def get_stats(self) -> dict:
        now = time.time()
        stats = {}
        
        with self.lock:
            self._prune_old_data(now)
            
            # Group values per stage
            stage_lists = {s[0]: [] for s in self.STAGES}
            for _, latencies in self.history:
                for stage_name in stage_lists.keys():
                    val = latencies.get(stage_name, 0.0)
                    if val > 0.0:  # Only count active stages
                        stage_lists[stage_name].append(val)
            
            for stage_name in stage_lists.keys():
                stats[stage_name] = self._calculate_metrics(stage_lists[stage_name])
                
        return stats
