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
        triggered = bool(packet.alert_triggered or packet.behavior_evidence)
        if triggered:
            logger.info(f"Trigger condition met! Alerts: {packet.alerts}", camera_id=packet.camera_id)
        return triggered

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
            evidence.behavior_type.capitalize() for evidence in packet.behavior_evidence
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
        scores_e = [evidence.confidence for evidence in packet.behavior_evidence]
        confidence_scores = scores_b + scores_c + scores_e
        
        return event_type, confidence_scores

# Global Decision Engine Singleton
_global_decision_engine = DecisionEngine()

def get_decision_engine() -> DecisionEngine:
    return _global_decision_engine
