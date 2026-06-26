import time
import threading
import psutil
from monitor_app.monitor_logging.logger import get_module_logger

# Try to import torch for VRAM
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = get_module_logger("Performance")

class PerformanceMonitor:
    """
    Periodically collects and logs system performance metrics.
    Emits a snapshot every 30-60 seconds.
    """
    def __init__(self, interval_seconds: float = 30.0):
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # Metrics tracking
        self.start_time = time.time()
        self.processed_frames = 0
        self.dropped_frames = 0
        self.latency_sum = 0.0
        self.latency_count = 0
        
    def track_frame(self, latency_seconds: float):
        with self.lock:
            self.processed_frames += 1
            self.latency_sum += latency_seconds
            self.latency_count += 1
            
    def track_dropped_frame(self):
        with self.lock:
            self.dropped_frames += 1
            
    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.start_time = time.time()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info("Performance Monitor STARTED")
            
    def stop(self):
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
            logger.info("Performance Monitor STOPPED")
            
    def _run_loop(self):
        last_time = time.time()
        last_frames = 0
        last_dropped = 0
        
        while True:
            # Sleep in small increments to respond quickly to stop signal
            for _ in range(int(self.interval)):
                with self.lock:
                    if not self.running:
                        return
                time.sleep(1.0)
                
            now = time.time()
            dt = now - last_time
            if dt <= 0:
                continue
                
            with self.lock:
                frames_done = self.processed_frames
                dropped_done = self.dropped_frames
                latencies_sum = self.latency_sum
                latencies_count = self.latency_count
                
                # Reset latency counters for the next window
                self.latency_sum = 0.0
                self.latency_count = 0
                
            # Calculations
            fps = (frames_done - last_frames) / dt
            dropped_fps = (dropped_done - last_dropped) / dt
            avg_latency_ms = (latencies_sum / latencies_count * 1000.0) if latencies_count > 0 else 0.0
            
            last_time = now
            last_frames = frames_done
            last_dropped = dropped_done
            
            # System stats
            cpu_pct = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            ram_used_gb = ram.used / (1024 ** 3)
            
            # GPU stats
            vram_used_gb = 0.0
            if TORCH_AVAILABLE and torch.cuda.is_available():
                vram_used_gb = torch.cuda.memory_allocated(0) / (1024 ** 3)
                
            # Uptime
            uptime_sec = int(now - self.start_time)
            hours, remainder = divmod(uptime_sec, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Log Snapshot
            msg = (
                "\n"
                "================================================\n"
                "CELLWATCH PERFORMANCE SNAPSHOT\n"
                "================================================\n"
                f"FPS................{fps:.1f}\n"
                f"Dropped FPS........{dropped_fps:.1f}\n"
                f"Inference Latency..{avg_latency_ms:.1f} ms\n"
                f"RAM................{ram_used_gb:.1f} GB / {ram.total / (1024**3):.1f} GB\n"
                f"VRAM...............{vram_used_gb:.1f} GB\n"
                f"CPU................{cpu_pct:.1f}%\n"
                f"Uptime.............{uptime_str}\n"
                "================================================"
            )
            print(msg)
            logger.info("Consolidated performance snapshot logged successfully.")

# Global singleton
_performance_monitor = PerformanceMonitor()

def get_performance_monitor() -> PerformanceMonitor:
    return _performance_monitor
