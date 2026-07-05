import os
import logging
from .structured_logger import StructuredFormatter

class LogRouter:
    def __init__(self, export_dir):
        self.export_dir = export_dir
        self.logs_dir = os.path.join(export_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.loggers = {}
        
        # Route categories to specific files
        self.routes = {
            "SYSTEM": "system.log",
            "CAMERA": "system.log", 
            "AI": "ai.log",
            "YOLO": "yolo.log",
            "MoveNet": "movenet.log",
            "Behavior": "events.log",
            "Decision Engine": "events.log",
            "Telemetry": "telemetry.log",
            "Benchmark": "benchmark.log"
        }
        self.formatter = StructuredFormatter()

    def get_logger(self, category):
        if category not in self.loggers:
            filename = self.routes.get(category, "events.log")
            filepath = os.path.join(self.logs_dir, filename)
            
            logger = logging.getLogger(f"offline_{self.export_dir}_{category}")
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            
            # Remove old handlers to prevent duplicates if instantiated multiple times
            if logger.hasHandlers():
                logger.handlers.clear()
                
            fh = logging.FileHandler(filepath)
            fh.setFormatter(self.formatter)
            logger.addHandler(fh)
            
            self.loggers[category] = logger
            
        return self.loggers[category]
