import os
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

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
            "health_monitor": {"check_interval": 10.0}
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
            "health_monitor": {"check_interval": 10.0}
        }
    return _config_cache

def get_config(section, key=None, default=None):
    cfg = load_config()
    sec = cfg.get(section, {})
    if key is None:
        return sec
    return sec.get(key, default)
