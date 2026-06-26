import threading
from typing import Dict, Any, List

class AlertManager:
    """
    Central hub that takes decisions and triggers alerts/recordings on registered recorders.
    Decoupled action layer executing directives from the DecisionEngine.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.recorders: Dict[str, Any] = {}

    def register_recorder(self, camera_id: str, recorder: Any):
        with self.lock:
            self.recorders[str(camera_id)] = recorder

    def unregister_recorder(self, camera_id: str):
        with self.lock:
            self.recorders.pop(str(camera_id), None)

    def trigger_alert(self, camera_id: str, event_type: str, confidence_scores: List[float], frame: Any, ai_results: dict):
        """Command the camera's recorder to start recording evidence."""
        with self.lock:
            recorder = self.recorders.get(str(camera_id))
            if recorder:
                recorder.trigger_recording(event_type, confidence_scores, frame, ai_results)

    def stop_alert(self, camera_id: str):
        """Command the camera's recorder to stop recording and transition to cooldown."""
        with self.lock:
            recorder = self.recorders.get(str(camera_id))
            if recorder:
                recorder.stop_recording()

# Global Alert Manager Singleton
_global_alert_manager = AlertManager()

def get_alert_manager() -> AlertManager:
    return _global_alert_manager
