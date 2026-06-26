import threading
from typing import Dict
from monitor_app.evidence import EvidencePacket

class CameraFusion:
    """
    Synchronized telemetry aggregator.
    Collects and maintains the latest EvidencePackets from all cameras.
    Does NOT perform ReID or cross-camera tracking.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_packets: Dict[str, EvidencePacket] = {}

    def update(self, packet: EvidencePacket):
        with self.lock:
            self.latest_packets[str(packet.camera_id)] = packet
            print(f"[Fusion] Aggregated telemetry packet for Cam {packet.camera_id}. Total camera feeds in fusion: {len(self.latest_packets)}")

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
