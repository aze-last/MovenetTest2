import os
import yaml
from monitor_app.utils import resource_path

CONFIG_PATH = resource_path("config.yaml")

_config_cache = None

def load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    
    if not os.path.exists(CONFIG_PATH):
        # Fallback defaults if file missing
        _config_cache = {
            "logging": {"level": "INFO"},
            "alert_cooldowns": {"default": 25.0, "fight": 30.0, "knife": 60.0, "cellphone": 30.0},
            "motion_gate": {"enable_delay": 0.5, "disable_delay": 3.0, "minimum_active_duration": 1.0},
            "camera_reconnect": {"initial_backoff": 1.0, "max_backoff": 60.0, "factor": 2.0},
            "incident_merging": {"merge_window": 10.0},
            "health_monitor": {"check_interval": 10.0},
            "yolo": {"model_path": "best.pt", "inference_imgsz": 960}
        }
        return _config_cache

    try:
        with open(CONFIG_PATH, "r") as f:
            _config_cache = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config.yaml: {e}. Using defaults.")
        _config_cache = {
            "logging": {"level": "INFO"},
            "alert_cooldowns": {"default": 25.0, "fight": 30.0, "knife": 60.0, "cellphone": 30.0},
            "motion_gate": {"enable_delay": 0.5, "disable_delay": 3.0, "minimum_active_duration": 1.0},
            "camera_reconnect": {"initial_backoff": 1.0, "max_backoff": 60.0, "factor": 2.0},
            "incident_merging": {"merge_window": 10.0},
            "health_monitor": {"check_interval": 10.0},
            "yolo": {"model_path": "best.pt", "inference_imgsz": 960}
        }
    return _config_cache

def get_config(section, key=None, default=None):
    cfg = load_config()
    sec = cfg.get(section, {})
    if key is None:
        return sec
    return sec.get(key, default)


def get_concealment_config(key=None, default=None):
    """Return concealment engineering config from config.yaml."""
    cfg = load_config()
    concealment = cfg.get("concealment", {}) or {}
    if key is None:
        return concealment
    return concealment.get(key, default)

def save_developer_config(updates):
    global _config_cache
    cfg = load_config()
    
    # Safe legacy migration / backward compatibility
    if "yolo" not in cfg:
        cfg["yolo"] = {}
    if "motion_gate" not in cfg:
        cfg["motion_gate"] = {}
        
    # Apply updates
    if "inference_imgsz" in updates:
        cfg["yolo"]["inference_imgsz"] = updates["inference_imgsz"]
    if "motion_gate_movenet_enabled" in updates:
        cfg["motion_gate"]["motion_gate_movenet_enabled"] = updates["motion_gate_movenet_enabled"]
    if "motion_gate_yolo_enabled" in updates:
        cfg["motion_gate"]["motion_gate_yolo_enabled"] = updates["motion_gate_yolo_enabled"]
        
    _config_cache = cfg
    
    try:
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        return True
    except Exception as e:
        print(f"Error saving config.yaml: {e}")
        return False
