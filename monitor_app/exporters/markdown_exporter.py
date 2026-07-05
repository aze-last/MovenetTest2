import os
from collections import defaultdict

class MarkdownExporter:
    def __init__(self, export_dir):
        self.export_dir = export_dir

    def export_timeline(self, detailed_incidents):
        path = os.path.join(self.export_dir, "timeline.md")
        with open(path, "w") as f:
            f.write("# Incident Timeline\n\n")
            for inc in sorted(detailed_incidents, key=lambda x: x.get("timestamp", 0)):
                f.write(f"### {inc.get('video_time', '00:00:00')}\n\n")
                f.write(f"**{inc.get('incident_type', 'Unknown')}** detected\n\n")
                if inc.get("normalized_score"):
                    f.write(f"- Confidence: {inc['normalized_score'] * 100:.1f}%\n")
                if inc.get("subject_track_id", -1) != -1:
                    f.write(f"- Track ID: {inc['subject_track_id']}\n")
                if inc.get("snapshot_filename"):
                    f.write(f"- Snapshot: `gallery/{inc['snapshot_filename']}`\n")
                f.write("\n---\n\n")

    def export_gallery(self, detailed_incidents):
        path = os.path.join(self.export_dir, "gallery.md")
        with open(path, "w") as f:
            f.write("# Detection Gallery\n\n")
            
            incidents_with_snaps = [inc for inc in detailed_incidents if inc.get("snapshot_filename")]
            
            if not incidents_with_snaps:
                f.write("*No critical incidents requiring snapshots were detected.*\n")
                return
                
            for inc in incidents_with_snaps:
                f.write(f"### Incident {inc.get('incident_id', '?')}\n\n")
                f.write(f"**Class:** {inc.get('incident_type', 'Unknown')}\n\n")
                f.write(f"**Confidence:** {inc.get('normalized_score', 0)*100:.1f}%\n\n")
                f.write(f"**Time:** {inc.get('video_time', '00:00:00')}\n\n")
                
                # In standard markdown syntax
                snap_path = f"gallery/{inc['snapshot_filename']}"
                f.write(f"![{inc.get('incident_type', 'Detection')}]({snap_path})\n\n")
                f.write("---\n\n")

    def export_report(self, session_id, profile, video_path, total_time, frames_processed, all_detections, detailed_incidents, telemetry, fingerprint):
        path = os.path.join(self.export_dir, "report.md")
        
        # Calculate some stats
        detection_counts = defaultdict(int)
        for d in all_detections:
            detection_counts[d.get("detection_class", "Unknown")] += 1
            
        total_incidents = len(detailed_incidents)
        avg_fps = frames_processed / max(1, total_time)
        
        avg_lat = 0
        peak_cpu = 0
        peak_ram = 0
        if telemetry:
            avg_lat = sum(t.get("latency_ms", 0) for t in telemetry) / len(telemetry)
            peak_cpu = max((t.get("cpu_percent", 0) for t in telemetry), default=0)
            peak_ram = max((t.get("ram_percent", 0) for t in telemetry), default=0)

        with open(path, "w") as f:
            f.write("====================================================\n")
            f.write("        CELLWATCH OFFLINE ANALYSIS REPORT\n")
            f.write("====================================================\n\n")
            
            f.write(f"**Analysis ID:** {session_id}\n\n")
            f.write(f"**Video:** {os.path.basename(video_path)}\n\n")
            f.write(f"**Duration:** {total_time:.2f}s\n\n")
            f.write(f"**Frames Processed:** {frames_processed}\n\n")
            f.write(f"**Analysis Profile:** {profile}\n\n")
            f.write(f"**Overall Status:** COMPLETED\n\n")
            
            f.write("### Summary\n\n")
            f.write(f"Total Incidents: {total_incidents}\n\n")
            
            f.write("====================================================\n")
            f.write("Detection Summary\n")
            f.write("====================================================\n\n")
            for cls, count in detection_counts.items():
                f.write(f"**{cls}**: {count}\n\n")
                
            f.write("====================================================\n")
            f.write("Session Information\n")
            f.write("====================================================\n\n")
            f.write(f"- CPU: {fingerprint.get('cpu', 'Unknown')}\n")
            f.write(f"- GPU: {fingerprint.get('gpu', 'Unknown')}\n")
            f.write(f"- RAM: {fingerprint.get('ram', 'Unknown')}\n")
            f.write(f"- OS: {fingerprint.get('os', 'Unknown')}\n\n")
            
            f.write("====================================================\n")
            f.write("Detection Statistics\n")
            f.write("====================================================\n\n")
            f.write(f"- Average Pipeline Latency: {avg_lat:.2f}ms\n")
            f.write(f"- Average FPS: {avg_fps:.2f}\n")
            f.write(f"- Peak CPU: {peak_cpu}%\n")
            f.write(f"- Peak RAM: {peak_ram}%\n\n")
            
            f.write("====================================================\n")
            f.write("Recommendations\n")
            f.write("====================================================\n\n")
            if peak_cpu < 60:
                f.write("CPU utilization remained within stable limits. No optimization required.\n\n")
            else:
                f.write("High CPU utilization detected. Consider lowering resolution.\n\n")
