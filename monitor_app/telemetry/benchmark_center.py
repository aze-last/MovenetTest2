import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import time
import threading
from typing import Dict, List, Optional
import os

from monitor_app.benchmark.db import BenchmarkDBManager
from monitor_app.benchmark.comparator import BenchmarkComparator
from monitor_app.benchmark.diagnostics import PerformanceDiagnostics
from monitor_app.benchmark.__main__ import CellWatchBenchmark, BenchmarkProfile, BenchmarkState
from monitor_app.telemetry import (
    get_telemetry_engine,
    camera_collector,
    ai_collector,
    system_collector,
    queue_collector,
    health_collector
)
from monitor_app.telemetry.log_console import LogConsole
from monitor_app.utils import GlobalState
from monitor_app.logger import get_module_logger

logger = get_module_logger("Validation Center")

class ValidationCenterScreen(ctk.CTkFrame):
    """
    Validation Center Dashboard - Unified Hub for Real-time Telemetry,
    Benchmarking Control, Saved Runs Comparison, and Log Monitoring.
    """
    PALETTE = {
        "page": "#06090c",
        "panel": "#0f161f",
        "card": "#151f2b",
        "border": "#1e2c3a",
        "accent": "#4f84bb",
        "text_main": "#ffffff",
        "text_dim": "#a2b5c7",
        "success": "#50d186",
        "warning": "#f2c94c",
        "danger": "#f25c5c",
    }

    def __init__(self, parent):
        super().__init__(parent, fg_color=self.PALETTE["page"])
        self.pack(fill="both", expand=True)

        self.db = BenchmarkDBManager()
        self.benchmark_runner = CellWatchBenchmark()
        self.active_run_id = None
        self.replay_timeline: List[dict] = []
        self.replay_mode = False

        self.setup_ui()
        self.start_live_update()
        
        # Subscribe to all EventBus events to feed LogConsole
        from monitor_app.events import get_event_bus
        bus = get_event_bus()
        self._sub_callbacks = []
        for ev in ["TELEM_FRAME_READ", "TELEM_PIPELINE_COMPLETE", "TELEM_FRAME_DROPPED", 
                   "TELEM_QUEUE_TICK", "TELEM_SYSTEM_TICK", "TELEM_HEALTH_ALERT", 
                   "TELEM_BENCHMARK_STATE", "TELEM_INCIDENT_STARTED", "TELEM_DB_WRITE_COMPLETE"]:
            # Capture variable in closure using default argument
            cb = lambda payload, name=ev: self.on_event_bus_msg(name, payload)
            self._sub_callbacks.append((ev, cb))
            bus.subscribe(ev, cb)

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Header Area
        header = ctk.CTkFrame(self, fg_color=self.PALETTE["panel"], height=80, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w", padx=20, pady=10)

        ctk.CTkLabel(
            title_box,
            text="CELLWATCH SYSTEM VALIDATION & TELEMETRY CENTER",
            font=("Segoe UI Bold", 10),
            text_color=self.PALETTE["accent"]
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="Performance Characterization & Verification Platform",
            font=("Bahnschrift SemiBold", 20),
            text_color=self.PALETTE["text_main"]
        ).pack(anchor="w", pady=(2, 0))

        # Big Status Badge
        self.status_badge_frame = ctk.CTkFrame(header, fg_color="transparent")
        self.status_badge_frame.grid(row=0, column=1, sticky="e", padx=20, pady=10)

        self.lbl_status_badge = ctk.CTkLabel(
            self.status_badge_frame,
            text="LIVE STREAMING",
            font=("Segoe UI Bold", 12),
            text_color=self.PALETTE["success"],
            fg_color=self.PALETTE["card"],
            corner_radius=8,
            padx=16,
            pady=6
        )
        self.lbl_status_badge.pack(side="right")

        # 2. Main Tabs Frame
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=self.PALETTE["panel"],
            segmented_button_fg_color=self.PALETTE["card"],
            segmented_button_selected_color=self.PALETTE["accent"],
            segmented_button_selected_hover_color=self.PALETTE["border"],
            segmented_button_unselected_color=self.PALETTE["page"],
            segmented_button_unselected_hover_color=self.PALETTE["border"],
            text_color=self.PALETTE["text_main"]
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(10, 20))

        self.tab_telemetry_compare = self.tabs.add("Telemetry & Compare")
        self.tab_logs = self.tabs.add("Diagnostic Event Log")

        self.setup_telemetry_compare_tab()
        self.setup_logs_tab()

    def setup_telemetry_compare_tab(self):
        self.tab_telemetry_compare.grid_rowconfigure(0, weight=1) # Monitor
        self.tab_telemetry_compare.grid_rowconfigure(1, weight=1) # Compare
        self.tab_telemetry_compare.grid_columnconfigure(0, weight=1)

        monitor_frame = ctk.CTkFrame(self.tab_telemetry_compare, fg_color="transparent")
        monitor_frame.grid(row=0, column=0, sticky="nsew")

        compare_frame = ctk.CTkFrame(self.tab_telemetry_compare, fg_color="transparent")
        compare_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        self.setup_monitor_ui(monitor_frame)
        self.setup_compare_ui(compare_frame)

    def setup_monitor_ui(self, parent_frame):
        parent_frame.grid_columnconfigure(0, weight=3) # Cards
        parent_frame.grid_columnconfigure(1, weight=2) # Waterfall
        parent_frame.grid_rowconfigure(0, weight=1)

        left_side = ctk.CTkFrame(parent_frame, fg_color="transparent")
        left_side.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        left_side.grid_columnconfigure(0, weight=1)
        left_side.grid_rowconfigure(1, weight=1)

        # Dynamic mode controls at top
        mode_bar = ctk.CTkFrame(left_side, fg_color="transparent")
        mode_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.btn_replay_toggle = ctk.CTkButton(
            mode_bar,
            text="Switch to Replay Mode",
            width=150,
            command=self.toggle_replay_mode,
            fg_color=self.PALETTE["accent"]
        )
        self.btn_replay_toggle.pack(side="left", padx=5)

        self.run_select_replay = ctk.CTkOptionMenu(
            mode_bar,
            values=["Select Replay Session"],
            command=self.load_historical_replay,
            fg_color=self.PALETTE["card"]
        )
        self.run_select_replay.pack(side="left", padx=10)

        # Metrics cards grid
        metrics_grid = ctk.CTkFrame(left_side, fg_color="transparent")
        metrics_grid.grid(row=1, column=0, sticky="nsew")
        metrics_grid.grid_columnconfigure((0, 1), weight=1)
        
        # Configure row weights to scale responsively and set a minsize to prevent squishing
        metrics_grid.grid_rowconfigure(0, weight=1, minsize=65)
        metrics_grid.grid_rowconfigure(1, weight=1, minsize=65)
        metrics_grid.grid_rowconfigure(2, weight=1, minsize=90)

        self.cards = {}
        metric_configs = [
            ("CPU Usage", "0.0%", 0, 0),
            ("RAM Usage", "0.0 GB", 0, 1),
            ("VRAM Allocation", "0.0 MB", 1, 0),
            ("GPU Temp / Clocks", "0.0°C / 0 MHz", 1, 1),
            ("Camera Status", "0 Cams Active", 2, 0),
            ("Queue Waiting Depth", "0 frames", 2, 1)
        ]
        for name, default, r, c in metric_configs:
            card = ctk.CTkFrame(metrics_grid, fg_color=self.PALETTE["card"], corner_radius=8)
            card.grid(row=r, column=c, sticky="nsew", padx=5, pady=5)
            ctk.CTkLabel(card, text=name.upper(), font=("Segoe UI Bold", 10), text_color=self.PALETTE["text_dim"]).pack(anchor="w", padx=12, pady=(6, 0))
            
            # Use smaller font and left alignment for longer values (like Camera Status)
            font_size = 11 if name == "Camera Status" else 18
            lbl_val = ctk.CTkLabel(card, text=default, font=("Bahnschrift SemiBold", font_size), text_color=self.PALETTE["text_main"], justify="left")
            lbl_val.pack(anchor="w", padx=12, pady=(0, 6))
            self.cards[name] = lbl_val

        # Chronological Diagnostics Widget at bottom
        self.lbl_diagnostic_banner = ctk.CTkLabel(
            left_side,
            text="Diagnostics: System fully optimized.",
            font=("Segoe UI Semibold", 12),
            text_color=self.PALETTE["success"],
            fg_color=self.PALETTE["card"],
            corner_radius=6,
            height=30
        )
        self.lbl_diagnostic_banner.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        # Replay scrubbing slider
        self.slider_frame = ctk.CTkFrame(left_side, fg_color="transparent")
        self.slider_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.lbl_slider_time = ctk.CTkLabel(self.slider_frame, text="Playback Position: 0s", font=("Segoe UI", 11), text_color=self.PALETTE["text_dim"])
        self.lbl_slider_time.pack(anchor="w")
        self.timeline_slider = ctk.CTkSlider(self.slider_frame, from_=0, to=100, number_of_steps=100, command=self.on_slider_scrub, state="disabled")
        self.timeline_slider.pack(fill="x", pady=5)

        # Right Side (Waterfall charts)
        right_side = ctk.CTkFrame(parent_frame, fg_color="transparent")
        right_side.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        right_side.grid_columnconfigure(0, weight=1)
        right_side.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            right_side,
            text="PIPELINE LATENCY WATERFALL",
            font=("Segoe UI Bold", 12),
            text_color=self.PALETTE["text_main"]
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(0, 10))

        self.waterfall_frame = ctk.CTkFrame(right_side, fg_color=self.PALETTE["panel"], corner_radius=12)
        self.waterfall_frame.grid(row=1, column=0, sticky="nsew")
        self.waterfall_frame.grid_columnconfigure(1, weight=1)

        self.waterfall_bars = {}
        stages = ["Camera Read", "Motion Gate", "MoveNet", "YOLO", "Fusion", "Behavior", "Decision", "Database", "Recorder"]
        for idx, stage in enumerate(stages):
            ctk.CTkLabel(self.waterfall_frame, text=stage, font=("Segoe UI", 11), text_color=self.PALETTE["text_dim"]).grid(row=idx, column=0, sticky="w", padx=15, pady=8)
            bar = ctk.CTkProgressBar(self.waterfall_frame, fg_color=self.PALETTE["card"], progress_color=self.PALETTE["accent"])
            bar.grid(row=idx, column=1, sticky="ew", pady=8)
            bar.set(0.0)
            lbl_val = ctk.CTkLabel(self.waterfall_frame, text="0.0 ms", font=("Segoe UI Semibold", 10), text_color=self.PALETTE["text_main"])
            lbl_val.grid(row=idx, column=2, sticky="e", padx=15, pady=8)
            self.waterfall_bars[stage.lower().replace(" ", "_")] = (bar, lbl_val)

    def setup_compare_ui(self, parent_frame):
        parent_frame.grid_columnconfigure((0, 1), weight=1)
        parent_frame.grid_rowconfigure(1, weight=1)

        # Dynamic run comparison header controls
        select_bar = ctk.CTkFrame(parent_frame, fg_color="transparent")
        select_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        ctk.CTkLabel(select_bar, text="Baseline Run (A):", font=("Segoe UI Semibold", 11)).pack(side="left", padx=5)
        self.opt_run_a = ctk.CTkOptionMenu(select_bar, values=["Select Baseline"], fg_color=self.PALETTE["card"])
        self.opt_run_a.pack(side="left", padx=5)

        ctk.CTkLabel(select_bar, text="Current Run (B):", font=("Segoe UI Semibold", 11)).pack(side="left", padx=15)
        self.opt_run_b = ctk.CTkOptionMenu(select_bar, values=["Select Run"], fg_color=self.PALETTE["card"])
        self.opt_run_b.pack(side="left", padx=5)

        btn_compare = ctk.CTkButton(
            select_bar,
            text="Perform Comparison",
            fg_color=self.PALETTE["accent"],
            width=150,
            command=self.run_comparator_analysis
        )
        btn_compare.pack(side="left", padx=15)

        # Baseline locker
        btn_lock_baseline = ctk.CTkButton(
            select_bar,
            text="Lock Selected as Golden",
            fg_color=self.PALETTE["card"],
            hover_color=self.PALETTE["border"],
            width=160,
            command=self.lock_selected_golden_baseline
        )
        btn_lock_baseline.pack(side="right", padx=5)

        # Matrix output left panel
        self.compare_matrix_box = ctk.CTkTextbox(parent_frame, fg_color=self.PALETTE["card"], text_color=self.PALETTE["text_main"], font=("Consolas", 11), corner_radius=8, border_width=1, border_color=self.PALETTE["border"])
        self.compare_matrix_box.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=10)
        self.compare_matrix_box.configure(state="disabled")

        # Diagnostics output right panel
        self.compare_diag_box = ctk.CTkTextbox(parent_frame, fg_color=self.PALETTE["card"], text_color=self.PALETTE["text_main"], font=("Consolas", 11), corner_radius=8, border_width=1, border_color=self.PALETTE["border"])
        self.compare_diag_box.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=10)
        self.compare_diag_box.configure(state="disabled")

        self.populate_compare_menus()

    def setup_logs_tab(self):
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(0, weight=1)

        # Chronological Category-filtered Console Widget
        self.log_console = LogConsole(self.tab_logs)
        self.log_console.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def populate_compare_menus(self):
        try:
            history = self.db.get_run_history()
            values = [f"{r.get('display_label') or r['run_id']} ({r['timestamp'].split('T')[0]})" for r in history]
            if values:
                self.opt_run_a.configure(values=values)
                self.opt_run_b.configure(values=values)
                self.run_select_replay.configure(values=[f"{r.get('display_label') or r['run_id']} ({r.get('performance_score', 'N/A')}/100)" for r in history])
                
                self._run_mapping = {}
                for r in history:
                    disp_main = f"{r.get('display_label') or r['run_id']} ({r['timestamp'].split('T')[0]})"
                    disp_rep = f"{r.get('display_label') or r['run_id']} ({r.get('performance_score', 'N/A')}/100)"
                    self._run_mapping[disp_main] = r['run_id']
                    self._run_mapping[disp_rep] = r['run_id']
        except Exception:
            pass

    def on_event_bus_msg(self, name: str, payload: dict):
        # Format and append to log console UI widget in main thread
        t_str = time.strftime("%H:%M:%S", time.localtime())
        severity = "INFO"
        category = "SYSTEM"
        msg = f"Event published: {payload}"

        if name == "TELEM_HEALTH_ALERT":
            severity = "WARNING"
            category = "WARNING"
            msg = f"{payload.get('alert_type')} raised: {payload.get('message', '')}"
        elif name == "TELEM_FRAME_DROPPED":
            severity = "WARNING"
            category = "CAMERA"
            msg = f"Camera {payload.get('camera_id')} dropped frame due to {payload.get('reason')}"
        elif name == "TELEM_PIPELINE_COMPLETE":
            category = "AI"
            msg = f"Pipeline execution completed for frame UUID: {payload.get('frame_uuid')[:16]}..."
        elif name == "TELEM_INCIDENT_STARTED":
            severity = "ERROR"
            category = "BEHAVIOR"
            msg = f"[INCIDENT] Event {payload.get('incident_id')} started on Cam {payload.get('camera_id')} - {payload.get('event_type')}"
        elif name == "TELEM_DB_WRITE_COMPLETE":
            category = "DATABASE"
            msg = f"SQLite commit finished for event {payload.get('incident_id')} - Status: {payload.get('status')}"
        elif name == "TELEM_FRAME_READ":
            category = "CAMERA"
            msg = f"Frame read seq {payload.get('sequence_num')} from camera {payload.get('camera_id')}"

        def _gui_log():
            try:
                if self.winfo_exists() and self.log_console.winfo_exists():
                    self.log_console.add_log_entry(t_str, severity, category, "TelemetryEngine", msg)
            except Exception:
                pass
        try:
            if self.winfo_exists():
                self.after(0, _gui_log)
        except Exception:
            pass

    def toggle_replay_mode(self):
        self.replay_mode = not self.replay_mode
        if self.replay_mode:
            self.btn_replay_toggle.configure(text="Switch to Live Mode")
            self.lbl_status_badge.configure(text="REPLAY ARCHIVE", text_color=self.PALETTE["warning"])
            self.timeline_slider.configure(state="normal")
        else:
            self.btn_replay_toggle.configure(text="Switch to Live Mode")
            self.lbl_status_badge.configure(text="LIVE STREAMING", text_color=self.PALETTE["success"])
            self.timeline_slider.configure(state="disabled")
            self.active_run_id = None
            self.replay_timeline.clear()
            self.lbl_slider_time.configure(text="Playback Position: 0s")
            self.timeline_slider.set(0)

    def load_historical_replay(self, selection: str):
        run_id = getattr(self, "_run_mapping", {}).get(selection, selection.split(" ")[0])
        self.active_run_id = run_id
        try:
            self.replay_timeline = self.db.get_timeline(run_id)
            if self.replay_timeline:
                self.timeline_slider.configure(from_=0, to=len(self.replay_timeline) - 1, number_of_steps=len(self.replay_timeline))
                self.timeline_slider.set(0)
                self.on_slider_scrub(0)
        except Exception:
            pass

    def on_slider_scrub(self, value):
        if not self.replay_timeline:
            return
        idx = int(float(value))
        idx = max(0, min(idx, len(self.replay_timeline) - 1))
        
        metrics = self.replay_timeline[idx]
        self.lbl_slider_time.configure(text=f"Playback Position: {idx}s")
        
        self.cards["CPU Usage"].configure(text=f"{(metrics.get('cpu_percent') or 0.0)}%")
        self.cards["RAM Usage"].configure(text=f"{(metrics.get('ram_used_gb') or 0.0)} GB")
        self.cards["VRAM Allocation"].configure(text=f"{(metrics.get('vram_allocated_mb') or 0.0)} MB")
        self.cards["GPU Temp / Clocks"].configure(text=f"{(metrics.get('gpu_temp') or 0.0)}°C / {(metrics.get('gpu_clock_mhz') or 0.0)} MHz")
        self.cards["Queue Waiting Depth"].configure(text=f"{(metrics.get('queue_size') or 0)} frames")
        
        # Waterfall mock/rough distributions of overall P95 for scrubbing playback
        avg_lat = (metrics.get("p95_latency_ms") or metrics.get("avg_latency_ms") or 0.0)
        mock_weights = {"camera_read": 0.05, "motion_gate": 0.05, "movenet": 0.40, "yolo": 0.40, "fusion": 0.02, "behavior": 0.05, "decision": 0.01, "database": 0.01, "recorder": 0.01}
        
        for stage, (bar, label) in self.waterfall_bars.items():
            stage_lat = avg_lat * mock_weights.get(stage, 0.0)
            norm_val = min(1.0, stage_lat / 100.0)
            bar.set(norm_val)
            label.configure(text=f"{round(stage_lat, 1)} ms")

    def run_comparator_analysis(self):
        sel_a = self.opt_run_a.get()
        sel_b = self.opt_run_b.get()

        if "Select" in sel_a or "Select" in sel_b:
            return

        run_a = getattr(self, "_run_mapping", {}).get(sel_a, sel_a.split(" ")[0])
        run_b = getattr(self, "_run_mapping", {}).get(sel_b, sel_b.split(" ")[0])

        try:
            # Query db details
            manifest_a = None
            manifest_b = None
            
            history = self.db.get_run_history()
            for r in history:
                if r["run_id"] == run_a:
                    manifest_a = r
                if r["run_id"] == run_b:
                    manifest_b = r

            if not manifest_a or not manifest_b:
                return

            timeline_a = self.db.get_timeline(run_a)
            timeline_b = self.db.get_timeline(run_b)

            # Compare runs
            matrix, winner, warning = BenchmarkComparator.compare_runs(manifest_a, timeline_a, manifest_b, timeline_b)
            
            # Print side-by-side comparison text
            self.compare_matrix_box.configure(state="normal")
            self.compare_matrix_box.delete("1.0", "end")
            
            self.compare_matrix_box.insert("end", f"=== SIDE-BY-SIDE VERDICT matrix ===\n")
            if winner:
                self.compare_matrix_box.insert("end", f"Winner: {winner}\n")
            if warning:
                self.compare_matrix_box.insert("end", f"WARNING: {warning}\n")
            self.compare_matrix_box.insert("end", "\n")
            
            self.compare_matrix_box.insert("end", f"{'Metric':<30} | {'Baseline (A)':<15} | {'Current (B)':<15} | {'Delta %':<10}\n")
            self.compare_matrix_box.insert("end", "-" * 80 + "\n")
            
            for k, val in matrix.items():
                unit = val["unit"]
                baseline_str = f"{val['baseline']} {unit}"
                current_str = f"{val['current']} {unit}"
                delta_str = f"{val['delta']:+.1f}%" if val["delta"] != 0 else "0.0%"
                self.compare_matrix_box.insert("end", f"{k:<30} | {baseline_str:<15} | {current_str:<15} | {delta_str:<10}\n")
                
            self.compare_matrix_box.configure(state="disabled")

            # Perform physical resource diagnostics audit on Run B
            stats_b = self.db.get_timeline(run_b)
            # Find RSS slope roughly
            slope = 0.0
            if len(stats_b) >= 2:
                slope = (stats_b[-1]["ram_used_gb"] - stats_b[0]["ram_used_gb"]) * 1024.0 / ((stats_b[-1]["timestamp"] - stats_b[0]["timestamp"]) / 60.0)
                
            recs = PerformanceDiagnostics.audit_run(manifest_b, stats_b, {}, slope)
            
            self.compare_diag_box.configure(state="normal")
            self.compare_diag_box.delete("1.0", "end")
            self.compare_diag_box.insert("end", f"=== EXPERT SYSTEM DIAGNOSTICS AUDIT (RUN B) ===\n\n")
            for rec in recs:
                self.compare_diag_box.insert("end", f"Anomaly: {rec['issue']}\n")
                self.compare_diag_box.insert("end", f"Fix: {rec['recommendation']}\n")
                self.compare_diag_box.insert("end", "-" * 50 + "\n")
            self.compare_diag_box.configure(state="disabled")
            
        except Exception as e:
            logger.error(f"Comparator UI Error: {e}")

    def lock_selected_golden_baseline(self):
        sel = self.opt_run_a.get()
        if "Select" in sel:
            return
        run_id = getattr(self, "_run_mapping", {}).get(sel, sel.split(" ")[0])
        try:
            self.db.set_golden_baseline(run_id)
            logger.info(f"Golden baseline locked to run {sel}")
        except Exception as e:
            logger.error(f"Locker error: {e}")

    def start_live_update(self):
        def _update():
            while True:
                try:
                    if not self.winfo_exists():
                        break
                except Exception:
                    break
                if not self.replay_mode:
                    self._do_live_update()
                self._update_runner_state()
                time.sleep(1.0)

        t = threading.Thread(target=_update, daemon=True)
        t.start()

    def _update_runner_state(self):
        def _gui():
            try:
                if not self.winfo_exists():
                    return
                state = self.benchmark_runner.state
                
                if state in (BenchmarkState.COMPLETED, BenchmarkState.FAILED, BenchmarkState.IDLE):
                    self.populate_compare_menus()

                # Dynamic diagnostics banner update
                ai_stats = ai_collector.get_stats()
                yolo_p95 = ai_stats.get("yolo", {}).get("p95", 0.0)
                movenet_p95 = ai_stats.get("movenet", {}).get("p95", 0.0)
                total_latency = yolo_p95 + movenet_p95
                
                health_stats = health_collector.get_stats()
                failures = health_stats.get("failures", {})
                reconnects = failures.get("camera_reconnects", 0)
                
                if reconnects > 0:
                    self.lbl_diagnostic_banner.configure(
                        text=f"Diagnostics: Camera Network Instabilities Detected! ({reconnects} drops).",
                        text_color=self.PALETTE["danger"]
                    )
                elif total_latency > 130.0:
                    self.lbl_diagnostic_banner.configure(
                        text=f"Diagnostics: High Pipeline Latency Warning ({round(total_latency, 1)} ms). Use MoveNet Lightning.",
                        text_color=self.PALETTE["warning"]
                    )
                else:
                    self.lbl_diagnostic_banner.configure(
                        text="Diagnostics: System is running fully optimized.",
                        text_color=self.PALETTE["success"]
                    )
            except Exception:
                pass

        try:
            if self.winfo_exists():
                self.after(0, _gui)
        except Exception:
            pass

    def _do_live_update(self):
        def _gui_update():
            try:
                if not self.winfo_exists():
                    return
                # CPU/RAM/VRAM
                sys_stats = system_collector.get_stats()
                self.cards["CPU Usage"].configure(text=f"{sys_stats.get('cpu_percent', 0.0)}%")
                self.cards["RAM Usage"].configure(text=f"{sys_stats.get('ram_used_gb', 0.0)} GB")
                self.cards["VRAM Allocation"].configure(text=f"{sys_stats.get('vram_allocated_mb', 0.0)} MB")
                self.cards["GPU Temp / Clocks"].configure(text=f"{sys_stats.get('gpu_temp', 0.0)}°C / {sys_stats.get('gpu_clock_mhz', 0) or 0} MHz")
                
                # Active Cameras & per-camera FPS
                cam_stats = camera_collector.get_stats()
                active_cams_text = []
                for cam_id in sorted(cam_stats.keys()):
                    fps = cam_stats[cam_id].get("fps", 0.0)
                    active_cams_text.append(f"Cam {cam_id}: {fps} FPS")
                if not active_cams_text:
                    active_cams_text = ["0 Cams Active"]
                self.cards["Camera Status"].configure(text="\n".join(active_cams_text))
                
                # Queue size
                q_stats = queue_collector.get_stats()
                self.cards["Queue Waiting Depth"].configure(text=f"{q_stats.get('current_queue_size', 0)} frames")
                
                # Stage Latencies
                ai_stats = ai_collector.get_stats()
                for stage, (bar, label) in self.waterfall_bars.items():
                    p95_val = ai_stats.get(stage, {}).get("p95", 0.0)
                    norm_val = min(1.0, p95_val / 100.0)
                    bar.set(norm_val)
                    label.configure(text=f"{p95_val} ms")
            except Exception:
                pass
                
        try:
            if self.winfo_exists():
                self.after(0, _gui_update)
        except Exception:
            pass

    def destroy(self):
        # Unsubscribe all registered callbacks to prevent TclError and memory leaks
        from monitor_app.events import get_event_bus
        bus = get_event_bus()
        if hasattr(self, "_sub_callbacks"):
            for ev, callback in self._sub_callbacks:
                try:
                    bus.unsubscribe(ev, callback)
                except Exception:
                    pass
        super().destroy()
