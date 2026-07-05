import collections
import os
import subprocess
import threading
import time
import psutil
from typing import Dict, Optional

# Try to import torch for VRAM
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

class SystemCollector:
    """
    Tracks system performance and thermals: CPU percent, RAM, VRAM,
    and CPU/GPU temperatures and clock speeds.
    Enforces a strict 500-sample ring buffer (sampled every 1.0s or 5.0s).
    """
    def __init__(self, max_samples: int = 500, max_duration_sec: float = 300.0):
        self.max_samples = max_samples
        self.max_duration_sec = max_duration_sec
        self.lock = threading.Lock()
        
        # Deque of (timestamp, system_metrics)
        self.history = collections.deque(maxlen=max_samples)
        
        # Register metrics dynamically
        from monitor_app.telemetry.registry import get_registry
        reg = get_registry()
        reg.register_metric("cpu_percent", "CPU Usage", "%", "system")
        reg.register_metric("ram_used_gb", "RAM Used", "GB", "system")
        reg.register_metric("ram_total_gb", "RAM Total", "GB", "system")
        reg.register_metric("vram_allocated_mb", "VRAM Allocated", "MB", "system")
        reg.register_metric("vram_reserved_mb", "VRAM Reserved", "MB", "system")
        reg.register_metric("cpu_clock_mhz", "CPU Clock Speed", "MHz", "system")
        reg.register_metric("gpu_clock_mhz", "GPU Clock Speed", "MHz", "system")
        reg.register_metric("cpu_temp", "CPU Temperature", "°C", "system")
        reg.register_metric("gpu_temp", "GPU Temperature", "°C", "system")
        
        # Cached values to prevent frequent slow syscalls
        self.last_thermal_time = 0.0
        self.cached_thermals = {
            "cpu_temp": 0.0,
            "gpu_temp": 0.0,
            "gpu_clock_mhz": 0.0,
            "cpu_clock_mhz": 0.0
        }

    def on_event(self, event_name: str, payload: dict):
        # We only ingest metrics on the system tick event
        if event_name != "TELEM_SYSTEM_TICK":
            return
            
        now = time.time()
        
        # Basic stats (cheap to query)
        cpu_pct = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        ram_used = ram.used / (1024 ** 3)
        ram_total = ram.total / (1024 ** 3)
        
        # VRAM (cheap if PyTorch is available)
        vram_allocated_mb = 0.0
        vram_reserved_mb = 0.0
        if TORCH_AVAILABLE and torch.cuda.is_available():
            try:
                vram_allocated_mb = torch.cuda.memory_allocated(0) / (1024 * 1024)
                vram_reserved_mb = torch.cuda.memory_reserved(0) / (1024 * 1024)
            except Exception:
                pass
                
        # Thermals & Clocks (throttle check - sample every 5s)
        thermals = self._query_thermals_cached(now)
        
        metrics = {
            "cpu_percent": cpu_pct,
            "ram_used_gb": round(ram_used, 2),
            "ram_total_gb": round(ram_total, 2),
            "vram_allocated_mb": round(vram_allocated_mb, 2),
            "vram_reserved_mb": round(vram_reserved_mb, 2),
            **thermals
        }
        
        with self.lock:
            self.history.append((now, metrics))

    def _query_thermals_cached(self, now: float) -> dict:
        """Throttles thermal calls to once every 5 seconds."""
        if now - self.last_thermal_time < 5.0:
            return self.cached_thermals.copy()
            
        self.last_thermal_time = now
        
        # 1. CPU Clock Speed
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            self.cached_thermals["cpu_clock_mhz"] = round(cpu_freq.current, 1)
            
        # 2. GPU Thermals & Clocks (nvidia-smi)
        gpu_stats = self._query_nvidia_smi()
        self.cached_thermals["gpu_temp"] = gpu_stats.get("gpu_temp", 0.0)
        self.cached_thermals["gpu_clock_mhz"] = gpu_stats.get("gpu_clock_mhz", 0.0)
        
        # 3. CPU Temperature
        self.cached_thermals["cpu_temp"] = self._query_cpu_temp()
        
        return self.cached_thermals.copy()

    def _query_nvidia_smi(self) -> dict:
        """Safely invokes nvidia-smi with a strict timeout."""
        res = {"gpu_temp": 0.0, "gpu_clock_mhz": 0.0}
        try:
            # Query temperature and graphics clock
            cmd = ["nvidia-smi", "--query-gpu=temperature.gpu,clocks.current.graphics", "--format=csv,noheader,nounits"]
            # Start process without creating a window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5, startupinfo=startupinfo)
            if proc.returncode == 0:
                output = proc.stdout.decode("utf-8").strip()
                parts = output.split(",")
                if len(parts) >= 2:
                    res["gpu_temp"] = float(parts[0].strip())
                    res["gpu_clock_mhz"] = float(parts[1].strip())
        except Exception:
            pass  # Fallback to 0.0 if nvidia-smi is not found or fails
        return res

    def _query_cpu_temp(self) -> float:
        """Attempts to read CPU temperature (OS-specific)."""
        # Linux fallback
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if "coretemp" in temps:
                    return temps["coretemp"][0].current
                elif temps:
                    # Return first available temp sensor
                    first_sensor = list(temps.values())[0]
                    if first_sensor:
                        return first_sensor[0].current
            except Exception:
                pass
                
        # Windows fallback (WMI query via PowerShell command - very throttled to avoid speed issues)
        if os.name == 'nt':
            try:
                # WMI query for temperature (requires admin privileges, so it will often fail gracefully)
                # Keep it safe by using a simple command structure
                cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | Select-Object -ExpandProperty CurrentTemperature"]
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5, startupinfo=startupinfo)
                if proc.returncode == 0:
                    val = float(proc.stdout.decode("utf-8").strip())
                    # Convert tenths of Kelvin to Celsius
                    return round((val / 10.0) - 273.15, 1)
            except Exception:
                pass
                
        return 0.0

    def _prune_old_data(self, now: float):
        cutoff = now - self.max_duration_sec
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()

    def clear(self):
        with self.lock:
            self.history.clear()

    def get_stats(self) -> dict:
        now = time.time()
        with self.lock:
            self._prune_old_data(now)
            if not self.history:
                return {}
            # Return latest sample
            return self.history[-1][1].copy()

    def get_history(self) -> list:
        now = time.time()
        with self.lock:
            self._prune_old_data(now)
            return list(self.history)
