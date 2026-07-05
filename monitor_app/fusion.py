import threading
import time
from typing import Dict, List, Tuple

from monitor_app.evidence import EvidencePacket, HandObservation
from monitor_app.logger import get_module_logger

logger = get_module_logger("Camera Fusion")


class CameraFusion:
    """
    Synchronized telemetry aggregator.
    Collects latest EvidencePackets and per-camera hand observations.
    Does NOT perform ReID or cross-camera tracking.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.latest_packets: Dict[str, EvidencePacket] = {}
        self.hand_observations: Dict[str, Tuple[float, List[HandObservation]]] = {}

        from monitor_app.health import get_health_monitor
        get_health_monitor().register_component("Camera Fusion", self.get_state)

    def get_state(self):
        from monitor_app.health import ComponentState
        return ComponentState.RUNNING if self.latest_packets else ComponentState.IDLE

    def update(self, packet: EvidencePacket):
        with self.lock:
            self.latest_packets[str(packet.camera_id)] = packet
            logger.debug("Aggregated telemetry packet", camera_id=packet.camera_id)

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

    def get_latest_packet(self, camera_id: str) -> EvidencePacket:
        with self.lock:
            return self.latest_packets.get(str(camera_id))

    def get_all_packets(self) -> Dict[str, EvidencePacket]:
        with self.lock:
            return dict(self.latest_packets)


_global_fusion = CameraFusion()


def get_camera_fusion() -> CameraFusion:
    return _global_fusion
