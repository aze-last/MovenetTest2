from typing import List
from monitor_app.behaviors.base import BehaviorDetector
from monitor_app.behaviors.concealment_detector import ConcealmentDetector

def get_active_detectors() -> List[BehaviorDetector]:
    """
    Returns the list of instantiated behavior detectors to run in the pipeline.
    """
    return [
        ConcealmentDetector()
    ]
