import time
import uuid

class TelemetryContext:
    """
    Isolated telemetry context carrying performance tracking markers and UUID 
    without polluting the active AI pipeline objects.
    """
    def __init__(self, camera_id: str, sequence_num: int):
        self.camera_id = str(camera_id)
        self.sequence_num = sequence_num
        self.timestamps = {}
        
        # Unique Frame UUID: cam_{id}_frame_{seq}_{timestamp_uuid}
        rand_suffix = uuid.uuid4().hex[:6]
        self.frame_uuid = f"cam_{self.camera_id}_frame_{sequence_num}_{int(time.time())}_{rand_suffix}"
        
        # Auto-initialize with creation/read start
        self.mark("camera_read_start")

    def mark(self, stage_name: str):
        """Record timestamp for a pipeline checkpoint."""
        self.timestamps[stage_name] = time.perf_counter()

    def get_duration(self, start_stage: str, end_stage: str) -> float:
        """Get latency in milliseconds between two checkpoints."""
        start = self.timestamps.get(start_stage)
        end = self.timestamps.get(end_stage)
        if start is not None and end is not None:
            return (end - start) * 1000.0
        return 0.0

    def to_dict(self) -> dict:
        """Serialize context for event publication or exports."""
        return {
            "camera_id": self.camera_id,
            "frame_uuid": self.frame_uuid,
            "sequence_num": self.sequence_num,
            "timestamps": self.timestamps.copy()
        }
