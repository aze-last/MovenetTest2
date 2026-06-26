import threading
from typing import Callable, Dict, List

class EventBus:
    """
    Lightweight Event Bus for loose coupling.
    Modules publish and subscribe to events (e.g. 'DECISION_TRIGGER', 'INCIDENT_START').
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.lock = threading.Lock()

    def subscribe(self, event_name: str, callback: Callable):
        with self.lock:
            if event_name not in self.subscribers:
                self.subscribers[event_name] = []
            if callback not in self.subscribers[event_name]:
                self.subscribers[event_name].append(callback)

    def publish(self, event_name: str, *args, **kwargs):
        with self.lock:
            callbacks = self.subscribers.get(event_name, []).copy()
        
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                from monitor_app.logger import get_module_logger
                logger = get_module_logger("EventBus")
                logger.error(f"Error executing callback for event '{event_type}': {e}")

_global_event_bus = EventBus()

def get_event_bus() -> EventBus:
    return _global_event_bus
