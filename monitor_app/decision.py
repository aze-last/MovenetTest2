import threading
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


class DecisionEngine:
    """
    Central logical brain for behavior analysis and contraband triage.
    Inspects EvidencePackets and makes high-level start/stop recording decisions.
    """
    def __init__(self):
        self.lock = threading.Lock()
        
        # Register with Health Monitor
        from monitor_app.health import get_health_monitor
        get_health_monitor().register_component("Decision Engine", self.get_state)

    def get_state(self):
        from monitor_app.health import ComponentState
        return ComponentState.RUNNING

    def evaluate_trigger(self, packet: EvidencePacket) -> bool:
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
        return triggered

    def _filter_behavior_evidence(self, evidence_list):
        valid = []
        for evidence in evidence_list:
            if evidence.behavior_type == "concealment":
                if evidence.metadata.get("fusion_confirmed"):
                    valid.append(evidence)
            else:
                valid.append(evidence)
        return valid

    def get_event_details(self, packet: EvidencePacket) -> Tuple[str, List[float]]:
        """
        Extract standardized event type labels with threshold indicators and confidence scores.
        """
        detections = packet.detections
        event_labels = []

        # Parse contraband items with confidence & threshold (skip dismissed)
        for c in detections.get('contraband', []):
            if c.get('dismissed'):
                continue
            name = c.get('name', 'Item').capitalize()
            conf = float(c.get('confidence', 0.0))
            if conf > 0:
                event_labels.append(f"{name} ({int(conf*100)}% >= 30%)")
            else:
                event_labels.append(name)

        # Parse behavior evidence with metrics & thresholds
        for evidence in self._filter_behavior_evidence(packet.behavior_evidence):
            b_type = evidence.behavior_type.capitalize()
            conf = float(evidence.confidence)
            if evidence.behavior_type == "concealment":
                event_labels.append(f"Concealment ({int(conf*100)}% >= 75%)")
            elif "aggression" in evidence.behavior_type.lower() or "fight" in evidence.behavior_type.lower():
                speed = evidence.supporting_metrics.get("speed", 0.0) if evidence.supporting_metrics else conf
                event_labels.append(f"Aggression (Speed: {speed:.2f} >= 0.10)")
            else:
                event_labels.append(f"{b_type} ({int(conf*100)}%)")

        # Fallback to detections behavior if no behavior_evidence
        if not event_labels:
            for d in detections.get('behavior', []):
                lbl = d.get('label', '')
                if any(x in lbl for x in ["Aggressive", "Suspicious", "Fast"]):
                    score = d.get('score', 0.0)
                    event_labels.append(f"{lbl.split(':')[0].strip()} ({int(score*100)}%)")

        # Standardize event name
        unique_labels = list(dict.fromkeys(event_labels))
        event_type = " + ".join(unique_labels) if unique_labels else "Alert"
        
        # Compile confidence scores
        scores_b = [d.get('score', 0.0) for d in detections.get('behavior', [])]
        scores_c = [d.get('confidence', 0.0) for d in detections.get('contraband', [])]
        scores_e = [
            evidence.confidence
            for evidence in self._filter_behavior_evidence(packet.behavior_evidence)
        ]
        confidence_scores = scores_b + scores_c + scores_e
        
        return event_type, confidence_scores

    def get_severity(self, packet: EvidencePacket) -> str:
        """
        Determine standardized severity level (CRITICAL, HIGH, MEDIUM, LOW).
        """
        detections = packet.detections
        has_contraband = False
        for c in detections.get('contraband', []):
            name = c.get('name', '').lower()
            if any(k in name for k in ['cellphone', 'phone', 'knife']):
                has_contraband = True
                break

        has_behavior = False
        if packet.behavior_evidence:
            for b in self._filter_behavior_evidence(packet.behavior_evidence):
                b_type = b.behavior_type.lower()
                if any(k in b_type for k in ["aggression", "aggressive", "fight", "conceal", "fast"]):
                    has_behavior = True
                    break

        if has_contraband and has_behavior:
            return "CRITICAL"
        elif has_behavior:
            return "HIGH"
        elif has_contraband:
            return "MEDIUM"
        return "LOW"


    def generate_incident_record(self, packet: EvidencePacket, session_id: str, current_frame: int, video_time_str: str):
        from monitor_app.evidence import IncidentRecord, IncidentType, SnapshotResult
        
        detections = packet.detections
        incident_type = IncidentType.UNKNOWN
        
        has_contraband = False
        contraband_type = IncidentType.UNKNOWN
        contraband_score = 0.0
        contraband_track = -1
        contraband_reason = ""

        # 1. Check Contraband
        for c in detections.get('contraband', []):
            name = c.get('name', '').lower()
            if 'cellphone' in name or 'phone' in name:
                contraband_type = IncidentType.CELLPHONE
                contraband_score = c.get('confidence', 0.0)
                contraband_track = c.get('track_id', -1)
                contraband_reason = "Cellphone Detected"
                has_contraband = True
                break
            elif 'knife' in name:
                contraband_type = IncidentType.KNIFE
                contraband_score = c.get('confidence', 0.0)
                contraband_track = c.get('track_id', -1)
                contraband_reason = "Knife Detected"
                has_contraband = True
                break

        has_behavior = False
        behavior_type = IncidentType.UNKNOWN
        behavior_raw_score = 0.0
        behavior_norm_score = 0.0
        behavior_track = -1
        behavior_reason = ""

        # 2. Check Behavior independently
        if packet.behavior_evidence:
            for b in self._filter_behavior_evidence(packet.behavior_evidence):
                b_type = b.behavior_type.lower()
                if "aggression" in b_type or "aggressive" in b_type or "fight" in b_type:
                    behavior_type = IncidentType.AGGRESSION
                    behavior_raw_score = b.confidence
                    behavior_norm_score = min(b.confidence / 200.0, 1.0) # mock threshold
                    behavior_track = b.stable_id
                    behavior_reason = "Aggression Behavior"
                    has_behavior = True
                    break
                elif "conceal" in b_type:
                    behavior_type = IncidentType.SUSPICIOUS_CONCEALMENT
                    behavior_raw_score = b.confidence
                    behavior_norm_score = min(b.confidence / 150.0, 1.0)
                    behavior_track = b.stable_id
                    behavior_reason = "Concealment Behavior"
                    has_behavior = True
                    break
                elif "fast" in b_type:
                    if behavior_type == IncidentType.UNKNOWN:
                        behavior_type = IncidentType.FAST_MOVEMENT
                        behavior_raw_score = b.confidence
                        behavior_norm_score = min(b.confidence / 100.0, 1.0)
                        behavior_track = b.stable_id
                        behavior_reason = "Fast Movement"
                        has_behavior = True

        # Combine severity logic
        severity = "UNKNOWN"
        snapshot_required = False
        snapshot_reason = ""
        
        if has_contraband and has_behavior:
            severity = "CRITICAL"
            incident_type = contraband_type  # Priority to contraband type
            raw_score = contraband_score
            normalized_score = contraband_score
            subject_track_id = contraband_track
            snapshot_required = True
            snapshot_reason = f"{contraband_reason} + {behavior_reason}"
        elif has_behavior:
            severity = "HIGH"
            incident_type = behavior_type
            raw_score = behavior_raw_score
            normalized_score = behavior_norm_score
            subject_track_id = behavior_track
            snapshot_required = True
            snapshot_reason = behavior_reason
        elif has_contraband:
            severity = "MEDIUM"
            incident_type = contraband_type
            raw_score = contraband_score
            normalized_score = contraband_score
            subject_track_id = contraband_track
            snapshot_required = True
            snapshot_reason = contraband_reason
        else:
            raw_score = 0.0
            normalized_score = 0.0
            subject_track_id = -1
            
        if subject_track_id == "":
            subject_track_id = -1

        incident_id = f"{session_id}_f{current_frame}"
        snapshot_filename = f"{incident_id}.jpg" if snapshot_required else ""
        
        base_notes = " | ".join(packet.alerts)
        notes = f"Severity: {severity} | {base_notes}" if base_notes else f"Severity: {severity}"

        return IncidentRecord(
            incident_id=incident_id,
            incident_type=incident_type,
            frame_number=current_frame,
            timestamp=packet.timestamp,
            video_time=video_time_str,
            subject_track_id=int(subject_track_id),
            raw_score=float(raw_score),
            normalized_score=float(normalized_score),
            snapshot_required=snapshot_required,
            snapshot_reason=snapshot_reason,
            snapshot_filename=snapshot_filename,
            snapshot_result=SnapshotResult.PENDING,
            notes=notes,
            severity=severity
        )

# Global Decision Engine Singleton
_global_decision_engine = DecisionEngine()

def get_decision_engine() -> DecisionEngine:
    return _global_decision_engine
