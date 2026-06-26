import threading
from typing import Dict
from monitor_app.evidence import EvidencePacket
from monitor_app.logger import get_module_logger

logger = get_module_logger("Camera Fusion")

class CameraFusion:
    """
    Synchronized telemetry aggregator.
    Collects and maintains the latest EvidencePackets from all cameras.
    Does NOT perform ReID or cross-camera tracking.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_packets: Dict[str, EvidencePacket] = {}
        
        # Register with Health Monitor
        from monitor_app.health import get_health_monitor
        get_health_monitor().register_component("Camera Fusion", self.get_state)

    def get_state(self):
        from monitor_app.health import ComponentState
        return ComponentState.RUNNING if self.latest_packets else ComponentState.IDLE

    def update(self, packet: EvidencePacket):
        with self.lock:
            self.latest_packets[str(packet.camera_id)] = packet
            logger.debug(f"Aggregated telemetry packet", camera_id=packet.camera_id)

    def get_latest_packet(self, camera_id: str) -> EvidencePacket:
        with self.lock:
            return self.latest_packets.get(str(camera_id))

    def get_all_packets(self) -> Dict[str, EvidencePacket]:
        with self.lock:
            return dict(self.latest_packets)

# Global Camera Fusion Singleton
_global_fusion = CameraFusion()

def get_camera_fusion() -> CameraFusion:
    return _global_fusion
