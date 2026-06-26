import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class EvidencePacket:
    """
    Standardized payload for communication between capture feeds,
    inference engines, tracking/fusion systems, and decision engines.
    """
    camera_id: str
    timestamp: float
    frame: np.ndarray
    motion_detected: bool = False
    motion_score: float = 0.0
    num_people: int = 0
    alert_triggered: bool = False
    alerts: List[str] = field(default_factory=list)
    detections: Dict[str, Any] = field(default_factory=lambda: {"behavior": [], "contraband": []})
    processing_mode: str = "Standard"

    def to_dict(self) -> Dict[str, Any]:
        """Convert payload to raw dictionary for backward compatibility."""
        return {
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "frame": self.frame,
            "motion_detected": self.motion_detected,
            "motion_score": self.motion_score,
            "num_people": self.num_people,
            "alert_triggered": self.alert_triggered,
            "alerts": self.alerts,
            "detections": self.detections,
            "processing_mode": self.processing_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidencePacket":
        """Instantiate EvidencePacket from dictionary representation."""
        return cls(
            camera_id=str(data.get("camera_id", "0")),
            timestamp=float(data.get("timestamp", 0.0)),
            frame=data.get("frame"),
            motion_detected=bool(data.get("motion_detected", False)),
            motion_score=float(data.get("motion_score", 0.0)),
            num_people=int(data.get("num_people", 0)),
            alert_triggered=bool(data.get("alert_triggered", False)),
            alerts=list(data.get("alerts", [])),
            detections=dict(data.get("detections", {"behavior": [], "contraband": []})),
            processing_mode=str(data.get("processing_mode", "Standard")),
        )
