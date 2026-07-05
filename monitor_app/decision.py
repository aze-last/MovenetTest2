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
        raw_score = 0.0
        normalized_score = 0.0
        subject_track_id = -1
        snapshot_reason = ""
        snapshot_required = False

        # 1. Check Contraband first (High priority)
        for c in detections.get('contraband', []):
            name = c.get('name', '').lower()
            if 'cellphone' in name or 'phone' in name:
                incident_type = IncidentType.CELLPHONE
                raw_score = c.get('confidence', 0.0)
                normalized_score = raw_score
                subject_track_id = c.get('track_id', -1)
                snapshot_required = True
                snapshot_reason = "Cellphone Detected"
                break
            elif 'knife' in name:
                incident_type = IncidentType.KNIFE
                raw_score = c.get('confidence', 0.0)
                normalized_score = raw_score
                subject_track_id = c.get('track_id', -1)
                snapshot_required = True
                snapshot_reason = "Knife Detected"
                break

        # 2. Check Behavior if Contraband didn't trigger critical
        if incident_type == IncidentType.UNKNOWN or not snapshot_required:
            if packet.behavior_evidence:
                for b in self._filter_behavior_evidence(packet.behavior_evidence):
                    b_type = b.behavior_type.lower()
                    if "aggression" in b_type or "aggressive" in b_type or "fight" in b_type:
                        incident_type = IncidentType.AGGRESSION
                        raw_score = b.confidence
                        normalized_score = min(raw_score / 200.0, 1.0) # mock threshold
                        subject_track_id = b.stable_id
                        snapshot_required = True
                        snapshot_reason = "Aggression Behavior"
                        break
                    elif "conceal" in b_type:
                        incident_type = IncidentType.SUSPICIOUS_CONCEALMENT
                        raw_score = b.confidence
                        normalized_score = min(raw_score / 150.0, 1.0)
                        subject_track_id = b.stable_id
                        snapshot_required = True
                        snapshot_reason = "Concealment Behavior"
                        break
                    elif "fast" in b_type:
                        if incident_type == IncidentType.UNKNOWN:
                            incident_type = IncidentType.FAST_MOVEMENT
                            raw_score = b.confidence
                            normalized_score = min(raw_score / 100.0, 1.0)
                            subject_track_id = b.stable_id
                            
        if subject_track_id == "":
            subject_track_id = -1

        incident_id = f"{session_id}_f{current_frame}"
        snapshot_filename = f"{incident_id}.jpg" if snapshot_required else ""
        
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
            notes=" | ".join(packet.alerts)
        )

# Global Decision Engine Singleton
_global_decision_engine = DecisionEngine()

def get_decision_engine() -> DecisionEngine:
    return _global_decision_engine
