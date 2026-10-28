import threading
import time
from typing import Dict, List, Tuple, Any, Optional

from monitor_app.config import get_config
from monitor_app.events import get_event_bus
from monitor_app.evidence import EvidencePacket, HandObservation
from monitor_app.logger import get_module_logger

logger = get_module_logger("Camera Fusion")


class CameraFusion:
    """
    Synchronized multi-camera telemetry aggregator and cross-camera zone deduplicator.
    - Collects latest EvidencePackets and per-camera hand observations.
    - Maintains cross-camera sliding window (default 7.0s) per facility zone.
    - Deduplicates alerts across cameras covering the same zone, suppressing alarm storms
      and merging multi-camera detections into corroborating evidence.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.latest_packets: Dict[str, EvidencePacket] = {}
        self.hand_observations: Dict[str, Tuple[float, List[HandObservation]]] = {}

        # Cross-camera zone deduplication state
        self.camera_zones: Dict[str, str] = dict(get_config("fusion", "camera_zones", {}))
        self.zone_dedup_window_s: float = float(get_config("fusion", "zone_dedup_window_s", 7.0))
        # (zone_id, event_type) -> zone_event_dict
        self.active_zone_events: Dict[Tuple[str, str], Dict[str, Any]] = {}

        from monitor_app.health import get_health_monitor
        get_health_monitor().register_component("Camera Fusion", self.get_state)

    def get_state(self):
        from monitor_app.health import ComponentState
        return ComponentState.RUNNING if self.latest_packets else ComponentState.IDLE

    def resolve_zone(self, camera_id: str) -> str:
        """Resolves the facility zone ID for a given camera, defaulting to Zone_<camera_id>."""
        cam_str = str(camera_id)
        if cam_str in self.camera_zones:
            return self.camera_zones[cam_str]
        cfg_zones = get_config("fusion", "camera_zones", {})
        if cam_str in cfg_zones:
            return cfg_zones[cam_str]
        return f"Zone_{cam_str}"

    def update(self, packet: EvidencePacket):
        with self.lock:
            self.latest_packets[str(packet.camera_id)] = packet
            logger.debug(f"Aggregated telemetry packet from cam={packet.camera_id}")

    def update_hand_observations(
        self, camera_id: str, observations: List[HandObservation]
    ):
        with self.lock:
            self.hand_observations[str(camera_id)] = (time.time(), list(observations))

    def get_hand_observations_snapshot(
        self,
    ) -> Dict[str, Tuple[float, List[HandObservation]]]:
        with self.lock:
            return dict(self.hand_observations)

    def get_latest_packet(self, camera_id: str) -> Optional[EvidencePacket]:
        with self.lock:
            return self.latest_packets.get(str(camera_id))

    def get_all_packets(self) -> Dict[str, EvidencePacket]:
        with self.lock:
            return dict(self.latest_packets)

    def get_active_zone_event(self, zone_id: str, event_type: str) -> Optional[Dict[str, Any]]:
        """Returns the active zone incident state if within the sliding window."""
        with self.lock:
            return self.active_zone_events.get((zone_id, event_type))

    def clear_zone_events(self, zone_id: Optional[str] = None, camera_id: Optional[str] = None):
        """Clears active zone events on operator dismissal so new detections can trigger fresh alerts."""
        with self.lock:
            if zone_id is None and camera_id is not None:
                zone_id = self.resolve_zone(str(camera_id))
            if zone_id:
                keys_to_del = [k for k in self.active_zone_events if k[0] == zone_id]
                for k in keys_to_del:
                    del self.active_zone_events[k]
                logger.info(f"Active zone events cleared for zone={zone_id}")
            else:
                self.active_zone_events.clear()
                logger.info("All active zone events cleared")

    def _prune_expired_events(self, current_time: float):
        """Internal helper to clean up old inactive zone events."""
        expired = [
            k for k, v in self.active_zone_events.items()
            if current_time - float(v.get("last_seen_time", 0.0)) > self.zone_dedup_window_s * 2.0
        ]
        for k in expired:
            del self.active_zone_events[k]

    def process_decision_trigger(
        self,
        packet: EvidencePacket,
        decision_engine: Any,
        ai_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Evaluates decision trigger with cross-camera zone deduplication.
        - If decision engine evaluates False: returns False.
        - If first alert in zone within window: emits DECISION_TRIGGER and opens zone event.
        - If corroborating alert in same zone within window: suppresses duplicate DECISION_TRIGGER
          and appends camera to corroborating evidence.
        """
        if not decision_engine.evaluate_trigger(packet):
            return False

        import re
        evt_type, conf_scores = decision_engine.get_event_details(packet)
        severity = decision_engine.get_severity(packet)
        zone_id = self.resolve_zone(packet.camera_id)
        current_time = float(packet.timestamp) if packet.timestamp else time.time()
        
        # Canonicalize event type (strip dynamic percentage/speed) for zone deduplication
        canonical_type = re.sub(r'\s*\([^)]*\)', '', evt_type).strip() or evt_type
        event_key = (zone_id, canonical_type)

        with self.lock:
            self._prune_expired_events(current_time)
            active_event = self.active_zone_events.get(event_key)

            if active_event is not None:
                elapsed = current_time - float(active_event.get("last_seen_time", 0.0))
                if elapsed <= self.zone_dedup_window_s:
                    active_event["last_seen_time"] = current_time
                    cam_id_str = str(packet.camera_id)
                    if cam_id_str != active_event.get("initial_camera_id"):
                        # Secondary camera in same zone: corroborate without duplicate alarm storm
                        if cam_id_str not in active_event["corroborating_cameras"]:
                            active_event["corroborating_cameras"].append(cam_id_str)
                            logger.info(
                                f"Cross-camera alert corroborated: cam={cam_id_str} in zone={zone_id} "
                                f"for event={canonical_type} (initial cam={active_event['initial_camera_id']})"
                            )
                            # Publish multi-camera corroborating evidence
                            get_event_bus().publish(
                                "EVIDENCE_ADDED",
                                camera_id=active_event["initial_camera_id"],
                                incident_id="",
                                event_type=f"Cross-Camera Corroboration (Cam {cam_id_str})",
                                confidence_scores=conf_scores,
                                severity=severity
                            )
                        return False
                    else:
                        # Primary detecting camera: update metadata and continue to emit DECISION_TRIGGER
                        active_event["confidence_scores"] = conf_scores
                        active_event["severity"] = severity
                        active_event["event_type"] = evt_type

            if active_event is None:
                # First detection in this zone or window expired: open new zone incident
                self.active_zone_events[event_key] = {
                    "zone_id": zone_id,
                    "event_type": evt_type,
                    "canonical_type": canonical_type,
                    "initial_camera_id": str(packet.camera_id),
                    "corroborating_cameras": [str(packet.camera_id)],
                    "start_time": current_time,
                    "last_seen_time": current_time,
                    "severity": severity,
                    "confidence_scores": conf_scores,
                }
                logger.info(
                    f"Zone incident initiated: zone={zone_id} cam={packet.camera_id} "
                    f"event={evt_type} severity={severity}"
                )

        # Publish DECISION_TRIGGER outside the lock
        get_event_bus().publish(
            "DECISION_TRIGGER",
            camera_id=packet.camera_id,
            zone_id=zone_id,
            event_type=evt_type,
            confidence_scores=conf_scores,
            severity=severity,
            frame=packet.frame,
            ai_results=ai_results or {},
        )
        return True


_global_fusion = CameraFusion()


def get_camera_fusion() -> CameraFusion:
    return _global_fusion
