import os

with open('monitor_app/decision.py', 'r', encoding='utf-8') as f:
    code = f.read()

registry_code = '''import threading
import time
from typing import Tuple, List, Dict, Any
from monitor_app.evidence import EvidencePacket
from monitor_app.logger import get_module_logger

logger = get_module_logger("Decision Engine")


class ContrabandDismissalRegistry:
    """
    Thread-safe registry tracking operator-dismissed contraband detections by track ID per camera.
    Suppresses recurring alert fatigue from static false positives (e.g. lights, reflections).
    When a brand new contraband ID appears, it triggers a fresh alert and beating sound.
    """
    def __init__(self, ttl_seconds: float = 15.0):
        self.lock = threading.Lock()
        self.ttl = ttl_seconds
        self._dismissed: Dict[str, Dict[Any, Dict[str, float]]] = {}

    def dismiss_track(self, camera_id: Any, track_id: Any):
        if track_id is None or track_id == -1:
            return
        cam_str = str(camera_id)
        now = time.time()
        with self.lock:
            if cam_str not in self._dismissed:
                self._dismissed[cam_str] = {}
            self._dismissed[cam_str][track_id] = {
                "dismissed_at": now,
                "last_seen": now
            }
            logger.info(f"Contraband detection dismissed: cam={cam_str} track_id={track_id}", camera_id=cam_str)

    def is_track_dismissed(self, camera_id: Any, track_id: Any) -> bool:
        if track_id is None or track_id == -1:
            return False
        cam_str = str(camera_id)
        now = time.time()
        with self.lock:
            cam_map = self._dismissed.get(cam_str)
            if not cam_map or track_id not in cam_map:
                return False
            entry = cam_map[track_id]
            if now - entry["last_seen"] > self.ttl:
                del cam_map[track_id]
                return False
            return True

    def touch_track(self, camera_id: Any, track_id: Any):
        """Update last_seen timestamp to sustain dismissal while object remains visible."""
        if track_id is None or track_id == -1:
            return
        cam_str = str(camera_id)
        now = time.time()
        with self.lock:
            cam_map = self._dismissed.get(cam_str)
            if cam_map and track_id in cam_map:
                cam_map[track_id]["last_seen"] = now

    def prune_stale(self, ttl: float = None):
        max_ttl = ttl if ttl is not None else self.ttl
        now = time.time()
        with self.lock:
            for cam_str in list(self._dismissed.keys()):
                cam_map = self._dismissed[cam_str]
                for tid in list(cam_map.keys()):
                    if now - cam_map[tid]["last_seen"] > max_ttl:
                        del cam_map[tid]
                if not cam_map:
                    del self._dismissed[cam_str]

    def clear_all(self):
        with self.lock:
            self._dismissed.clear()


_global_dismissal_registry = ContrabandDismissalRegistry()


def get_dismissal_registry() -> ContrabandDismissalRegistry:
    return _global_dismissal_registry
'''

# Replace header
header_target = '''import threading
from typing import Tuple, List
from monitor_app.evidence import EvidencePacket
from monitor_app.logger import get_module_logger

logger = get_module_logger("Decision Engine")'''

if header_target in code:
    code = code.replace(header_target, registry_code)
else:
    # try with CRLF
    code = code.replace(header_target.replace('\n', '\r\n'), registry_code.replace('\n', '\r\n'))

# Replace evaluate_trigger
old_eval = '''    def evaluate_trigger(self, packet: EvidencePacket) -> bool:
        """
        Evaluate if a new incident recording should be triggered.
        """
        valid_evidence = self._filter_behavior_evidence(packet.behavior_evidence)
        triggered = bool(packet.alert_triggered or valid_evidence)
        if triggered:
            logger.info(f"Trigger condition met! Alerts: {packet.alerts}", camera_id=packet.camera_id)
        return triggered'''

new_eval = '''    def evaluate_trigger(self, packet: EvidencePacket) -> bool:
        """
        Evaluate if a new incident recording should be triggered.
        Filters out contraband detections whose track IDs have been dismissed by the operator.
        """
        cam_str = str(packet.camera_id)
        reg = get_dismissal_registry()
        
        # 1. Process contraband detections against dismissal registry
        contraband_dets = packet.detections.get("contraband", [])
        has_undismissed_contraband = False
        
        for det in contraband_dets:
            tid = det.get("track_id")
            if tid is not None and reg.is_track_dismissed(cam_str, tid):
                reg.touch_track(cam_str, tid)
                det["dismissed"] = True
            else:
                has_undismissed_contraband = True
                
        # 2. Filter packet.alerts to suppress dismissed contraband from UI / alarm
        if contraband_dets and packet.alerts:
            filtered_alerts = []
            for alert_text in packet.alerts:
                is_dismissed_alert = False
                for det in contraband_dets:
                    if det.get("dismissed"):
                        tid_str = str(det.get("track_id"))
                        name_str = det.get("name", "").lower()
                        if tid_str in alert_text or (name_str and name_str in alert_text.lower() and not has_undismissed_contraband):
                            is_dismissed_alert = True
                            break
                if not is_dismissed_alert:
                    filtered_alerts.append(alert_text)
            packet.alerts = filtered_alerts

        # 3. Check behavior evidence
        valid_evidence = self._filter_behavior_evidence(packet.behavior_evidence)
        
        # If all contraband is dismissed and no behavior evidence exists, suppress alert_triggered
        if not has_undismissed_contraband and not valid_evidence and not packet.alerts:
            packet.alert_triggered = False
            return False

        triggered = bool(has_undismissed_contraband or valid_evidence or packet.alerts or packet.alert_triggered)
        if triggered:
            logger.info(f"Trigger condition met! Alerts: {packet.alerts}", camera_id=packet.camera_id)
        return triggered'''

if old_eval in code:
    code = code.replace(old_eval, new_eval)
else:
    code = code.replace(old_eval.replace('\n', '\r\n'), new_eval.replace('\n', '\r\n'))

# Update get_event_details to skip dismissed contraband
old_details = '''        # Parse contraband items with confidence & threshold
        for c in detections.get('contraband', []):
            name = c.get('name', 'Item').capitalize()'''

new_details = '''        # Parse contraband items with confidence & threshold (skip dismissed)
        for c in detections.get('contraband', []):
            if c.get('dismissed'):
                continue
            name = c.get('name', 'Item').capitalize()'''

if old_details in code:
    code = code.replace(old_details, new_details)
else:
    code = code.replace(old_details.replace('\n', '\r\n'), new_details.replace('\n', '\r\n'))

with open('monitor_app/decision.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Decision.py updated successfully!")

