import sys
import threading
import time
from enum import Enum
from monitor_app.logger import get_module_logger
from monitor_app.config import get_config
from monitor_app.events import get_event_bus
from monitor_app.health import ComponentState

logger = get_module_logger("Alert Manager")

# Audio alert engine (Windows native / winsound fallback)
try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    winsound = None
    WINSOUND_AVAILABLE = False


class SoundAlertManager:
    """
    Asynchronous, rate-limited institutional audio alert engine.
    Plays distinct audio tones for security incidents without blocking UI or inference.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.last_played_time = 0.0
        self._load_config()

    def _load_config(self):
        cfg = get_config("audio_alerts") or {}
        self.enabled = cfg.get("enabled", True)
        self.min_interval = float(cfg.get("min_interval", 3.0))
        self.default_freq = int(cfg.get("frequency_hz", 1200))
        self.default_duration = int(cfg.get("duration_ms", 250))
        self.pitch_map = cfg.get("severity_pitch_map", {
            "CRITICAL": [1500, 1800],
            "HIGH": [1200, 1400],
            "MEDIUM": [900],
        })

    def play_alert(self, severity: str = "MEDIUM"):
        """
        Trigger asynchronous audio beep for the specified severity level.
        Rate-limited by min_interval.
        """
        if not self.enabled:
            return

        now = time.time()
        with self.lock:
            if now - self.last_played_time < self.min_interval:
                return
            self.last_played_time = now

        # Launch playback in background daemon thread
        threading.Thread(target=self._play_worker, args=(severity,), daemon=True).start()

    def _play_worker(self, severity: str):
        if not WINSOUND_AVAILABLE or winsound is None:
            return

        try:
            tones = self.pitch_map.get(severity.upper(), [self.default_freq])
            if isinstance(tones, int):
                tones = [tones]
            
            dur = max(50, int(self.default_duration / max(1, len(tones))))
            for freq in tones:
                winsound.Beep(int(freq), dur)
                time.sleep(0.02)
        except Exception as e:
            # Fallback to system message beep
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
            logger.debug(f"Audio alert playback notice: {e}")


_global_sound_alert = SoundAlertManager()

def get_sound_alert_manager() -> SoundAlertManager:
    return _global_sound_alert


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
        self.highest_severity = "LOW"
        self.first_detected = 0.0
        self.last_detected = 0.0
        self.cooldown_expiration = 0.0
        
        # Config params
        self.merge_window = get_config("incident_merging", "merge_window", 10.0)
        self.default_cooldown = get_config("alert_cooldowns", "default", 25.0)
        self.pending_duration = float(get_config("incident_merging", "pending_duration", 0.5))
        self._pending_frame = None
        self._pending_ai_results = {}
        self._pending_event_type = ""

    def _update_severity(self, new_severity: str):
        priority = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
        curr_p = priority.get(self.highest_severity.upper(), 0)
        new_p = priority.get(new_severity.upper(), 0)
        if new_p >= curr_p:
            self.highest_severity = new_severity.upper()

    def update(self, event_type: str, confidence_scores: list, frame, ai_results: dict, severity: str = "MEDIUM"):
        now = time.time()
        self.last_detected = now
        self._update_severity(severity)
        self._pending_frame = frame
        self._pending_ai_results = ai_results
        self._pending_event_type = event_type
        
        # If IDLE or NOT_SEEN, start PENDING
        if self.state in (HysteresisState.IDLE, HysteresisState.NOT_SEEN):
            self.state = HysteresisState.PENDING
            self.first_detected = now
            self.accumulated_evidence = {event_type}
            logger.info(f"Motion/Event detected -> PENDING", camera_id=self.camera_id)
            # CRITICAL, HIGH, and MEDIUM (contraband) severity confirm immediately without lag
            if self.highest_severity in ("CRITICAL", "HIGH", "MEDIUM") or self.pending_duration <= 0.0:
                self._confirm(event_type, frame, ai_results)
            elif now - self.first_detected >= self.pending_duration:
                self._confirm(event_type, frame, ai_results)
        
        elif self.state == HysteresisState.PENDING:
            self.accumulated_evidence.add(event_type)
            # Confirm when pending duration elapsed or severity elevated
            if self.highest_severity in ("CRITICAL", "HIGH", "MEDIUM") or (now - self.first_detected >= self.pending_duration):
                self._confirm(event_type, frame, ai_results)
                
        elif self.state in (HysteresisState.CONFIRMED, HysteresisState.MAINTAINED):
            self.state = HysteresisState.MAINTAINED
            if event_type not in self.accumulated_evidence:
                self.accumulated_evidence.add(event_type)
                logger.info(f"Evidence Added | Type: {event_type} | Severity: {self.highest_severity}", camera_id=self.camera_id, incident_id=self.incident_id)
                get_event_bus().publish(
                    "EVIDENCE_ADDED",
                    camera_id=self.camera_id,
                    incident_id=self.incident_id,
                    event_type=event_type,
                    confidence_scores=confidence_scores,
                    severity=self.highest_severity
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
        logger.info(f"Incident Created | Type: {joined_evidence} | Severity: {self.highest_severity}", camera_id=self.camera_id, incident_id=self.incident_id)
        
        # Publish Event to Recorder & UI
        get_event_bus().publish(
            "INCIDENT_START", 
            camera_id=self.camera_id, 
            incident_id=self.incident_id, 
            event_type=joined_evidence, 
            severity=self.highest_severity,
            frame=frame, 
            ai_results=ai_results
        )

        # Trigger Institutional Audio Alert
        get_sound_alert_manager().play_alert(self.highest_severity)

        # Optional cloud second-opinion (prep, OFF by default).
        # Local truth already published above; this only enriches via CLOUD_VERDICT.
        # Never blocks: daemon thread, 2s timeout, rate-limited, silent fallback.
        try:
            from monitor_app.cloud_verifier import get_cloud_verifier
            get_cloud_verifier().verify_async(
                camera_id=self.camera_id,
                incident_id=self.incident_id,
                event_type=joined_evidence,
                severity=self.highest_severity,
                frame=frame,
            )
        except Exception:
            pass

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
            # If pending duration reached while detection remains active, confirm!
            if (now - self.first_detected >= self.pending_duration) and (now - self.last_detected <= self.merge_window):
                p_frame = getattr(self, "_pending_frame", None)
                p_res = getattr(self, "_pending_ai_results", {})
                p_evt = getattr(self, "_pending_event_type", "Alert")
                self._confirm(p_evt, p_frame, p_res)
            # If no detection for a while, go back to IDLE
            elif now - self.last_detected > self.merge_window:
                self.state = HysteresisState.IDLE
                self.accumulated_evidence.clear()
                self.highest_severity = "LOW"
                logger.info(f"Pending timeout -> IDLE", camera_id=self.camera_id)

        elif self.state == HysteresisState.COOLDOWN:
            if now > self.cooldown_expiration:
                self.state = HysteresisState.IDLE
                self.incident_id = "-"
                self.accumulated_evidence.clear()
                self.highest_severity = "LOW"
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
        from monitor_app.utils import normalize_cam_id
        norm_id = normalize_cam_id(camera_id)
        if norm_id not in self.camera_states:
            self.camera_states[norm_id] = IncidentState(norm_id)
        return self.camera_states[norm_id]

    def handle_decision(self, camera_id: str, event_type: str, confidence_scores: list, frame, ai_results: dict, severity: str = "MEDIUM", **kwargs):
        """Received a decision trigger event"""
        with self.lock:
            state = self._get_state(camera_id)
            state.update(event_type, confidence_scores, frame, ai_results, severity=severity)

    def handle_tick(self, camera_id: str, **kwargs):
        """Called regularly to allow state machine to progress timeouts"""
        with self.lock:
            from monitor_app.utils import normalize_cam_id
            norm_id = normalize_cam_id(camera_id)
            if norm_id in self.camera_states:
                self.camera_states[norm_id].tick()


# Global Alert Manager Singleton
_global_alert_manager = AlertManager()

def get_alert_manager() -> AlertManager:
    return _global_alert_manager

