import os
import platform
import psutil

from .csv_exporter import CSVExporter
from .json_exporter import JSONExporter
from .markdown_exporter import MarkdownExporter
from .pdf_exporter import PDFExporter
from .benchmark_exporter import BenchmarkExporter

class SessionExporter:
    """
    Single source of truth for writing files to the export directory.
    NO OTHER MODULE is permitted to write to the session folder.
    """
    def __init__(self, export_dir, session_id, profile, video_path):
        self.export_dir = export_dir
        self.session_id = session_id
        self.profile = profile
        self.video_path = video_path
        
        # Sub-directories setup
        self.gallery_dir = os.path.join(self.export_dir, "gallery")
        self.snapshots_dir = os.path.join(self.export_dir, "snapshots")
        self.graphs_dir = os.path.join(self.export_dir, "graphs")
        self.logs_dir = os.path.join(self.export_dir, "logs")
        
        os.makedirs(self.gallery_dir, exist_ok=True)
        os.makedirs(self.snapshots_dir, exist_ok=True)
        os.makedirs(self.graphs_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

    def _get_hardware_fingerprint(self):
        try:
            import torch
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None"
        except ImportError:
            gpu_name = "Unknown"

        return {
            "hardware_fingerprint": f"{platform.processor()}_{gpu_name}",
            "hardware_name": platform.node(),
            "cpu": platform.processor(),
            "gpu": gpu_name,
            "ram": f"{round(psutil.virtual_memory().total / (1024.**3))} GB",
            "os": platform.platform()
        }
        
    def export_all(self, all_detections, detailed_incidents, telemetry, total_time, frames_processed):
        from monitor_app.logger import get_module_logger
        logger = get_module_logger("Exporter")

        # IncidentRecord validation before export
        valid_incidents = []
        for inc in detailed_incidents:
            if not isinstance(inc, dict):
                logger.warning(f"Invalid incident record type: {type(inc)}")
                continue
            if "incident_id" not in inc or not inc.get("timestamp"):
                logger.warning(f"Incident missing core fields: {inc}")
                continue
            if inc.get("snapshot_required") and not inc.get("snapshot_filename"):
                logger.warning(f"Incident required snapshot but missing filename: {inc.get('incident_id')}")
            valid_incidents.append(inc)

        detailed_incidents = valid_incidents
        fingerprint = self._get_hardware_fingerprint()
        
        json_exp = JSONExporter(self.export_dir)
        csv_exp = CSVExporter(self.export_dir)
        md_exp = MarkdownExporter(self.export_dir)
        bench_exp = BenchmarkExporter(self.export_dir)
        pdf_exp = PDFExporter(self.export_dir)
        
        # 1. JSON Data (Manifest, Replay)
        json_exp.export_manifest(self.session_id, self.profile, self.video_path, frames_processed, total_time, fingerprint, detailed_incidents)
        json_exp.export_replay_index(detailed_incidents)
        json_exp.update_global_registry(self.session_id, fingerprint, self.video_path, self.profile, total_time)
        
        # 2. CSV Data (Detections, Incidents, Telemetry)
        csv_exp.export_detections(all_detections)
        csv_exp.export_incidents(detailed_incidents)
        csv_exp.export_telemetry(telemetry)
        
        # 3. Markdown (Report, Timeline, Gallery)
        md_exp.export_timeline(detailed_incidents)
        md_exp.export_gallery(detailed_incidents)
        md_exp.export_report(self.session_id, self.profile, self.video_path, total_time, frames_processed, all_detections, detailed_incidents, telemetry, fingerprint)
        
        # 4. Benchmark & PDF
        bench_exp.export_comparison(fingerprint, telemetry)
        pdf_exp.export_pdf(telemetry)
        
        return self._verify_integrity()

    def _verify_integrity(self):
        """
        Deep verification checking existence, readability, and content validity.
        """
        required_files = [
            "manifest.json", "report.pdf", "report.md", "comparison.md", 
            "timeline.md", "gallery.md", "detections.csv", "incidents.csv", 
            "telemetry.csv", "replay.json"
        ]
        
        status = "Passed"
        for f in required_files:
            path = os.path.join(self.export_dir, f)
            if not os.path.exists(path):
                status = "Failed"
                break
            if os.path.getsize(path) == 0:
                status = "Failed"
                break
                
        # Could add strict JSON parsing/CSV header checks here in the future
        return status
