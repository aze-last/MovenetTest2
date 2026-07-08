import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum


class IncidentType(Enum):
    CELLPHONE = "Cellphone"
    KNIFE = "Knife"
    AGGRESSION = "Aggression"
    SUSPICIOUS_CONCEALMENT = "Suspicious Concealment"
    FAST_MOVEMENT = "Fast Movement"
    UNKNOWN = "Unknown"


class HandSide(Enum):
    LEFT = "left"
    RIGHT = "right"


class HandObservationState(Enum):
    VISIBLE = "visible"
    CONCEALED = "concealed"
    UNKNOWN = "unknown"


@dataclass
class HandObservation:
    """Per-camera hand visibility observation before multi-camera fusion."""
    camera_id: str
    stable_id: int
    hand: HandSide
    state: HandObservationState
    confidence: float
    timestamp: float
    frame_index: int
    sources: Dict[str, Any] = field(default_factory=dict)
    view_quality: float = 0.0
    hip_centroid: Optional[Tuple[float, float]] = None


@dataclass
class FusedConcealmentObservation:
    """Zone-level fused hand state across multiple cameras."""
    zone_id: str
    subject_slot: int
    hand: HandSide
    fused_state: HandObservationState
    fused_confidence: float
    supporting_cameras: List[str] = field(default_factory=list)
    vetoing_cameras: List[str] = field(default_factory=list)
    unknown_cameras: List[str] = field(default_factory=list)
    camera_stable_ids: Dict[str, int] = field(default_factory=dict)


class SnapshotResult(Enum):
    SUCCESS = "Success"
    NO_FRAME = "No Frame"
    NO_TRACK = "No Track"
    NOT_CRITICAL = "Not Critical"
    WRITE_FAILED = "Write Failed"
    DIRECTORY_FAILED = "Directory Failed"
    INVALID_IMAGE = "Invalid Image"
    PENDING = "Pending"


@dataclass
class IncidentRecord:
    incident_id: str
    incident_type: IncidentType
    frame_number: int
    timestamp: float
    video_time: str
    subject_track_id: int
    raw_score: float
    normalized_score: float
    snapshot_required: bool
    snapshot_reason: str
    snapshot_filename: str
    snapshot_result: SnapshotResult
    notes: str
    severity: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "incident_type": self.incident_type.value,
            "frame_number": self.frame_number,
            "timestamp": self.timestamp,
            "video_time": self.video_time,
            "subject_track_id": self.subject_track_id,
            "raw_score": self.raw_score,
            "normalized_score": self.normalized_score,
            "snapshot_required": self.snapshot_required,
            "snapshot_reason": self.snapshot_reason,
            "snapshot_filename": self.snapshot_filename,
            "snapshot_result": self.snapshot_result.value,
            "notes": self.notes,
            "severity": getattr(self, "severity", "UNKNOWN")
        }


@dataclass
class TrackedPerson:
    """Canonical frame-level representation of a detected person."""
    stable_id: int
    raw_person_id: int
    camera_id: str
    keypoints: np.ndarray
    bbox: Optional[Tuple[int, int, int, int]] = None
    hip_centroid: Optional[Tuple[float, float]] = None
    confidence: float = 0.0
    frame_number: int = 0
    timestamp: float = 0.0
    torso_height: float = 0.0
    shoulder_width: float = 0.0


@dataclass
class BehaviorEvidence:
    """Behavior-level evidence emitted by detectors for the decision pipeline."""
    behavior_type: str
    stable_id: int
    confidence: float
    frame_number: int
    timestamp: float
    sustained_frames: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    camera_id: str = "-"
    supporting_metrics: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


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
    tracked_persons: List[TrackedPerson] = field(default_factory=list)
    behavior_evidence: List[BehaviorEvidence] = field(default_factory=list)
    fused_concealment: List["FusedConcealmentObservation"] = field(default_factory=list)
    frame_uuid: Optional[str] = None

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
            "frame_uuid": self.frame_uuid,
            "tracked_persons": [
                {
                    "stable_id": person.stable_id,
                    "raw_person_id": person.raw_person_id,
                    "camera_id": person.camera_id,
                    "keypoints": person.keypoints.tolist() if isinstance(person.keypoints, np.ndarray) else person.keypoints,
                    "bbox": person.bbox,
                    "hip_centroid": person.hip_centroid,
                    "confidence": person.confidence,
                    "frame_number": person.frame_number,
                    "timestamp": person.timestamp,
                    "torso_height": person.torso_height,
                    "shoulder_width": person.shoulder_width,
                }
                for person in self.tracked_persons
            ],
            "behavior_evidence": [
                {
                    "behavior_type": evidence.behavior_type,
                    "stable_id": evidence.stable_id,
                    "confidence": evidence.confidence,
                    "frame_number": evidence.frame_number,
                    "timestamp": evidence.timestamp,
                    "sustained_frames": evidence.sustained_frames,
                    "metadata": evidence.metadata,
                    "camera_id": evidence.camera_id,
                    "supporting_metrics": evidence.supporting_metrics,
                    "reason": evidence.reason,
                }
                for evidence in self.behavior_evidence
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidencePacket":
        """Instantiate EvidencePacket from dictionary representation."""
        tracked_persons = []
        for item in data.get("tracked_persons", []):
            keypoints = item.get("keypoints")
            tracked_persons.append(
                TrackedPerson(
                    stable_id=int(item.get("stable_id", -1)),
                    raw_person_id=int(item.get("raw_person_id", 0)),
                    camera_id=str(item.get("camera_id", "0")),
                    keypoints=np.array(keypoints, dtype=float) if keypoints is not None else np.empty((0, 3), dtype=float),
                    bbox=item.get("bbox"),
                    hip_centroid=item.get("hip_centroid"),
                    confidence=float(item.get("confidence", 0.0)),
                    frame_number=int(item.get("frame_number", 0)),
                    timestamp=float(item.get("timestamp", 0.0)),
                    torso_height=float(item.get("torso_height", 0.0)),
                    shoulder_width=float(item.get("shoulder_width", 0.0)),
                )
            )

        behavior_evidence = []
        for item in data.get("behavior_evidence", []):
            behavior_evidence.append(
                BehaviorEvidence(
                    behavior_type=str(item.get("behavior_type", "unknown")),
                    stable_id=int(item.get("stable_id", -1)),
                    confidence=float(item.get("confidence", 0.0)),
                    frame_number=int(item.get("frame_number", 0)),
                    timestamp=float(item.get("timestamp", 0.0)),
                    sustained_frames=int(item.get("sustained_frames", 1)),
                    metadata=dict(item.get("metadata", {})),
                    camera_id=str(item.get("camera_id", "-")),
                    supporting_metrics=dict(item.get("supporting_metrics", {})),
                    reason=str(item.get("reason", "")),
                )
            )

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
            tracked_persons=tracked_persons,
            behavior_evidence=behavior_evidence,
            frame_uuid=data.get("frame_uuid")
        )
