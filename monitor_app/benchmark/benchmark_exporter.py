import csv
import json
import os
from typing import Dict, List, Optional

# Try to import matplotlib for charts
try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

class ResultExporter:
    """
    Exports a complete performance bundle directory containing:
    - manifest.json
    - summary.md (formatted Markdown report)
    - timeline.csv (CPU, GPU, RAM, VRAM time-series)
    - latency.csv (detailed stage timings)
    - Rendered charts in graphs/ directory.
    """
    def __init__(self, output_root: Optional[str] = None):
        if output_root is None:
            from monitor_app.utils import data_path
            self.output_root = data_path(os.path.join("runs", "benchmark_sessions"))
        else:
            self.output_root = output_root

    def export_bundle(self, 
                      manifest: dict, 
                      timeline: List[dict], 
                      ai_stats: dict, 
                      camera_stats: dict, 
                      failures: dict,
                      verdict: str,
                      score: float,
                      recommendations: List[str],
                      baseline_comparison: Optional[dict] = None) -> str:
        """Generates the benchmark report bundle."""
        run_id = manifest.get("run_id", "unknown_run")
        bundle_dir = os.path.join(self.output_root, f"Session_{run_id}")
        os.makedirs(bundle_dir, exist_ok=True)
        
        # 1. Export manifest.json
        manifest_path = os.path.join(bundle_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({**manifest, "score": score, "verdict": verdict}, f, indent=2)

        # 2. Export timeline.csv
        timeline_path = os.path.join(bundle_dir, "timeline.csv")
        self._write_timeline_csv(timeline_path, timeline)

        # 3. Export detailed latency.csv (from ai_stats raw samples if provided)
        # For simplicity, we write the stage statistics to latency.csv
        latency_path = os.path.join(bundle_dir, "latency.csv")
        self._write_latency_csv(latency_path, ai_stats)

        # 4. Generate graphs
        graphs_dir = os.path.join(bundle_dir, "graphs")
        os.makedirs(graphs_dir, exist_ok=True)
        self._generate_plots(graphs_dir, timeline, ai_stats)

        # 5. Export summary.md
        summary_path = os.path.join(bundle_dir, "summary.md")
        self._write_summary_markdown(summary_path, manifest, ai_stats, camera_stats, failures, verdict, score, recommendations, baseline_comparison)

        # 6. Export summary.pdf
        try:
            from monitor_app.benchmark.pdf_generator import PerformancePDFGenerator
            pdf_path = os.path.join(bundle_dir, "summary.pdf")
            PerformancePDFGenerator.generate_report(
                pdf_path, manifest, ai_stats, camera_stats, failures, verdict, score, recommendations
            )
        except Exception as e:
            from monitor_app.logger import get_module_logger
            get_module_logger("ResultExporter").error(f"Failed to generate PDF report: {e}")

        return bundle_dir

    def _write_timeline_csv(self, file_path: str, timeline: List[dict]):
        if not timeline:
            return
        fields = ["timestamp", "cpu_percent", "ram_used_gb", "vram_allocated_mb", "gpu_temp", "gpu_clock_mhz", "cpu_clock_mhz", "queue_size", "avg_latency_ms"]
        with open(file_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in timeline:
                # Filter to only expected fields
                filtered_row = {k: row.get(k, 0.0) for k in fields}
                writer.writerow(filtered_row)

    def _write_latency_csv(self, file_path: str, ai_stats: dict):
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Stage", "Average_ms", "Median_ms", "Min_ms", "Max_ms", "P95_ms", "P99_ms", "StdDev_ms"])
            for stage, metrics in ai_stats.items():
                writer.writerow([
                    stage,
                    metrics.get("avg", 0.0),
                    metrics.get("median", 0.0),
                    metrics.get("min", 0.0),
                    metrics.get("max", 0.0),
                    metrics.get("p95", 0.0),
                    metrics.get("p99", 0.0),
                    metrics.get("stddev", 0.0)
                ])

    def _generate_plots(self, graphs_dir: str, timeline: List[dict], ai_stats: dict):
        if not MATPLOTLIB_AVAILABLE or not timeline:
            return
            
        try:
            # Graph 1: CPU, GPU, and RAM Thermals & Usage
            times = [r["timestamp"] - timeline[0]["timestamp"] for r in timeline]
            cpu_pct = [r["cpu_percent"] for r in timeline]
            gpu_temp = [r["gpu_temp"] for r in timeline]
            
            plt.figure(figsize=(10, 5))
            plt.plot(times, cpu_pct, label="CPU %", color="blue")
            plt.plot(times, gpu_temp, label="GPU Temp (°C)", color="red")
            plt.title("System Utilisation & Thermals Over Time")
            plt.xlabel("Time (seconds)")
            plt.ylabel("Value")
            plt.legend()
            plt.grid(True)
            plt.savefig(os.path.join(graphs_dir, "cpu_gpu_thermals.png"))
            plt.close()

            # Graph 2: Stage Latency Waterfall Chart
            stages = list(ai_stats.keys())
            p95_latencies = [ai_stats[s].get("p95", 0.0) for s in stages]
            
            plt.figure(figsize=(10, 5))
            plt.barh(stages, p95_latencies, color="purple")
            plt.title("P95 Latency Per Pipeline Stage")
            plt.xlabel("Latency (ms)")
            plt.ylabel("Pipeline Stage")
            plt.tight_layout()
            plt.grid(True, axis="x")
            plt.savefig(os.path.join(graphs_dir, "stage_latency_waterfall.png"))
            plt.close()
        except Exception:
            pass  # Ensure plotting issues never fail the export flow

    def _write_summary_markdown(self, 
                                 file_path: str, 
                                 manifest: dict, 
                                 ai_stats: dict, 
                                 camera_stats: dict, 
                                 failures: dict,
                                 verdict: str, 
                                 score: float, 
                                 recommendations: List[str],
                                 baseline_comparison: Optional[dict]):
        
        md = f"""# CellWatch AI Performance Summary Report
**Run ID**: `{manifest.get("run_id")}`  
**Verdict**: `{verdict}`  
**Overall Performance Score**: `{score}/100`

---

## 1. System & Run Specifications
| Parameter | Configuration |
| --- | --- |
| **Host Name** | {manifest.get("hardware", {}).get("host_name")} |
| **CPU Model** | {manifest.get("hardware", {}).get("cpu")} |
| **GPU Model** | {manifest.get("hardware", {}).get("gpu")} |
| **RAM Total** | {manifest.get("hardware", {}).get("ram_total_gb")} GB |
| **OS Version** | {manifest.get("environment", {}).get("os")} |
| **Git Commit Hash** | `{manifest.get("git_commit")[:7] if manifest.get("git_commit") else "N/A"}` |
| **Active Profile** | {manifest.get("settings", {}).get("operator_profile")} |

---

## 2. Pipeline Latency Breakdown (Stage-by-Stage)
| Pipeline Stage | Average (ms) | Median (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- | --- |
"""
        for stage, metrics in ai_stats.items():
            md += f"| **{stage.capitalize()}** | {metrics.get('avg')} ms | {metrics.get('median')} ms | {metrics.get('p95')} ms | {metrics.get('p99')} ms |\n"
            
        md += """
---

## 3. Camera Performance & Telemetry
| Camera ID | FPS | Reconnects | Dropped Frames | Signal Loss | Avg Queue Delay |
| --- | --- | --- | --- | --- | --- |
"""
        for cam_id, stats in camera_stats.items():
            md += f"| Camera {cam_id} | {stats.get('fps')} FPS | {stats.get('reconnects')} | {stats.get('dropped_frames')} | {stats.get('signal_lost')} | {stats.get('avg_queue_delay_ms')} ms |\n"

        md += """
---

## 4. Pipeline Failures & Stability Indicators
- **Camera Reconnection Events**: {camera_reconnects}
- **Inference Crashes**: {inference_failures}
- **YOLO Model Load Faults**: {yolo_load_failures}
- **MoveNet Thread Exceptions**: {movenet_exceptions}
- **Telemetry Event Losses**: {dropped_events}
- **Database Query Retries**: {database_retries}
- **Video Recorder Failures**: {recorder_failures}
""".format(**failures)

        if baseline_comparison:
            md += """
---

## 5. Regression Analysis (vs. Golden Baseline)
| Metric | Golden Baseline | Current Run | Delta % |
| --- | --- | --- | --- |
"""
            for metric_name, comp in baseline_comparison.items():
                md += f"| **{metric_name}** | {comp.get('baseline')} | {comp.get('current')} | {comp.get('delta'):+.2f}% |\n"

        md += "\n--- \n\n## 6. System Diagnostics & Recommendations\n"
        for rec in recommendations:
            md += f"- **{rec}**\n"
            
        with open(file_path, "w") as f:
            f.write(md)
