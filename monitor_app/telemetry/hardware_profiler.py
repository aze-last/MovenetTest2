import hashlib
import os
import platform
import subprocess
import psutil
from typing import Dict, Optional

class HardwareProfiler:
    """
    Gathers detailed machine profile, runtime dependency versions, OS environment,
    git commit hashes, and config file signatures for benchmark reproducibility.
    """
    @staticmethod
    def get_profile(config_path: Optional[str] = None) -> dict:
        from monitor_app.telemetry.fingerprint import HardwareFingerprint
        profile = {
            "host_name": platform.node(),
            "os": f"{platform.system()} {platform.release()} {platform.win32_ver()[1] if platform.system() == 'Windows' else ''}".strip(),
            "python": platform.python_version(),
            "cpu": platform.processor() or "Unknown CPU",
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
            "gpu": "Unknown / CPU Only",
            "cuda": "N/A",
            "torch": "N/A",
            "tensorflow": "N/A",
            "git_commit": "N/A",
            "config_yaml_hash": "N/A",
            "hardware_hash": HardwareFingerprint.get_hash()
        }
        
        # 1. Dependency versions & GPU details
        try:
            import torch
            if torch.cuda.is_available():
                profile["gpu"] = torch.cuda.get_device_name(0)
                profile["cuda"] = torch.version.cuda or "Available"
            profile["torch"] = torch.__version__
        except ImportError:
            pass

        try:
            import tensorflow as tf
            profile["tensorflow"] = tf.__version__
        except ImportError:
            pass

        # 2. Get CPU Name (Windows WMI fallback)
        if platform.system() == "Windows" and profile["cpu"] in ("", "Unknown CPU"):
            try:
                cmd = ["wmic", "cpu", "get", "name"]
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                out = subprocess.check_output(cmd, startupinfo=startupinfo).decode().strip()
                lines = [l.strip() for l in out.split("\n") if l.strip()]
                if len(lines) > 1:
                    profile["cpu"] = lines[1]
            except Exception:
                pass

        # 3. Get Git commit hash
        try:
            cmd = ["git", "rev-parse", "HEAD"]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            out = subprocess.check_output(cmd, timeout=0.5, startupinfo=startupinfo).decode().strip()
            if out:
                profile["git_commit"] = out
        except Exception:
            pass

        # 4. Hash config.yaml
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config.yaml")
            
        if os.path.exists(config_path):
            try:
                with open(config_path, "rb") as f:
                    content = f.read()
                    profile["config_yaml_hash"] = hashlib.sha256(content).hexdigest()
            except Exception:
                pass

        return profile
