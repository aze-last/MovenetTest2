import os
from datetime import datetime
from fpdf import FPDF

class PerformancePDFGenerator:
    """
    Generates a professional PDF report containing the system specs, benchmark scoring,
    waterfall latencies, camera FPS tables, and rule-based diagnostics.
    """
    @staticmethod
    def generate_report(output_path: str, manifest: dict, ai_stats: dict, camera_stats: dict, failures: dict, verdict: str, score: float, recommendations: list):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", "B", 18)
        
        # Header block
        pdf.set_fill_color(30, 44, 58) # #1e2c3a dark blue
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 15, "CellWatch AI Performance Verification Report", ln=True, align="C", fill=True)
        pdf.ln(5)
        
        # Run Summary
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        
        # Color coding verdict
        v_color = (80, 209, 134) # Green
        if "FAIL" in verdict:
            v_color = (242, 92, 92) # Red
        elif "WARNING" in verdict:
            v_color = (242, 201, 76) # Yellow
            
        pdf.set_font("helvetica", "", 11)
        pdf.cell(50, 8, "Run ID:")
        pdf.cell(100, 8, str(manifest.get("run_id")), ln=True)
        pdf.cell(50, 8, "Timestamp:")
        pdf.cell(100, 8, str(manifest.get("timestamp")), ln=True)
        pdf.cell(50, 8, "Overall Score:")
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(100, 8, f"{score}/100", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(50, 8, "Verdict:")
        pdf.set_font("helvetica", "B", 11)
        pdf.set_text_color(*v_color)
        pdf.cell(100, 8, str(verdict), ln=True)
        pdf.set_text_color(30, 30, 30)
        pdf.ln(5)
        
        # Section 1: System specs
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 10, "1. Hardware & System Specifications", ln=True)
        pdf.set_font("helvetica", "", 10)
        
        # Helper for key-value layout
        def render_spec(k, v):
            pdf.cell(50, 6, f"  * {k}:", border=0)
            pdf.cell(130, 6, str(v), border=0, ln=True)
            
        render_spec("CPU Model", manifest.get("hardware", {}).get("cpu", "N/A"))
        render_spec("GPU Model", manifest.get("hardware", {}).get("gpu", "N/A"))
        render_spec("RAM Total", f"{manifest.get('hardware', {}).get('ram_total_gb', 'N/A')} GB")
        render_spec("Host Name", manifest.get("hardware", {}).get("host_name", "N/A"))
        render_spec("Operating System", manifest.get("environment", {}).get("os", "N/A"))
        render_spec("CUDA Version", manifest.get("environment", {}).get("cuda", "N/A"))
        render_spec("Git Commit", manifest.get("git_commit", "N/A")[:10])
        render_spec("Config Signature", manifest.get("config_yaml_hash", "N/A")[:10])
        pdf.ln(5)

        # Section 2: Pipeline Latency Breakdown
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 10, "2. Pipeline Latency Breakdown (Stage-by-Stage)", ln=True)
        pdf.set_font("helvetica", "B", 10)
        
        # Latency Table Headers
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(60, 8, "Pipeline Stage", border=1, fill=True)
        pdf.cell(30, 8, "Average", border=1, fill=True)
        pdf.cell(30, 8, "Median", border=1, fill=True)
        pdf.cell(30, 8, "P95 Latency", border=1, fill=True)
        pdf.cell(30, 8, "P99 Latency", border=1, fill=True, ln=True)
        
        pdf.set_font("helvetica", "", 9)
        for stage, metrics in ai_stats.items():
            pdf.cell(60, 7, stage.capitalize(), border=1)
            pdf.cell(30, 7, f"{metrics.get('avg', 0.0)} ms", border=1)
            pdf.cell(30, 7, f"{metrics.get('median', 0.0)} ms", border=1)
            pdf.cell(30, 7, f"{metrics.get('p95', 0.0)} ms", border=1)
            pdf.cell(30, 7, f"{metrics.get('p99', 0.0)} ms", border=1, ln=True)
            
        pdf.ln(5)
        
        # Section 3: Camera Metrics
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 10, "3. Camera Feed Metrics & Telemetry", ln=True)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 8, "Camera ID", border=1, fill=True)
        pdf.cell(30, 8, "FPS", border=1, fill=True)
        pdf.cell(35, 8, "Dropped Frames", border=1, fill=True)
        pdf.cell(35, 8, "Reconnections", border=1, fill=True)
        pdf.cell(40, 8, "Avg Queue Delay", border=1, fill=True, ln=True)
        
        pdf.set_font("helvetica", "", 9)
        for cam_id, stats in camera_stats.items():
            pdf.cell(40, 7, f"Camera {cam_id}", border=1)
            pdf.cell(30, 7, f"{stats.get('fps', 0.0)}", border=1)
            pdf.cell(35, 7, f"{stats.get('dropped_frames', 0)}", border=1)
            pdf.cell(35, 7, f"{stats.get('reconnects', 0)}", border=1)
            pdf.cell(40, 7, f"{stats.get('avg_queue_delay_ms', 0.0)} ms", border=1, ln=True)
            
        pdf.ln(5)
        
        # Section 4: System Failures
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 10, "4. Stability & Exception Counters", ln=True)
        pdf.set_font("helvetica", "", 10)
        
        def render_fail_counter(label, count):
            pdf.cell(70, 6, f"  * {label}:")
            pdf.set_font("helvetica", "B" if count > 0 else "", 10)
            if count > 0:
                pdf.set_text_color(242, 92, 92)
            pdf.cell(50, 6, str(count), ln=True)
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("helvetica", "", 10)

        render_fail_counter("Camera Reconnections", failures.get("camera_reconnects", 0))
        render_fail_counter("Inference Failures", failures.get("inference_failures", 0))
        render_fail_counter("YOLO Model Load Faults", failures.get("yolo_load_failures", 0))
        render_fail_counter("MoveNet Thread Exceptions", failures.get("movenet_exceptions", 0))
        render_fail_counter("Telemetry Event Losses", failures.get("dropped_events", 0))
        render_fail_counter("Database Query Retries", failures.get("database_retries", 0))
        render_fail_counter("Video Recorder Exceptions", failures.get("recorder_failures", 0))
        pdf.ln(5)
        
        # Section 5: Recommendations
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 10, "5. Rule-Based Diagnostics & Recommendations", ln=True)
        pdf.set_font("helvetica", "", 10)
        for rec in recommendations:
            try:
                pdf.multi_cell(w=0, h=6, text=f"- {rec}")
            except TypeError:
                pdf.multi_cell(w=0, h=6, txt=f"- {rec}")
            
        # Write to file
        pdf.output(output_path)
