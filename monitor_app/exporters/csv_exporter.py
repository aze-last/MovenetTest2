import csv
import os

class CSVExporter:
    def __init__(self, export_dir):
        self.export_dir = export_dir

    def export_detections(self, all_detections):
        path = os.path.join(self.export_dir, "detections.csv")
        headers = [
            "Frame Number", "Timestamp", "Video Time", "Detection Class", 
            "Confidence", "Bounding Box", "Track ID", "Camera/Source", 
            "Behavior Label", "Incident Decision", "Snapshot Filename"
        ]
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for d in all_detections:
                writer.writerow([
                    d.get("frame_number", ""),
                    d.get("timestamp", ""),
                    d.get("video_time", ""),
                    d.get("detection_class", ""),
                    f"{d.get('confidence', 0.0):.3f}",
                    d.get("bounding_box", ""),
                    d.get("track_id", ""),
                    d.get("camera_source", "Offline"),
                    d.get("behavior_label", ""),
                    d.get("incident_decision", "No"),
                    d.get("snapshot_filename", "")
                ])

    def export_incidents(self, detailed_incidents):
        path = os.path.join(self.export_dir, "incidents.csv")
        headers = [
            "Incident ID", "Frame Number", "Timestamp", "Video Time", 
            "Incident Type", "Normalized Score", "Raw Score", "Track ID", 
            "Snapshot Result", "Snapshot Reason", "Snapshot Filename", "Notes"
        ]
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for inc in detailed_incidents:
                writer.writerow([
                    inc.get("incident_id", ""),
                    inc.get("frame_number", ""),
                    inc.get("timestamp", ""),
                    inc.get("video_time", ""),
                    inc.get("incident_type", ""),
                    f"{inc.get('normalized_score', 0.0):.3f}",
                    f"{inc.get('raw_score', 0.0):.3f}",
                    inc.get("subject_track_id", ""),
                    inc.get("snapshot_result", ""),
                    inc.get("snapshot_reason", ""),
                    inc.get("snapshot_filename", ""),
                    inc.get("notes", "")
                ])

    def export_telemetry(self, telemetry):
        path = os.path.join(self.export_dir, "telemetry.csv")
        if not telemetry:
            open(path, "w").close()
            return
            
        headers = list(telemetry[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(telemetry)
