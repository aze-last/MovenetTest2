import hashlib
import os
import platform
import subprocess
import psutil
from typing import Dict

class HardwareFingerprint:
    """
    Retrieves detailed system specifications and creates a unique SHA-256 machine hash
    to link benchmark histories across identical physical units.
    """
    @staticmethod
    def get_details() -> dict:
        details = {
            "cpu": platform.processor() or "Unknown CPU",
            "gpu": "Unknown GPU",
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
            "os_platform": platform.platform(),
            "os_release": platform.release(),
            "motherboard_serial": "Unknown Motherboard",
            "bios_uuid": "Unknown BIOS"
        }
        
        # 1. Fetch GPU (nvidia-smi)
        try:
            cmd = ["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader,nounits"]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5, startupinfo=startupinfo)
            if proc.returncode == 0:
                details["gpu"] = proc.stdout.decode("utf-8").strip()
        except Exception:
            pass
            
        # 2. Motherboard Serial & BIOS UUID (Windows WMI)
        if os.name == 'nt':
            try:
                # Motherboard Serial
                cmd_mb = ["powershell", "-NoProfile", "-Command", "Get-CimInstance -ClassName Win32_BaseBoard | Select-Object -ExpandProperty SerialNumber"]
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                proc_mb = subprocess.run(cmd_mb, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5, startupinfo=startupinfo)
                if proc_mb.returncode == 0:
                    details["motherboard_serial"] = proc_mb.stdout.decode("utf-8").strip()
                
                # BIOS UUID
                cmd_bios = ["powershell", "-NoProfile", "-Command", "Get-CimInstance -ClassName Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID"]
                proc_bios = subprocess.run(cmd_bios, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5, startupinfo=startupinfo)
                if proc_bios.returncode == 0:
                    details["bios_uuid"] = proc_bios.stdout.decode("utf-8").strip()
            except Exception:
                pass
        else:
            # Linux fallbacks
            try:
                if os.path.exists("/sys/class/dmi/id/product_uuid"):
                    with open("/sys/class/dmi/id/product_uuid", "r") as f:
                        details["bios_uuid"] = f.read().strip()
                if os.path.exists("/sys/class/dmi/id/board_serial"):
                    with open("/sys/class/dmi/id/board_serial", "r") as f:
                        details["motherboard_serial"] = f.read().strip()
            except Exception:
                pass

        return details

    @classmethod
    def get_hash(cls) -> str:
        """Generates a reproducible SHA256 hardware hash from core details."""
        d = cls.get_details()
        # Sort and concatenate unique identifiers
        fingerprint_raw = f"{d['cpu']}|{d['gpu']}|{d['ram_total_gb']}|{d['motherboard_serial']}|{d['bios_uuid']}"
        return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()
