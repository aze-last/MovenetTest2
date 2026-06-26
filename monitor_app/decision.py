import threading
from typing import Tuple, List
from monitor_app.evidence import EvidencePacket

class DecisionEngine:
    """
    Central logical brain for behavior analysis and contraband triage.
    Inspects EvidencePackets and makes high-level start/stop recording decisions.
    """
    def __init__(self):
        self.lock = threading.Lock()

    def evaluate_trigger(self, packet: EvidencePacket) -> bool:
        """
        Evaluate if a new incident recording should be triggered.
        """
        return packet.alert_triggered

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
        
        # Parse contraband items
        items = [d.get('name', 'Item') for d in detections.get('contraband', [])]
        
        # Standardize event name
        unique_labels = list(set([b.split(":")[0].strip() for b in behaviors] + items))
        event_type = " + ".join(unique_labels) if unique_labels else "Alert"
        
        # Compile confidence scores
        scores_b = [d.get('score', 0.0) for d in detections.get('behavior', [])]
        scores_c = [d.get('confidence', 0.0) for d in detections.get('contraband', [])]
        confidence_scores = scores_b + scores_c
        
        return event_type, confidence_scores

# Global Decision Engine Singleton
_global_decision_engine = DecisionEngine()

def get_decision_engine() -> DecisionEngine:
    return _global_decision_engine
