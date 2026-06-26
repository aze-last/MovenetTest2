import logging
from datetime import datetime

class CellWatchFormatter(logging.Formatter):
    """
    Structured CellWatch Formatter:
    [Timestamp] [Level] [CameraID] Message
    """
    def format(self, record):
        dt = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = record.levelname
        component = getattr(record, "component", "System")
        camera_id = getattr(record, "camera_id", "-")
        incident_id = getattr(record, "incident_id", "-")
        
        # Format Camera Identifier
        cam_str = f"CAM{str(camera_id).zfill(2)}" if camera_id != "-" else "SYSTEM"
        
        # Build prefix
        prefix_parts = [dt, level, cam_str]
        if component != "System":
            prefix_parts.append(component)
        if incident_id != "-":
            prefix_parts.append(f"INCIDENT:{incident_id}")
            
        prefix = " | ".join(prefix_parts)
        message = record.getMessage()
        return f"{prefix} | {message}"
