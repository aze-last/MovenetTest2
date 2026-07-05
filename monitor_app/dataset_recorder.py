"""
Dataset Recorder — Standalone multi-camera dataset collection tool.

Captures synchronized video/image data from USB, RTSP, and IP cameras
for offline annotation and model training. Zero AI dependencies.

Launched as a CTkToplevel from the main CellWatch dashboard.
"""

import os
import sys
import cv2
import json
import math
import time
import shutil
import threading
import logging
from datetime import datetime
from collections import deque

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageTk

try:
    import yaml
    def _load_config():
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                return yaml.safe_load(f) or {}
        return {}
except ImportError:
    def _load_config():
        return {}

logger = logging.getLogger("DatasetRecorder")

# ─── Palette (matches institutional design language) ─────────────────────────
PALETTE = {
    "bg":         "#06090c",
    "header":     "#0f161f",
    "card":       "#151f2b",
    "card_alt":   "#1b2430",
    "border":     "#1e2c3a",
    "accent":     "#4f84bb",
    "accent_dim": "#3a6490",
    "text":       "#f3f7fb",
    "muted":      "#a2b5c7",
    "dim":        "#637a91",
    "success":    "#50d186",
    "warning":    "#f2c94c",
    "danger":     "#f25c5c",
    "rec_red":    "#e63946",
    "rec_glow":   "#ff1a2e",
}


# ─── Camera Worker Thread ────────────────────────────────────────────────────
class CameraWorker(threading.Thread):
    """Dedicated thread for one camera: reads frames, writes video/images."""

    def __init__(self, camera_source, camera_label, session_dir, record_mode,
                 image_interval, on_frame_callback, on_stats_callback):
        super().__init__(daemon=True)
        self.camera_source = camera_source
        self.camera_label = camera_label
        self.session_dir = session_dir
        self.record_mode = record_mode
        self.image_interval = max(1, image_interval)
        self.on_frame = on_frame_callback
        self.on_stats = on_stats_callback

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()

        self.cap = None
        self.writer = None
        self.frame_count = 0
        self.dropped_frames = 0
        self.start_time_ns = 0
        self.timestamps = []
        self._width = 0
        self._height = 0
        self._fps = 30.0

    def run(self):
        src = self.camera_source
        if isinstance(src, str) and (src.startswith("rtsp://") or src.startswith("http")):
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        else:
            idx = int(src) if isinstance(src, str) and src.isdigit() else src
            self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)

        if not self.cap or not self.cap.isOpened():
            logger.warning("Camera %s failed to open.", self.camera_label)
            return

        self._width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self._fps <= 0 or self._fps > 120:
            self._fps = 30.0

        video_dir = os.path.join(self.session_dir, "videos")
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, f"{self.camera_label}.mp4")

        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        if self.record_mode in ("video", "both"):
            self.writer = cv2.VideoWriter(video_path, fourcc, self._fps,
                                          (self._width, self._height))

        img_dir = os.path.join(self.session_dir, "snapshots", self.camera_label)
        if self.record_mode in ("images", "both"):
            os.makedirs(img_dir, exist_ok=True)

        self.start_time_ns = time.perf_counter_ns()
        fps_deque = deque(maxlen=30)
        last_ui = time.time()

        while not self._stop_event.is_set():
            self._pause_event.wait()
            t0 = time.perf_counter()
            ret, frame = self.cap.read()
            if not ret:
                self.dropped_frames += 1
                time.sleep(0.005)
                continue

            self.frame_count += 1
            elapsed_ns = time.perf_counter_ns() - self.start_time_ns
            self.timestamps.append(elapsed_ns)

            if self.writer:
                self.writer.write(frame)

            if self.record_mode in ("images", "both"):
                if self.frame_count % self.image_interval == 0:
                    p = os.path.join(img_dir, f"frame_{self.frame_count:06d}.jpg")
                    cv2.imwrite(p, frame)

            dt = time.perf_counter() - t0
            fps_deque.append(dt)

            now = time.time()
            if now - last_ui >= 0.15:  # ~7fps UI updates
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil = Image.fromarray(rgb)
                    self.on_frame(self.camera_label, pil)
                except Exception:
                    pass

                avg_dt = sum(fps_deque) / len(fps_deque) if fps_deque else 1
                cfps = 1.0 / avg_dt if avg_dt > 0 else 0
                self.on_stats(self.camera_label, {
                    "fps": round(cfps, 1),
                    "frames": self.frame_count,
                    "dropped": self.dropped_frames,
                })
                last_ui = now

        if self.writer:
            self.writer.release()
        if self.cap:
            self.cap.release()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()

    def get_metadata(self):
        return {
            "source": str(self.camera_source),
            "label": self.camera_label,
            "resolution": f"{self._width}x{self._height}",
            "fps": round(self._fps, 1),
            "total_frames": self.frame_count,
            "dropped_frames": self.dropped_frames,
        }


