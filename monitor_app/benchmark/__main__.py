import sys
import os
import time
import threading
from enum import Enum
import numpy as np

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from monitor_app.evidence import EvidencePacket
from monitor_app.central_inference import get_inference_manager
from monitor_app.telemetry import get_telemetry_engine, camera_collector, ai_collector, system_collector, queue_collector, health_collector
from monitor_app.telemetry.hardware_profiler import HardwareProfiler
from monitor_app.benchmark.db import BenchmarkDBManager
from monitor_app.benchmark.benchmark_exporter import ResultExporter
from monitor_app.utils import GlobalState

class BenchmarkState(Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class BenchmarkProfile(Enum):
    QUICK = ("quick", 30.0)
    BASELINE = ("baseline", 300.0)
    LOAD = ("load", 1800.0)
    ENDURANCE = ("endurance", 28800.0)
    
    def __init__(self, profile_name: str, duration_sec: float):
        self.profile_name = profile_name
        self.duration_sec = duration_sec

class CellWatchBenchmark:
    """
    Orchestrates system benchmarks, performance scoring, baseline comparisons,
    and exports reproducible performance report bundles.
    """
    def __init__(self):
        self.state = BenchmarkState.IDLE
        self.db = BenchmarkDBManager()
        self.exporter = ResultExporter()
        self._running_thread = None

    def run_profile(self, profile: BenchmarkProfile = BenchmarkProfile.QUICK, num_simulated_cams: int = 4):
        print(f"=== CELLWATCH AI PERFORMANCE BENCHMARK ===")
        print(f"Profile: {profile.name} | Target duration: {profile.duration_sec} seconds")
        print(f"Simulating {num_simulated_cams} camera feeds...")
        
        self.state = BenchmarkState.STARTING
        
        from monitor_app.config import load_config
        cfg = load_config()
        
        # === Benchmark Configuration Lock ===
        frozen_config = {
            "camera_count": num_simulated_cams,
            "profile": profile.profile_name,
            "yolo_model": cfg.get("yolo_model_path", "yolov8n.pt").split('/')[-1],
            "movenet_model": cfg.get("movenet_model", "movenet_lightning"),
            "target_fps": cfg.get("target_fps", 15),
            "resolution": "640x480",
            "config_yaml_hash": HardwareProfiler.get_profile().get("config_yaml_hash", "N/A"),
        }
        GlobalState.lock_benchmark(frozen_config)
        print("[LOCK] Benchmark Configuration Lock ACTIVE. Settings frozen.")
        
        # Warmup and initialize Inference Manager
        manager = get_inference_manager()
        manager.start()
        
        # Wait for engines to initialize in worker thread
        print("Waiting for central inference manager engine to initialize...")
        for _ in range(45):
            if manager.engine is not None:
                break
            time.sleep(1.0)
            
        if manager.engine is None:
            print("Warning: Engine failed to initialize in time.")
            self.state = BenchmarkState.FAILED
            GlobalState.unlock_benchmark()
            print("[LOCK] Benchmark Configuration Lock RELEASED (failed init).")
            return
            
        print("Warming up CUDA context (3 seconds)...")
        time.sleep(3.0)
        
        self.state = BenchmarkState.RUNNING
        
        # Start Telemetry Engine
        engine = get_telemetry_engine()
        engine.start()
        
        # Reset collector caches
        camera_collector.clear()
        ai_collector.clear()
        system_collector.clear()
        queue_collector.clear()
        health_collector.clear()

        # Start Active Benchmark Session
        from monitor_app.benchmark.session_manager import get_session_manager
        get_session_manager().create_session("Validation Center", profile.profile_name)

        # Collect system time-series timeline in main thread
        timeline = []
        start_time = time.time()
        
        # Telemetry levels check: System tick event triggers resource collection
        from monitor_app.events import get_event_bus, TELEM_SYSTEM_TICK, TELEM_QUEUE_TICK
        
        while time.time() - start_time < profile.duration_sec:
            # Emit ticks
            get_event_bus().publish(TELEM_SYSTEM_TICK, TELEM_SYSTEM_TICK, {})
            get_event_bus().publish(TELEM_QUEUE_TICK, TELEM_QUEUE_TICK, {"queue_size": manager.task_queue.qsize()})
            
            # Read stats
            sys_metrics = system_collector.get_stats()
            queue_metrics = queue_collector.get_stats()
            ai_metrics = ai_collector.get_stats()
            
            # Combine current slice
            slice_data = {
                "timestamp": time.time(),
                "cpu_percent": sys_metrics.get("cpu_percent", 0.0),
                "ram_used_gb": sys_metrics.get("ram_used_gb", 0.0),
                "vram_allocated_mb": sys_metrics.get("vram_allocated_mb", 0.0),
                "gpu_temp": sys_metrics.get("gpu_temp", 0.0),
                "gpu_clock_mhz": sys_metrics.get("gpu_clock_mhz", 0.0),
                "cpu_clock_mhz": sys_metrics.get("cpu_clock_mhz", 0.0),
                "queue_size": queue_metrics.get("current_queue_size", 0),
                "p95_latency_ms": ai_metrics.get("movenet", {}).get("p95", 0.0) + ai_metrics.get("yolo", {}).get("p95", 0.0)
            }
            timeline.append(slice_data)
            time.sleep(1.0)
            
        self.state = BenchmarkState.STOPPING
        
        # Close Active Session (stops async writer thread)
        get_session_manager().close_active_session()
        
        # 1. Collect aggregated results
        cam_stats = camera_collector.get_stats()
        ai_stats = ai_collector.get_stats()
        health_stats = health_collector.get_stats()
        
        failures = health_stats.get("failures", {})
        
        # Calculate performance score (0-100)
        score, verdict, recs = self._calculate_scores(cam_stats, ai_stats, health_stats, timeline)
        
        # 2. Build hardware manifest
        manifest = {
            "run_id": f"run_{int(time.time())}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "versions": {
                "telemetry_schema_version": "1.0",
                "pipeline_version": "2.1",
                "behavior_module_version": "1.4",
                "config_version": "1.0"
            },
            "environment": {
                "os": HardwareProfiler.get_profile().get("os"),
                "python": HardwareProfiler.get_profile().get("python"),
                "cuda": HardwareProfiler.get_profile().get("cuda"),
                "torch": HardwareProfiler.get_profile().get("torch"),
                "tensorflow": HardwareProfiler.get_profile().get("tensorflow")
            },
            "hardware": {
                "host_name": HardwareProfiler.get_profile().get("host_name"),
                "cpu": HardwareProfiler.get_profile().get("cpu"),
                "gpu": HardwareProfiler.get_profile().get("gpu"),
                "ram_total_gb": HardwareProfiler.get_profile().get("ram_total_gb")
            },
            "settings": {
                "operator_profile": profile.profile_name,
                "camera_count": len(cam_stats.keys()) if cam_stats else 1,
                "camera_resolution": "640x480",
                "target_fps": cfg.get("target_fps", 15),
                "yolo_model": cfg.get("yolo_model_path", "yolov8n.pt").split('/')[-1],
                "movenet_model": cfg.get("movenet_model", "movenet_lightning")
            },
            "git_commit": HardwareProfiler.get_profile().get("git_commit"),
            "config_yaml_hash": HardwareProfiler.get_profile().get("config_yaml_hash"),
            "hardware_hash": HardwareProfiler.get_profile().get("hardware_hash"),
            "p95_latency": round(ai_stats.get("yolo", {}).get("p95", 0.0) + ai_stats.get("movenet", {}).get("p95", 0.0), 1),
            "avg_fps": round(sum(stats.get("fps", 0.0) for stats in cam_stats.values()) / len(cam_stats.keys()), 1) if cam_stats else 0.0
        }
        
        # 3. Decoupled baseline comparison (done in UI instead)
        comp_report = None

        # 4. Save to Database
        self.db.save_run(manifest, timeline, score)
        
        # 5. Save report bundle
        bundle_path = self.exporter.export_bundle(
            manifest, timeline, ai_stats, cam_stats, failures, verdict, score, recs, comp_report
        )
        
        self.state = BenchmarkState.COMPLETED
        GlobalState.unlock_benchmark()
        print("[LOCK] Benchmark Configuration Lock RELEASED.")
        print(f"Benchmark run completed! Bundle saved to: {bundle_path}")
        print(f"Overall Score: {score}/100 | Verdict: {verdict}")

    def _calculate_scores(self, cam_stats: dict, ai_stats: dict, health_stats: dict, timeline: list) -> tuple:
        """Computes score, determines PASS/WARNING/FAIL, and generates recommendations."""
        recs = []
        
        # 1. FPS Score
        fps_ratios = []
        for cam_id, stats in cam_stats.items():
            fps = stats.get("fps", 0.0)
            fps_ratios.append(min(1.0, fps / 15.0))
        fps_score = (sum(fps_ratios) / len(fps_ratios) * 100.0) if fps_ratios else 0.0
        
        # 2. Latency Score (P95)
        # Total latency = sum of P95 of MoveNet and YOLO
        yolo_p95 = ai_stats.get("yolo", {}).get("p95", 0.0)
        movenet_p95 = ai_stats.get("movenet", {}).get("p95", 0.0)
        total_p95 = yolo_p95 + movenet_p95
        
        if total_p95 <= 80.0:
            latency_score = 100.0
        elif total_p95 >= 150.0:
            latency_score = 0.0
        else:
            # Interpolate
            latency_score = 100.0 - ((total_p95 - 80.0) / 70.0 * 100.0)
            
        # 3. Drops Score
        total_drops = sum(stats.get("dropped_frames", 0) for stats in cam_stats.values())
        drops_pct = (total_drops / 5000.0) * 100.0  # approximate scale
        drops_score = max(0.0, 100.0 - (drops_pct * 20.0))  # 5% drops = 0 score
        
        # 4. Failures Penalty
        failures = health_stats.get("failures", {})
        reconnects = failures.get("camera_reconnects", 0)
        crashes = failures.get("inference_failures", 0)
        fails_penalty = min(100.0, (reconnects * 10) + (crashes * 30))
        failures_score = max(0.0, 100.0 - fails_penalty)
        
        # Weighting: 30% FPS, 30% Latency, 20% Drops, 20% Failures
        score = (fps_score * 0.3) + (latency_score * 0.3) + (drops_score * 0.2) + (failures_score * 0.2)
        score = round(score, 1)
        
        # Diagnostic Recommendation Engine
        cpu_usage = [r["cpu_percent"] for r in timeline]
        avg_cpu = sum(cpu_usage) / len(cpu_usage) if cpu_usage else 0.0
        
        gpu_temps = [r["gpu_temp"] for r in timeline]
        max_gpu_temp = max(gpu_temps) if gpu_temps else 0.0
        
        if avg_cpu > 90.0:
            recs.append("CPU execution Saturated. Recommend offloading MoveNet parsing to custom GPU filters or reducing target camera streams.")
        if max_gpu_temp > 82.0:
            recs.append("GPU thermal throttling risk. GPU reached peak temperature of {}°C. Ensure cooling is active or throttle FPS.".format(max_gpu_temp))
        if total_p95 > 130.0:
            recs.append("High pipeline latency detected (P95: {}ms). Recommended: Decrease YOLO resolution or use the MoveNet lightning model.".format(round(total_p95, 1)))
        if health_stats.get("memory_leak_slope_mb_min", 0.0) > 1.0:
            recs.append("Significant RAM heap growth detected ({} MB/min). Investigate memory references or release cv2 handles.".format(health_stats.get("memory_leak_slope_mb_min")))
        if reconnects > 0:
            recs.append("Camera network instabilities detected. {} reconnect triggers logged.".format(reconnects))
            
        if not recs:
            recs.append("System execution is highly optimized. No resource anomalies detected.")
            
        # PASS/WARNING/FAIL Verdict
        if score >= 85.0 and total_p95 < 100.0 and reconnects == 0:
            verdict = "PASS"
        elif score >= 60.0 and total_p95 < 140.0:
            verdict = "WARNING"
        else:
            verdict = "FAIL"
            
        return score, verdict, recs


if __name__ == "__main__":
    benchmark = CellWatchBenchmark()
    
    # Defaults to Quick (30s) benchmark
    profile = BenchmarkProfile.QUICK
    if len(sys.argv) > 1:
        prof_arg = sys.argv[1].lower()
        if prof_arg == "baseline":
            profile = BenchmarkProfile.BASELINE
        elif prof_arg == "load":
            profile = BenchmarkProfile.LOAD
        elif prof_arg == "endurance":
            profile = BenchmarkProfile.ENDURANCE
            
    benchmark.run_profile(profile)
