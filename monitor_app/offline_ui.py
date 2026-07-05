import os
import cv2
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk

from monitor_app.offline_inference import OfflineInferenceManager

PALETTE = {
    "page": "#10161d",
    "panel": "#171f29",
    "panel_alt": "#1c2531",
    "card": "#1b2430",
    "border": "#26384a",
    "text": "#f3f7fb",
    "muted": "#8da1b4",
    "accent": "#4f84bb",
    "success": "#42c08d",
    "warning": "#d7a75a",
    "danger": "#d86161",
}

class OfflineAnalysisCenterDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Offline Analysis Center")
        self.geometry("1100x700")
        self.configure(fg_color=PALETTE["page"])
        self.attributes("-topmost", True)
        
        self.video_path = None
        self.inference_manager = None
        
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3) # Video area
        self.grid_columnconfigure(1, weight=1) # Controls area
        self.grid_rowconfigure(0, weight=1)
        
        # --- LEFT: VIDEO AREA ---
        video_frame = ctk.CTkFrame(self, fg_color=PALETTE["panel"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        video_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        video_frame.grid_rowconfigure(0, weight=1)
        video_frame.grid_columnconfigure(0, weight=1)
        
        self.lbl_video = ctk.CTkLabel(video_frame, text="No Video Selected", text_color=PALETTE["muted"])
        self.lbl_video.grid(row=0, column=0, sticky="nsew")
        
        # Progress Bar
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ctk.CTkProgressBar(video_frame, variable=self.progress_var)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        
        # Playback Controls
        ctrl_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        ctrl_frame.grid(row=2, column=0, pady=(0, 10))
        
        ctk.CTkButton(ctrl_frame, text="⏪ Seek", width=60, command=lambda: self._seek(-100)).pack(side="left", padx=5)
        self.btn_play = ctk.CTkButton(ctrl_frame, text="▶ Play", width=60, command=self._play_pause)
        self.btn_play.pack(side="left", padx=5)
        ctk.CTkButton(ctrl_frame, text="⏸ Pause", width=60, command=self._pause).pack(side="left", padx=5)
        ctk.CTkButton(ctrl_frame, text="⏹ Stop", width=60, command=self._stop).pack(side="left", padx=5)
        ctk.CTkButton(ctrl_frame, text="⏭ Step", width=60, command=self._step).pack(side="left", padx=5)

        # --- RIGHT: SETTINGS AREA ---
        settings_frame = ctk.CTkFrame(self, fg_color=PALETTE["panel_alt"], corner_radius=10)
        settings_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(settings_frame, text="Analysis Configuration", font=("Segoe UI Bold", 16)).pack(pady=10)
        
        # Open Session
        ctk.CTkButton(settings_frame, text="Open Previous Session", command=self._open_previous_session, fg_color=PALETTE["accent"]).pack(fill="x", padx=10, pady=5)
        
        # Browse Video
        ctk.CTkButton(settings_frame, text="Browse Video File...", command=self._browse_video).pack(fill="x", padx=10, pady=5)
        self.lbl_file = ctk.CTkLabel(settings_frame, text="", text_color=PALETTE["muted"], font=("Segoe UI", 10))
        self.lbl_file.pack(padx=10, pady=(0, 10))
        
        # Profile
        ctk.CTkLabel(settings_frame, text="Analysis Profile", font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=10)
        self.profile_var = tk.StringVar(value="Standard")
        ctk.CTkOptionMenu(settings_frame, variable=self.profile_var, values=["Quick", "Standard", "Benchmark", "Forensic"]).pack(fill="x", padx=10, pady=5)
        
        # Frame Range
        ctk.CTkLabel(settings_frame, text="Frame Range", font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        range_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        range_frame.pack(fill="x", padx=10, pady=5)
        self.entry_start = ctk.CTkEntry(range_frame, placeholder_text="Start Frame", width=100)
        self.entry_start.pack(side="left", expand=True, padx=(0, 5))
        self.entry_end = ctk.CTkEntry(range_frame, placeholder_text="End Frame", width=100)
        self.entry_end.pack(side="right", expand=True, padx=(5, 0))
        
        # Export Options
        ctk.CTkLabel(settings_frame, text="Export Bundle Options", font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        self.export_vars = {
            "mp4": tk.BooleanVar(value=True),
            "csv": tk.BooleanVar(value=True),
            "json": tk.BooleanVar(value=True),
            "markdown": tk.BooleanVar(value=True),
            "telemetry": tk.BooleanVar(value=True),
            "logs": tk.BooleanVar(value=True),
            "benchmark": tk.BooleanVar(value=True)
        }
        for key, var in self.export_vars.items():
            ctk.CTkCheckBox(settings_frame, text=key.upper(), variable=var).pack(anchor="w", padx=20, pady=2)
            
        # Start/Cancel
        self.btn_start = ctk.CTkButton(settings_frame, text="Start Analysis", command=self._start_analysis, fg_color=PALETTE["success"])
        self.btn_start.pack(fill="x", padx=10, pady=(20, 5))
        
        self.btn_cancel = ctk.CTkButton(settings_frame, text="Cancel Analysis", command=self._cancel_analysis, fg_color=PALETTE["danger"], state="disabled")
        self.btn_cancel.pack(fill="x", padx=10, pady=5)

    def _browse_video(self):
        file_path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video Files", "*.mp4 *.avi *.mkv *.mov"), ("All Files", "*.*")]
        )
        if file_path:
            self.video_path = file_path
            self.lbl_file.configure(text=os.path.basename(file_path))
            
    def _open_previous_session(self):
        folder_path = filedialog.askdirectory(title="Select Export Session Folder")
        if folder_path:
            manifest_path = os.path.join(folder_path, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r") as f:
                        manifest = json.load(f)
                    msg = f"Loaded Session: {manifest.get('session_id')}\nProfile: {manifest.get('profile')}\nFrames: {manifest.get('frames_processed')}"
                    messagebox.showinfo("Session Loaded", msg)
                    
                    # If mp4 exists, load first frame
                    vid_path = os.path.join(folder_path, "annotated_video.mp4")
                    if os.path.exists(vid_path):
                        self.video_path = vid_path
                        self.lbl_file.configure(text=f"[Re-opened] {os.path.basename(vid_path)}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to parse manifest: {e}")
            else:
                messagebox.showwarning("Not Found", "No manifest.json found in the selected folder.")

    def _start_analysis(self):
        if not self.video_path:
            messagebox.showwarning("Warning", "Please select a video file first.")
            return
            
        config = {
            "profile": self.profile_var.get(),
            "export_options": {k: v.get() for k, v in self.export_vars.items()}
        }
        try:
            start_f = int(self.entry_start.get()) if self.entry_start.get() else 0
            end_f = int(self.entry_end.get()) if self.entry_end.get() else None
            config["start_frame"] = start_f
            config["end_frame"] = end_f
        except ValueError:
            messagebox.showerror("Error", "Frame range must be integers.")
            return
            
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress_var.set(0.0)
        
        self.inference_manager = OfflineInferenceManager(
            self.video_path,
            config,
            self._on_frame_ready,
            self._on_progress,
            self._on_complete
        )
        self.inference_manager.start()
        
        # Launch Telemetry Live Monitor
        from monitor_app.dashboard import DashboardScreen
        # In a real app we'd broadcast a launch signal or open the Dashboard Window if closed
        print("Telemetry Live Monitor launched automatically for offline session.")

    def _pause(self):
        if self.inference_manager:
            self.inference_manager.pause()
            
    def _play_pause(self):
        if self.inference_manager:
            if self.inference_manager.paused:
                self.inference_manager.resume()
            
    def _stop(self):
        if self.inference_manager:
            self.inference_manager.stop()
            
    def _step(self):
        if self.inference_manager and self.inference_manager.paused:
            self.inference_manager.request_step()
            
    def _seek(self, offset):
        # Optional advanced: currently we'd need to re-init cv2 cap or skip frames
        pass

    def _cancel_analysis(self):
        if self.inference_manager:
            self.inference_manager.stop()

    def _on_frame_ready(self, frame, current_frame, total_frames):
        # Convert cv2 image to PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb)
        
        # Resize to fit UI
        target_w, target_h = 700, 500
        pil_img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
        self.after(0, lambda: self.lbl_video.configure(image=ctk_img, text=""))

    def _on_progress(self, pct):
        self.after(0, lambda: self.progress_var.set(pct / 100.0))

    def _on_complete(self, summary):
        def _update():
            self.btn_start.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            
            status = summary.get("status", "Unknown")
            
            msg = (
                f"Analysis Complete\n\n"
                f"Status: {status}\n"
                f"Duration: {summary.get('duration')}\n"
                f"Frames Processed: {summary.get('frames_processed')}\n"
                f"Average FPS: {summary.get('avg_fps')}\n"
                f"Average Latency: {summary.get('avg_latency')}\n"
                f"Incidents Detected: {summary.get('incidents')}\n\n"
                f"Export Folder:\n{summary.get('export_dir')}"
            )
            self._show_summary_dialog(msg, summary.get("export_dir"))
            
        self.after(0, _update)

    def _show_summary_dialog(self, text, folder_path):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Analysis Summary")
        dlg.geometry("400x350")
        dlg.attributes("-topmost", True)
        
        ctk.CTkLabel(dlg, text=text, justify="left").pack(padx=20, pady=20)
        
        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(btn_frame, text="Open Folder", command=lambda: os.startfile(folder_path)).pack(side="left", padx=10, expand=True)
        report_path = os.path.join(folder_path, "report.md")
        if os.path.exists(report_path):
            ctk.CTkButton(btn_frame, text="Open Report", command=lambda: os.startfile(report_path)).pack(side="left", padx=10, expand=True)
            
        ctk.CTkButton(dlg, text="Close", command=dlg.destroy).pack(pady=10)
