import threading
import time
from enum import Enum
from monitor_app.logger import get_module_logger
from monitor_app.config import get_config

logger = get_module_logger("Health Monitor")

class ComponentState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"

class HealthMonitor:
    """
    Lightweight Observational Watchdog.
    Periodically checks the states of registered components.
    Does NOT control or restart components. Only logs warnings if a component fails.
    """
    def __init__(self):
        self.components = {}
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self.check_interval = get_config("health_monitor", "check_interval", 10.0)
        self.thread = None

    def register_component(self, name, get_state_callback):
        """
        Registers a component to be monitored.
        `get_state_callback` should be a function that returns a ComponentState enum.
        """
        with self.lock:
            self.components[name] = get_state_callback

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self._stop_event.clear()
            self.thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self.thread.start()
            logger.info("Health Monitor STARTED")

    def stop(self):
        self._stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
            logger.info("Health Monitor STOPPED")

    def _watchdog_loop(self):
        while not self._stop_event.is_set():
            time.sleep(self.check_interval)
            
            with self.lock:
                for name, get_state_callback in self.components.items():
                    try:
                        state = get_state_callback()
                        if state == ComponentState.FAILED:
                            logger.warning(f"Component '{name}' reported FAILED state!")
                        elif state == ComponentState.RECOVERING:
                            logger.info(f"Component '{name}' is RECOVERING.")
                        # IDLE, RUNNING, WAITING are normal and don't spam logs
                    except Exception as e:
                        logger.error(f"Error checking health for '{name}': {e}")

# Global singleton
_global_health_monitor = HealthMonitor()

def get_health_monitor() -> HealthMonitor:
    return _global_health_monitor
