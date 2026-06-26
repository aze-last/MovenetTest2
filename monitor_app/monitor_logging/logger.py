import os
import logging
import logging.handlers
import sys
from monitor_app.config import get_config
from monitor_app.monitor_logging.formatter import CellWatchFormatter

_global_logger = None

def setup_logging():
    global _global_logger
    if _global_logger is not None:
        return _global_logger
        
    logger = logging.getLogger("CellWatch")
    logger.handlers.clear()
    
    # Read config
    level_str = get_config("logging", "level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)
    
    console_enabled = get_config("logging", "console", True)
    file_enabled = get_config("logging", "file", True)
    keep_days = int(get_config("logging", "keep_days", 30))
    
    formatter = CellWatchFormatter()
    
    if console_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    if file_enabled:
        # Save logs folder inside the project workspace
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "cellwatch.log")
        
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=keep_days,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    logger.propagate = False
    _global_logger = logger
    return logger

def get_logger(name="CellWatch"):
    return setup_logging()

def get_module_logger(component_name):
    base_logger = get_logger()
    return ComponentLogger(base_logger, component_name)

class ComponentLogger:
    def __init__(self, logger, component):
        self.logger = logger
        self.component = component

    def _log(self, level, msg, camera_id="-", incident_id="-", **kwargs):
        extra = {"component": self.component, "camera_id": camera_id, "incident_id": incident_id}
        if "extra" in kwargs:
            kwargs["extra"].update(extra)
        else:
            kwargs["extra"] = extra
        self.logger.log(level, msg, **kwargs)

    def debug(self, msg, camera_id="-", incident_id="-", **kwargs):
        self._log(logging.DEBUG, msg, camera_id, incident_id, **kwargs)

    def info(self, msg, camera_id="-", incident_id="-", **kwargs):
        self._log(logging.INFO, msg, camera_id, incident_id, **kwargs)

    def warning(self, msg, camera_id="-", incident_id="-", **kwargs):
        self._log(logging.WARNING, msg, camera_id, incident_id, **kwargs)

    def error(self, msg, camera_id="-", incident_id="-", **kwargs):
        self._log(logging.ERROR, msg, camera_id, incident_id, **kwargs)
        
    def critical(self, msg, camera_id="-", incident_id="-", **kwargs):
        self._log(logging.CRITICAL, msg, camera_id, incident_id, **kwargs)
