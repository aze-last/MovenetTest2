import os
import time
import json
import calendar
import queue
import threading
from typing import Dict, Optional
from monitor_app.telemetry.fingerprint import HardwareFingerprint

class BenchmarkSession:
    """
    Represents an immutable, folder-based benchmark run.
    Contains session configurations, system specs, and dedicated diagnostics logs.
    All disk logging is handled asynchronously via a background thread to prevent pipeline blocking.
    """
    def __init__(self, run_id: str, base_dir: str):
        self.run_id = run_id
        self.session_dir = os.path.join(base_dir, f"Session_{run_id}")
        os.makedirs(self.session_dir, exist_ok=True)
        
        self.benchmark_log_path = os.path.join(self.session_dir, "benchmark.log")
        self.telemetry_log_path = os.path.join(self.session_dir, "telemetry.log")
        self.events_log_path = os.path.join(self.session_dir, "events.log")
        self.errors_log_path = os.path.join(self.session_dir, "errors.log")
        
        self._init_logs()
        
        # Async Logger Thread Setup
        self.log_queue = queue.Queue()
        self.writer_running = True
        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.writer_thread.start()

    def _init_logs(self):
        # Create empty log files if they don't exist
        for path in [self.benchmark_log_path, self.telemetry_log_path, self.events_log_path, self.errors_log_path]:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("")

    def _writer_loop(self):
        while self.writer_running or not self.log_queue.empty():
            try:
                item = self.log_queue.get(timeout=0.1)
                if item is None:
                    break
                path, content = item
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
                self.log_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

    def stop_writer(self):
        """Signals the background log writer to stop and waits for completion."""
        self.writer_running = False
        self.log_queue.put(None)
        try:
            self.writer_thread.join(timeout=2.0)
        except Exception:
            pass

    def log_benchmark(self, severity: str, category: str, module: str, message: str):
        """Queue log line for benchmark.log."""
        t = time.strftime("%H:%M:%S", time.localtime())
        log_line = f"[{t}] {severity:<7} {category:<10} {module:<15} {message}\n"
        self.log_queue.put((self.benchmark_log_path, log_line))

    def log_telemetry(self, timestamp: float, metrics: dict):
        """Queue telemetry state as JSON line."""
        log_entry = {"timestamp": timestamp, "metrics": metrics}
        self.log_queue.put((self.telemetry_log_path, json.dumps(log_entry) + "\n"))

    def log_event(self, timestamp: float, event_type: str, camera_id: str, confidence: float, latency_ms: float, message: str, payload: dict = None):
        """Queue AI event as JSON line, with optional extended payload (YOLO boxes/MoveNet keypoints)."""
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "camera_id": camera_id,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "message": message
        }
        if payload is not None:
            log_entry["payload"] = payload
        self.log_queue.put((self.events_log_path, json.dumps(log_entry) + "\n"))

    def log_error(self, timestamp: float, module: str, error_msg: str, traceback_str: str = ""):
        """Queue error details as JSON line."""
        log_entry = {
            "timestamp": timestamp,
            "module": module,
            "error": error_msg,
            "traceback": traceback_str
        }
        self.log_queue.put((self.errors_log_path, json.dumps(log_entry) + "\n"))


class BenchmarkSessionManager:
    """Manages the creation and retrieval of BenchmarkSession instances."""
    _instance: Optional['BenchmarkSessionManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BenchmarkSessionManager, cls).__new__(cls)
            from monitor_app.utils import data_path
            cls._instance.base_dir = data_path(os.path.join("runs", "benchmark_sessions"))
            os.makedirs(cls._instance.base_dir, exist_ok=True)
            cls._instance.active_session = None
        return cls._instance

    def create_session(self, operator_name: str, profile_name: str) -> BenchmarkSession:
        """Initializes a new benchmark session folder."""
        run_id = f"{int(time.time())}"
        session = BenchmarkSession(run_id, self.base_dir)
        
        # Write hardware manifest to session folder immediately
        hw_details = HardwareFingerprint.get_details()
        manifest = {
            "run_id": run_id,
            "hardware_hash": HardwareFingerprint.get_hash(),
            "operator": operator_name,
            "profile": profile_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **hw_details
        }
        
        manifest_path = os.path.join(session.session_dir, "hardware.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4)
            
        self.active_session = session
        session.log_benchmark("INFO", "BENCHMARK", "SessionManager", f"Created session {run_id} by {operator_name}")
        return session

    def get_active_session(self) -> Optional[BenchmarkSession]:
        return self.active_session

    def close_active_session(self):
        if self.active_session:
            self.active_session.log_benchmark("INFO", "BENCHMARK", "SessionManager", "Closing active benchmark session")
            self.active_session.stop_writer()
            
            # Write end_timestamp and duration to manifest
            manifest_path = os.path.join(self.active_session.session_dir, "hardware.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    manifest["end_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    # Calculate duration if start timestamp exists
                    start_str = manifest.get("timestamp", "")
                    if start_str:
                        try:
                            start_t = calendar.timegm(time.strptime(start_str, "%Y-%m-%dT%H:%M:%SZ"))
                            end_t = time.time()
                            manifest["duration_seconds"] = round(end_t - start_t, 1)
                        except Exception:
                            pass
                    with open(manifest_path, "w", encoding="utf-8") as f:
                        json.dump(manifest, f, indent=4)
                except Exception:
                    pass
            
            self.active_session = None

_session_manager = BenchmarkSessionManager()

def get_session_manager() -> BenchmarkSessionManager:
    return _session_manager