# ─── Dataset Recorder UI ────────────────────────────────────────────────────
class DatasetRecorderDialog(ctk.CTkToplevel):
    """Standalone multi-camera dataset recorder window — matches Live Monitor layout."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Dataset Recorder")
        self.geometry("1340x820")
        self.configure(fg_color=PALETTE["bg"])
        self.minsize(1000, 650)

        cfg = _load_config().get("dataset_recorder", {})
        self.scan_max = cfg.get("camera_scan_max", 20)
        self.default_image_interval = cfg.get("image_interval", 30)
        self.base_output = cfg.get("output_dir", "DatasetRecordings")

        self.discovered_cameras = []
        self.camera_vars = {}
        self.workers = []
        self.recording = False
        self.paused = False
        self.session_dir = None
        self.session_start = None

        # Preview refs (GC protection)
        self._preview_photos = {}
        self._canvas_refs = {}
        self._stat_labels = {}
        self._canvas_image_ids = {}

        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Header Bar (like Live Monitor) ──
        self.header = ctk.CTkFrame(self, fg_color=PALETTE["header"], height=56, corner_radius=0)
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        ctk.CTkLabel(
            self.header, text="DATASET RECORDER",
            font=("Segoe UI Bold", 13), text_color=PALETTE["accent"],
        ).pack(side="left", padx=25)

        self.lbl_rec_indicator = ctk.CTkLabel(
            self.header, text="", font=("Segoe UI Bold", 13),
            text_color=PALETTE["rec_red"],
        )
        self.lbl_rec_indicator.pack(side="left", padx=(10, 0))

        # Header buttons (right side)
        self.btn_open_folder = ctk.CTkButton(
            self.header, text="📂 Open Folder", width=120, height=36,
            corner_radius=10, fg_color=PALETTE["card"],
            hover_color=PALETTE["accent_dim"], font=("Segoe UI Semibold", 11),
            text_color=PALETTE["text"], state="disabled",
            command=self._open_session_folder,
        )
        self.btn_open_folder.pack(side="right", padx=5, pady=10)

        self.btn_stop = ctk.CTkButton(
            self.header, text="⏹ Stop", width=90, height=36,
            corner_radius=10, fg_color=PALETTE["danger"],
            hover_color="#b34545", font=("Segoe UI Bold", 12),
            text_color=PALETTE["text"], state="disabled",
            command=self._stop_recording,
        )
        self.btn_stop.pack(side="right", padx=5, pady=10)

        self.btn_pause = ctk.CTkButton(
            self.header, text="⏸ Pause", width=90, height=36,
            corner_radius=10, fg_color=PALETTE["card"],
            hover_color=PALETTE["accent_dim"], font=("Segoe UI Semibold", 12),
            text_color=PALETTE["text"], state="disabled",
            command=self._toggle_pause,
        )
        self.btn_pause.pack(side="right", padx=5, pady=10)

        self.btn_start = ctk.CTkButton(
            self.header, text="●  Record", width=110, height=36,
            corner_radius=10, fg_color=PALETTE["success"],
            hover_color="#369e74", font=("Segoe UI Bold", 12),
            text_color=PALETTE["text"],
            command=self._start_recording,
        )
        self.btn_start.pack(side="right", padx=5, pady=10)

        self.btn_discover = ctk.CTkButton(
            self.header, text="⟳ Discover", width=110, height=36,
            corner_radius=10, fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_dim"], font=("Segoe UI Bold", 12),
            text_color=PALETTE["text"],
            command=self._discover_cameras,
        )
        self.btn_discover.pack(side="right", padx=5, pady=10)

        # ── Main body: left=settings panel, right=camera grid ──
        body = ctk.CTkFrame(self, fg_color=PALETTE["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0, minsize=300)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_settings_panel(body)
        self._build_camera_grid(body)

        # ── Status bar ──
        status = ctk.CTkFrame(self, fg_color=PALETTE["header"], height=28, corner_radius=0)
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)

        self.lbl_status = ctk.CTkLabel(
            status, text="Idle — Click Discover to scan cameras.",
            font=("Segoe UI", 11), text_color=PALETTE["dim"],
        )
        self.lbl_status.pack(side="left", padx=14)

        self.lbl_monitor = ctk.CTkLabel(
            status, text="", font=("Consolas", 11), text_color=PALETTE["muted"],
        )
        self.lbl_monitor.pack(side="right", padx=14)

    # ── Settings Panel (left sidebar) ────────────────────────────────────────
    def _build_settings_panel(self, parent):
        panel = ctk.CTkScrollableFrame(
            parent, width=290, fg_color=PALETTE["header"], corner_radius=0,
            scrollbar_button_color=PALETTE["card"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        # ── Camera List ──
        self._section(panel, "CAMERAS")
        self.camera_list_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self.camera_list_frame.pack(fill="x", padx=14, pady=(2, 6))

        # RTSP
        self._section(panel, "ADD RTSP / IP CAMERA")
        rtsp_row = ctk.CTkFrame(panel, fg_color="transparent")
        rtsp_row.pack(fill="x", padx=14, pady=(2, 8))
        rtsp_row.grid_columnconfigure(0, weight=1)
        self.rtsp_entry = ctk.CTkEntry(
            rtsp_row, placeholder_text="rtsp://192.168.1.x:554/stream",
            font=("Segoe UI", 11), fg_color=PALETTE["card"],
            border_color=PALETTE["border"], text_color=PALETTE["text"], height=30,
        )
        self.rtsp_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            rtsp_row, text="+", width=36, height=30,
            font=("Segoe UI Bold", 14), fg_color=PALETTE["card"],
            hover_color=PALETTE["accent_dim"], corner_radius=6,
            command=self._add_rtsp_camera,
        ).grid(row=0, column=1)

        # ── Session Notes ──
        self._section(panel, "SESSION NOTES")
        notes_card = ctk.CTkFrame(panel, fg_color=PALETTE["card"], corner_radius=10,
                                   border_width=1, border_color=PALETTE["border"])
        notes_card.pack(fill="x", padx=14, pady=(2, 8))

        self.note_fields = {}
        for field in ("Scenario", "Location", "Participants", "Lighting"):
            r = ctk.CTkFrame(notes_card, fg_color="transparent")
            r.pack(fill="x", padx=10, pady=(6, 0))
            ctk.CTkLabel(r, text=field, font=("Segoe UI", 10),
                         text_color=PALETTE["dim"]).pack(anchor="w")
            e = ctk.CTkEntry(r, font=("Segoe UI", 11), fg_color=PALETTE["bg"],
                             border_color=PALETTE["border"],
                             text_color=PALETTE["text"], height=26)
            e.pack(fill="x", pady=(1, 0))
            self.note_fields[field.lower()] = e

        ctk.CTkLabel(notes_card, text="Notes", font=("Segoe UI", 10),
                     text_color=PALETTE["dim"]).pack(anchor="w", padx=10, pady=(6, 0))
        self.notes_textbox = ctk.CTkTextbox(
            notes_card, font=("Segoe UI", 11), fg_color=PALETTE["bg"],
            border_color=PALETTE["border"], text_color=PALETTE["text"],
            height=50, corner_radius=6,
        )
        self.notes_textbox.pack(fill="x", padx=10, pady=(1, 10))

        # ── Recording Format ──
        self._section(panel, "FORMAT")
        fmt = ctk.CTkFrame(panel, fg_color="transparent")
        fmt.pack(fill="x", padx=14, pady=(2, 4))
        self.record_mode_var = ctk.StringVar(value="video")
        for val, txt in [("video", "Video"), ("images", "Images"), ("both", "Both")]:
            ctk.CTkRadioButton(
                fmt, text=txt, variable=self.record_mode_var, value=val,
                font=("Segoe UI", 11), text_color=PALETTE["text"],
                fg_color=PALETTE["accent"], hover_color=PALETTE["accent_dim"],
                border_color=PALETTE["dim"],
            ).pack(anchor="w", pady=1)

        int_row = ctk.CTkFrame(panel, fg_color="transparent")
        int_row.pack(fill="x", padx=14, pady=(2, 6))
        ctk.CTkLabel(int_row, text="Image every N frames:",
                     font=("Segoe UI", 10), text_color=PALETTE["dim"]).pack(side="left")
        self.img_interval_entry = ctk.CTkEntry(
            int_row, width=50, font=("Segoe UI", 11), fg_color=PALETTE["card"],
            border_color=PALETTE["border"], text_color=PALETTE["text"], height=26,
        )
        self.img_interval_entry.insert(0, str(self.default_image_interval))
        self.img_interval_entry.pack(side="right")

        # Options
        self._section(panel, "OPTIONS")
        self.sync_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            panel, text="Sync start (3-2-1 countdown)", variable=self.sync_var,
            font=("Segoe UI", 11), text_color=PALETTE["text"],
            fg_color=PALETTE["accent"], hover_color=PALETTE["accent_dim"],
            border_color=PALETTE["dim"],
        ).pack(anchor="w", padx=14, pady=2)

        self.grid_export_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            panel, text="Export multicam_preview.mp4", variable=self.grid_export_var,
            font=("Segoe UI", 11), text_color=PALETTE["text"],
            fg_color=PALETTE["accent"], hover_color=PALETTE["accent_dim"],
            border_color=PALETTE["dim"],
        ).pack(anchor="w", padx=14, pady=(2, 14))

    # ── Camera Grid (right side — matches Live Monitor) ──────────────────────
    def _build_camera_grid(self, parent):
        self.grid_container = ctk.CTkFrame(parent, fg_color=PALETTE["bg"], corner_radius=0)
        self.grid_container.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        # Fixed 2x2 grid (always allocated — cards don't shift)
        for c in range(2):
            self.grid_container.grid_columnconfigure(c, weight=1)
        for r in range(2):
            self.grid_container.grid_rowconfigure(r, weight=1)

        # Pre-create 4 empty slots
        self._card_frames = {}
        for slot in range(4):
            row, col = slot // 2, slot % 2
            card = ctk.CTkFrame(
                self.grid_container, fg_color=PALETTE["card"],
                corner_radius=14, border_width=1, border_color=PALETTE["border"],
            )
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            card.grid_rowconfigure(1, weight=1)
            card.grid_columnconfigure(0, weight=1)

            # Header row
            hdr = ctk.CTkFrame(card, fg_color="transparent", height=30)
            hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
            hdr.grid_propagate(False)
            hdr.grid_columnconfigure(0, weight=1)

            name_lbl = ctk.CTkLabel(hdr, text=f"SLOT {slot}",
                                     font=("Segoe UI Bold", 11),
                                     text_color=PALETTE["dim"], anchor="w")
            name_lbl.grid(row=0, column=0, sticky="w")

            stat_lbl = ctk.CTkLabel(hdr, text="",
                                     font=("Consolas", 10),
                                     text_color=PALETTE["dim"], anchor="e")
            stat_lbl.grid(row=0, column=1, sticky="e")

            # Canvas (video preview — same approach as Live Monitor)
            canvas = tk.Canvas(card, bg="black", highlightthickness=0)
            canvas.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 8))

            self._card_frames[slot] = {
                "card": card,
                "name_lbl": name_lbl,
                "stat_lbl": stat_lbl,
                "canvas": canvas,
                "cam_label": None,
            }

    # ── Helpers ──
    def _section(self, parent, text):
        ctk.CTkLabel(
            parent, text=text, font=("Segoe UI Bold", 10),
            text_color=PALETTE["dim"],
        ).pack(anchor="w", padx=14, pady=(10, 0))

    # ═══════════════════════════════════════════════════════════════════════════
    #  CAMERA DISCOVERY
    # ═══════════════════════════════════════════════════════════════════════════

    def _discover_cameras(self):
        if self.recording:
            return
        self.btn_discover.configure(state="disabled", text="Scanning...")
        self.lbl_status.configure(text="Scanning for cameras (DirectShow)...")
        threading.Thread(target=self._scan_cameras_thread, daemon=True).start()

    def _scan_cameras_thread(self):
        """Fast scan using DirectShow backend. Stops after 3 consecutive misses."""
        found = []
        consecutive_misses = 0
        for idx in range(self.scan_max):
            if consecutive_misses >= 3:
                break
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    found.append({
                        "index": idx,
                        "name": f"Camera {idx}",
                        "res": f"{w}x{h}",
                        "fps": round(fps, 1) if fps > 0 else 30.0,
                        "type": "USB",
                    })
                    cap.release()
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
            except Exception:
                consecutive_misses += 1

        rtsp_cams = [c for c in self.discovered_cameras if c.get("type") == "RTSP"]
        self.discovered_cameras = found + rtsp_cams
        self.after(0, self._update_camera_list_ui)

    def _add_rtsp_camera(self):
        url = self.rtsp_entry.get().strip()
        if not url:
            return
        idx = len(self.discovered_cameras)
        self.discovered_cameras.append({
            "index": url,
            "name": f"RTSP {idx}",
            "res": "Unknown",
            "fps": 30.0,
            "type": "RTSP",
        })
        self.rtsp_entry.delete(0, "end")
        self._update_camera_list_ui()

    def _update_camera_list_ui(self):
        for w in self.camera_list_frame.winfo_children():
            w.destroy()
        self.camera_vars.clear()

        for cam in self.discovered_cameras:
            label = cam["name"]
            var = ctk.BooleanVar(value=True)
            self.camera_vars[label] = var

            row = ctk.CTkFrame(self.camera_list_frame, fg_color=PALETTE["card"],
                               corner_radius=8, height=34)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            ctk.CTkCheckBox(
                row, text="", variable=var, width=20,
                fg_color=PALETTE["accent"], hover_color=PALETTE["accent_dim"],
                border_color=PALETTE["dim"], checkbox_height=16, checkbox_width=16,
            ).pack(side="left", padx=(6, 4))

            tc = PALETTE["accent"] if cam["type"] == "USB" else PALETTE["warning"]
            ctk.CTkLabel(
                row, text=cam["type"], font=("Segoe UI Bold", 9),
                text_color=PALETTE["bg"], fg_color=tc,
                corner_radius=4, padx=5, pady=1,
            ).pack(side="left", padx=(0, 6))

            ctk.CTkLabel(row, text=label, font=("Segoe UI", 11),
                         text_color=PALETTE["text"]).pack(side="left")
            ctk.CTkLabel(row, text=cam["res"], font=("Segoe UI", 10),
                         text_color=PALETTE["dim"]).pack(side="right", padx=8)

        self.btn_discover.configure(state="normal", text="⟳ Discover")
        n = len(self.discovered_cameras)
        self.lbl_status.configure(text=f"Found {n} camera(s). Select cameras and press Record.")

        # Assign cameras to the fixed grid slots
        self._assign_grid_slots()

    def _assign_grid_slots(self):
        """Map discovered cameras into the fixed 2x2 grid slots."""
        selected = [c for c in self.discovered_cameras
                    if self.camera_vars.get(c["name"], ctk.BooleanVar(value=False)).get()]

        for slot in range(4):
            info = self._card_frames[slot]
            if slot < len(selected):
                cam = selected[slot]
                info["name_lbl"].configure(text=cam["name"].upper(), text_color=PALETTE["accent"])
                info["stat_lbl"].configure(text=cam["res"], text_color=PALETTE["muted"])
                info["cam_label"] = cam["name"]
                info["card"].configure(border_color=PALETTE["border"])
            else:
                info["name_lbl"].configure(text=f"SLOT {slot}", text_color=PALETTE["dim"])
                info["stat_lbl"].configure(text="", text_color=PALETTE["dim"])
                info["cam_label"] = None
                info["card"].configure(border_color=PALETTE["border"])
                # Clear canvas
                info["canvas"].delete("all")

    # ═══════════════════════════════════════════════════════════════════════════
    #  RECORDING
    # ═══════════════════════════════════════════════════════════════════════════

    def _start_recording(self):
        selected = [c for c in self.discovered_cameras
                    if self.camera_vars.get(c["name"], ctk.BooleanVar(value=False)).get()]
        if not selected:
            self.lbl_status.configure(text="No cameras selected.")
            return
        self._assign_grid_slots()

        if self.sync_var.get():
            self._countdown(3, selected)
        else:
            self._begin_recording(selected)

    def _countdown(self, n, cams):
        if n <= 0:
            self._begin_recording(cams)
            return
        self.lbl_status.configure(text=f"Starting in {n}...")
        self.lbl_rec_indicator.configure(text=str(n), text_color=PALETTE["warning"])
        self.after(1000, lambda: self._countdown(n - 1, cams))

    def _begin_recording(self, selected_cams):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_name = f"Session_{ts}"
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            self.base_output)
        self.session_dir = os.path.join(base, session_name)
        os.makedirs(os.path.join(self.session_dir, "videos"), exist_ok=True)
        os.makedirs(os.path.join(self.session_dir, "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self.session_dir, "logs"), exist_ok=True)

        self.session_start = datetime.now()
        record_mode = self.record_mode_var.get()
        try:
            img_interval = int(self.img_interval_entry.get())
        except ValueError:
            img_interval = self.default_image_interval

        notes = {}
        for key, entry in self.note_fields.items():
            notes[key] = entry.get().strip()
        notes["notes"] = self.notes_textbox.get("1.0", "end").strip()

        session_meta = {
            "session_id": session_name,
            "start_time": self.session_start.isoformat(),
            "record_mode": record_mode,
            "image_interval": img_interval,
            "cameras": [{"name": c["name"], "source": str(c["index"]),
                         "type": c["type"], "resolution": c["res"]} for c in selected_cams],
            "notes": notes,
        }
        with open(os.path.join(self.session_dir, "session.json"), "w") as f:
            json.dump(session_meta, f, indent=2)

        self.workers.clear()
        for cam in selected_cams:
            w = CameraWorker(
                camera_source=cam["index"],
                camera_label=cam["name"].replace(" ", "_").lower(),
                session_dir=self.session_dir,
                record_mode=record_mode,
                image_interval=img_interval,
                on_frame_callback=self._on_worker_frame,
                on_stats_callback=self._on_worker_stats,
            )
            w.start()
            self.workers.append(w)

        self.recording = True
        self.paused = False
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self.btn_discover.configure(state="disabled")
        self.btn_open_folder.configure(state="disabled")
        self.lbl_status.configure(text=f"Recording {len(selected_cams)} camera(s)...")
        self.lbl_rec_indicator.configure(text="● REC", text_color=PALETTE["rec_red"])

        # Highlight active cards
        for slot in range(4):
            info = self._card_frames[slot]
            if info["cam_label"]:
                info["card"].configure(border_color=PALETTE["rec_red"])

        self._monitor_loop()

    def _toggle_pause(self):
        if not self.recording:
            return
        if self.paused:
            for w in self.workers:
                w.resume()
            self.paused = False
            self.btn_pause.configure(text="⏸ Pause")
            self.lbl_rec_indicator.configure(text="● REC", text_color=PALETTE["rec_red"])
            self.lbl_status.configure(text="Recording resumed.")
        else:
            for w in self.workers:
                w.pause()
            self.paused = True
            self.btn_pause.configure(text="▶ Resume")
            self.lbl_rec_indicator.configure(text="⏸ PAUSED", text_color=PALETTE["warning"])
            self.lbl_status.configure(text="Recording paused.")

    def _stop_recording(self):
        if not self.recording:
            return
        self.lbl_status.configure(text="Stopping...")
        self.recording = False
        for w in self.workers:
            w.stop()

        def _fin():
            for w in self.workers:
                w.join(timeout=5)
            self.after(0, self._finalize)

        threading.Thread(target=_fin, daemon=True).start()

    def _finalize(self):
        end_time = datetime.now()
        manifest = {
            "session_id": os.path.basename(self.session_dir),
            "start_time": self.session_start.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": round((end_time - self.session_start).total_seconds(), 2),
            "record_mode": self.record_mode_var.get(),
            "cameras": [w.get_metadata() for w in self.workers],
        }
        with open(os.path.join(self.session_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        if self.grid_export_var.get():
            threading.Thread(target=self._export_grid, args=(manifest,), daemon=True).start()

        self.workers.clear()
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸ Pause")
        self.btn_stop.configure(state="disabled")
        self.btn_discover.configure(state="normal")
        self.btn_open_folder.configure(state="normal")
        self.lbl_rec_indicator.configure(text="")
        self.lbl_status.configure(text=f"Session saved: {os.path.basename(self.session_dir)}")

        for slot in range(4):
            self._card_frames[slot]["card"].configure(border_color=PALETTE["border"])

    def _export_grid(self, manifest):
        """Stitch per-camera videos into a 2x2 grid preview."""
        try:
            vdir = os.path.join(self.session_dir, "videos")
            files = [os.path.join(vdir, f"{c['label']}.mp4") for c in manifest["cameras"]]
            files = [f for f in files if os.path.exists(f)]
            if not files:
                return

            import numpy as np
            caps = [cv2.VideoCapture(f) for f in files]
            cell_w, cell_h = 640, 480
            cols = 2
            rows = math.ceil(len(caps) / cols)
            out_w, out_h = cols * cell_w, rows * cell_h

            writer = cv2.VideoWriter(
                os.path.join(vdir, "multicam_preview.mp4"),
                cv2.VideoWriter_fourcc(*"avc1"), 25, (out_w, out_h))

            while True:
                canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
                any_ok = False
                for i, cap in enumerate(caps):
                    ret, frame = cap.read()
                    if ret:
                        any_ok = True
                        frame = cv2.resize(frame, (cell_w, cell_h))
                        r, c = i // cols, i % cols
                        y, x = r * cell_h, c * cell_w
                        canvas[y:y + cell_h, x:x + cell_w] = frame
                if not any_ok:
                    break
                writer.write(canvas)

            writer.release()
            for cap in caps:
                cap.release()
        except Exception as e:
            logger.error("Grid export failed: %s", e)

    # ── Worker callbacks (called from worker threads) ────────────────────────
    def _on_worker_frame(self, worker_label, pil_image):
        self.after(0, lambda wl=worker_label, img=pil_image: self._render_frame(wl, img))

    def _on_worker_stats(self, worker_label, stats):
        self.after(0, lambda wl=worker_label, s=stats: self._render_stats(wl, s))

    def _render_frame(self, worker_label, pil_image):
        """Draw frame onto the correct canvas — same approach as Live Monitor."""
        for slot in range(4):
            info = self._card_frames[slot]
            if info["cam_label"] and info["cam_label"].replace(" ", "_").lower() == worker_label:
                canvas = info["canvas"]
                cw = canvas.winfo_width()
                ch = canvas.winfo_height()
                if cw < 10 or ch < 10:
                    return
                pil_image = pil_image.resize((cw, ch), Image.LANCZOS)
                photo = ImageTk.PhotoImage(pil_image)
                self._preview_photos[slot] = photo  # prevent GC

                img_id = self._canvas_image_ids.get(slot)
                if img_id:
                    canvas.itemconfig(img_id, image=photo)
                else:
                    self._canvas_image_ids[slot] = canvas.create_image(
                        0, 0, anchor="nw", image=photo)
                break

    def _render_stats(self, worker_label, stats):
        for slot in range(4):
            info = self._card_frames[slot]
            if info["cam_label"] and info["cam_label"].replace(" ", "_").lower() == worker_label:
                txt = f"{stats['fps']} fps | {stats['frames']} frm | {stats['dropped']} drop"
                color = PALETTE["danger"] if stats["dropped"] > 0 else PALETTE["muted"]
                info["stat_lbl"].configure(text=txt, text_color=color)
                break

    def _monitor_loop(self):
        if not self.recording:
            return

        total_fps = 0
        total_dropped = 0
        for w in self.workers:
            elapsed = (time.perf_counter_ns() - w.start_time_ns) / 1e9 if w.start_time_ns else 0
            if elapsed > 0 and w.frame_count > 0:
                total_fps += w.frame_count / elapsed
            total_dropped += w.dropped_frames

        try:
            usage = shutil.disk_usage(self.session_dir)
            free_gb = usage.free / (1024 ** 3)
            elapsed_s = (datetime.now() - self.session_start).total_seconds()
            size = self._dir_size(self.session_dir)
            speed = (size / (1024 ** 2)) / elapsed_s if elapsed_s > 0 else 0

            disk_color = PALETTE["danger"] if free_gb < 5 else PALETTE["muted"]
            self.lbl_monitor.configure(
                text=f"FPS: {total_fps:.0f}  |  Drops: {total_dropped}  |  "
                     f"Write: {speed:.1f} MB/s  |  Disk: {free_gb:.1f} GB free",
                text_color=disk_color if free_gb < 5 else PALETTE["muted"],
            )
        except Exception:
            pass

        self.after(1000, self._monitor_loop)

    def _dir_size(self, path):
        total = 0
        try:
            for dp, _, fns in os.walk(path):
                for f in fns:
                    try:
                        total += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
        except Exception:
            pass
        return total

    def _open_session_folder(self):
        if self.session_dir and os.path.exists(self.session_dir):
            os.startfile(self.session_dir)

    def destroy(self):
        if self.recording:
            for w in self.workers:
                w.stop()
            for w in self.workers:
                w.join(timeout=3)
        super().destroy()
