import json
import os
from datetime import datetime

class JSONExporter:
    def __init__(self, export_dir):
        self.export_dir = export_dir

    def export_manifest(self, session_id, profile, video_path, frames_processed, total_time, fingerprint, detailed_incidents):
        snapshots_requested = sum(1 for inc in detailed_incidents if inc.get("snapshot_required"))
        snapshots_written = sum(1 for inc in detailed_incidents if inc.get("snapshot_result") == "Success")
        snapshots_skipped = snapshots_requested - snapshots_written
        
        manifest = {
            "export_schema_version": "1.0",
            "report_version": "1.0",
            "telemetry_version": "1.0",
            "benchmark_version": "1.0",
            "offline_pipeline_version": "2.0",
            
            "session_id": session_id,
            "profile": profile,
            "video_path": video_path,
            "timestamp": datetime.now().isoformat(),
            "operator": "LocalAdmin",
            "frames_processed": frames_processed,
            "duration_seconds": total_time,
            
            "hardware": fingerprint,
            
            "benchmarks": {
                "snapshots_requested": snapshots_requested,
                "snapshots_written": snapshots_written,
                "snapshots_skipped": snapshots_skipped
            }
        }
        with open(os.path.join(self.export_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

    def export_replay_index(self, detailed_incidents):
        replay = []
        for inc in detailed_incidents:
            replay.append({
                "frame": inc.get("frame_number"),
                "timestamp": inc.get("timestamp"),
                "incident_id": inc.get("incident_id"),
                "track_ids": inc.get("subject_track_id"),
                "snapshot": inc.get("snapshot_filename"),
                "video_position": inc.get("video_time")
            })
        with open(os.path.join(self.export_dir, "replay.json"), "w") as f:
            json.dump(replay, f, indent=2)

    def update_global_registry(self, session_id, fingerprint, video_path, profile, total_time, status="PASS", score="N/A"):
        exports_root = os.path.dirname(self.export_dir)
        registry_path = os.path.join(exports_root, "session_registry.json")
        
        registry = []
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
            except Exception:
                registry = []
                
        session_entry = {
            "session_id": session_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hardware_fingerprint": fingerprint.get("hardware_fingerprint", "Unknown"),
            "video_name": os.path.basename(video_path),
            "profile": profile,
            "duration_seconds": round(total_time, 2),
            "overall_score": score,
            "status": status,
            "report_path": os.path.join(session_id, "report.pdf"),
            "export_folder": session_id
        }
        
        updated = False
        for i, entry in enumerate(registry):
            if entry.get("session_id") == session_id:
                registry[i] = session_entry
                updated = True
                break
        
        if not updated:
            registry.append(session_entry)
            
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)
