from typing import Optional
from monitor_app.evidence import BehaviorEvidence, TrackedPerson

class BehaviorDetector:
    name: str = "base"
    
    def detect(self, person: TrackedPerson, frame_index: int, sensitivity: str) -> Optional[BehaviorEvidence]:
        """
        Analyze a person at a specific frame index and sensitivity level.
        Returns: Optional[BehaviorEvidence] if behavior is confirmed, otherwise None.
        """
        pass
