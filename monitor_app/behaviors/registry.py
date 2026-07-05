from typing import List
from monitor_app.behaviors.base import BehaviorDetector


def get_active_detectors() -> List[BehaviorDetector]:
    """
    Per-person behavior detectors registered for the BehaviorEngine loop.
    Concealment is handled via multi-camera fusion in central_inference.
    """
    return []
