import threading
from typing import Tuple, List
from monitor_app.evidence import EvidencePacket
from monitor_app.logger import get_module_logger

logger = get_module_logger("Decision Engine")

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
        """
        valid_evidence = self._filter_behavior_evidence(packet.behavior_evidence)
        triggered = bool(packet.alert_triggered or valid_evidence)
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
        Extract standardized event type labels and confidence scores.
        """
        detections = packet.detections

        # Parse behaviors (aggressive, suspicious, fast)
        behaviors = [
            d.get('label', 'Unknown') for d in detections.get('behavior', [])
            if any(x in d.get('label', '') for x in ["Aggressive", "Suspicious", "Fast"])
        ]

        behavior_evidence_labels = [
            evidence.behavior_type.capitalize()
            for evidence in self._filter_behavior_evidence(packet.behavior_evidence)
        ]
        behaviors.extend(behavior_evidence_labels)
        
        # Parse contraband items
        items = [d.get('name', 'Item') for d in detections.get('contraband', [])]
        
        # Standardize event name
        unique_labels = list(set([b.split(":")[0].strip() for b in behaviors] + items))
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
