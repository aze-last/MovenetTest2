from .log_router import LogRouter
import logging

class OfflineLogger:
    """
    Interface for logging events during offline analysis.
    Ensures logs do not pollute the live monitoring console and are strictly routed 
    into the session export directory.
    """
    def __init__(self, export_dir):
        self.router = LogRouter(export_dir)

    def _log(self, level, category, component, message, reference_id=""):
        logger = self.router.get_logger(category)
        extra = {
            "category": category,
            "component": component,
            "reference_id": reference_id
        }
        logger.log(level, message, extra=extra)

    def info(self, category, component, message, reference_id=""):
        self._log(logging.INFO, category, component, message, reference_id)

    def warning(self, category, component, message, reference_id=""):
        self._log(logging.WARNING, category, component, message, reference_id)

    def error(self, category, component, message, reference_id=""):
        self._log(logging.ERROR, category, component, message, reference_id)

    def debug(self, category, component, message, reference_id=""):
        self._log(logging.DEBUG, category, component, message, reference_id)
