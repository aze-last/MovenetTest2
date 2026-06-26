import threading
import time
from enum import Enum
from monitor_app.logger import get_module_logger
from monitor_app.config import get_config
from monitor_app.events import get_event_bus
from monitor_app.health import ComponentState

logger = get_module_logger("Alert Manager")

class HysteresisState(Enum):
    NOT_SEEN = "NOT_SEEN"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    MAINTAINED = "MAINTAINED"
    COOLDOWN = "COOLDOWN"
    IDLE = "IDLE"

class IncidentState:
    """
    Camera-scoped state machine tracking a single contiguous incident.
    Accumulates evidence over time.
    """
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.state = HysteresisState.IDLE
        self.incident_id = "-"
        self.accumulated_evidence = set()
        self.first_detected = 0.0
        self.last_detected = 0.0
        self.cooldown_expiration = 0.0
        
        # Config params
        self.merge_window = get_config("incident_merging", "merge_window", 10.0)
        self.default_cooldown = get_config("alert_cooldowns", "default", 25.0)

    def update(self, event_type: str, confidence_scores: list, frame, ai_results: dict):
        now = time.time()
        self.last_detected = now
        
        # If IDLE or NOT_SEEN, start PENDING
        if self.state in (HysteresisState.IDLE, HysteresisState.NOT_SEEN):
            self.state = HysteresisState.PENDING
            self.first_detected = now
            self.accumulated_evidence = {event_type}
            logger.info(f"Motion/Event detected -> PENDING", camera_id=self.camera_id)
            # Short pending window to confirmed
            if now - self.first_detected >= 0.5: # Configurable pending window could be added
                self._confirm(event_type, frame, ai_results)
        
        elif self.state == HysteresisState.PENDING:
            self.accumulated_evidence.add(event_type)
            # After a short time, confirm the incident
            if now - self.first_detected >= 0.5:
                self._confirm(event_type, frame, ai_results)
                
        elif self.state in (HysteresisState.CONFIRMED, HysteresisState.MAINTAINED):
            self.state = HysteresisState.MAINTAINED
            if event_type not in self.accumulated_evidence:
                self.accumulated_evidence.add(event_type)
                logger.info(f"Evidence Added | Type: {event_type}", camera_id=self.camera_id, incident_id=self.incident_id)
                get_event_bus().publish(
                    "EVIDENCE_ADDED",
                    camera_id=self.camera_id,
                    incident_id=self.incident_id,
                    event_type=event_type,
                    confidence_scores=confidence_scores
                )
        
        elif self.state == HysteresisState.COOLDOWN:
            # If we see an event in cooldown within merge window, re-maintain it
            if now <= self.cooldown_expiration:
                self.state = HysteresisState.MAINTAINED
                if event_type not in self.accumulated_evidence:
                    self.accumulated_evidence.add(event_type)
                    logger.info(f"Evidence Added during COOLDOWN | Type: {event_type}", camera_id=self.camera_id, incident_id=self.incident_id)
                logger.info(f"Incident REOPENED from Cooldown", camera_id=self.camera_id, incident_id=self.incident_id)
                # Publish event to recorder to extend recording
                get_event_bus().publish("INCIDENT_EXTEND", self.camera_id, self.incident_id)
            else:
                # Cooldown expired, start new
                self.state = HysteresisState.PENDING
                self.first_detected = now
                self.accumulated_evidence = {event_type}

    def _confirm(self, event_type, frame, ai_results):
        from datetime import datetime
        self.state = HysteresisState.CONFIRMED
        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        self.incident_id = f"INC_{date_str}_{time_str}_{self.camera_id}"
        
        joined_evidence = " + ".join(list(self.accumulated_evidence))
        logger.info(f"Incident Created | Type: {joined_evidence}", camera_id=self.camera_id, incident_id=self.incident_id)
        
        # Publish Event to Recorder
        get_event_bus().publish(
            "INCIDENT_START", 
            camera_id=self.camera_id, 
            incident_id=self.incident_id, 
            event_type=joined_evidence, 
            frame=frame, 
            ai_results=ai_results
        )

    def tick(self):
        """Called periodically or per-frame to process timeouts"""
        now = time.time()
        
        if self.state in (HysteresisState.CONFIRMED, HysteresisState.MAINTAINED):
            # If no detection for a while, go to COOLDOWN
            if now - self.last_detected > self.merge_window:
                self.state = HysteresisState.COOLDOWN
                self.cooldown_expiration = now + self.default_cooldown
                duration = int(now - self.first_detected)
                logger.info(f"Incident Closed (Entering Cooldown) | Duration: {duration} seconds", camera_id=self.camera_id, incident_id=self.incident_id)
                get_event_bus().publish("INCIDENT_STOP", camera_id=self.camera_id, incident_id=self.incident_id)
                
        elif self.state == HysteresisState.PENDING:
            # If no detection for a while, go back to IDLE
            if now - self.last_detected > self.merge_window:
                self.state = HysteresisState.IDLE
                self.accumulated_evidence.clear()
                logger.info(f"Pending timeout -> IDLE", camera_id=self.camera_id)

        elif self.state == HysteresisState.COOLDOWN:
            if now > self.cooldown_expiration:
                self.state = HysteresisState.IDLE
                self.incident_id = "-"
                self.accumulated_evidence.clear()
                logger.info(f"Cooldown Finished -> IDLE", camera_id=self.camera_id)


class AlertManager:
    """
    Central hub that takes decisions and triggers alerts/recordings on registered recorders.
    Decoupled action layer executing directives from the DecisionEngine via EventBus.
    Maintains per-camera IncidentState.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.camera_states = {}
        self._health_state = ComponentState.RUNNING
        
        # Subscribe to Decision Events
        get_event_bus().subscribe("DECISION_TRIGGER", self.handle_decision)
        get_event_bus().subscribe("FRAME_TICK", self.handle_tick)

    def get_health_state(self) -> ComponentState:
        return self._health_state

    def _get_state(self, camera_id: str) -> IncidentState:
        if camera_id not in self.camera_states:
            self.camera_states[camera_id] = IncidentState(camera_id)
        return self.camera_states[camera_id]

    def handle_decision(self, camera_id: str, event_type: str, confidence_scores: list, frame, ai_results: dict):
        """Received a decision trigger event"""
        with self.lock:
            state = self._get_state(camera_id)
            state.update(event_type, confidence_scores, frame, ai_results)

    def handle_tick(self, camera_id: str):
        """Called regularly to allow state machine to progress timeouts"""
        with self.lock:
            if camera_id in self.camera_states:
                self.camera_states[camera_id].tick()


# Global Alert Manager Singleton
_global_alert_manager = AlertManager()

def get_alert_manager() -> AlertManager:
    return _global_alert_manager
