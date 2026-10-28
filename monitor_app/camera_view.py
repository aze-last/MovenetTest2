import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
import monitor_app.utils as utils
from monitor_app import profile_store
import threading
import queue
import time
from monitor_app.incident_record import IncidentRecorder
from monitor_app.evidence import EvidencePacket
from monitor_app.logger import get_module_logger

logger = get_module_logger("Camera Feed")

# OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    print("OpenCV Import Error. Camera features disabled.")
    CV2_AVAILABLE = False
    cv2 = None

# AI engines (import module so we can access engines and YOLO flags)
try:
    import monitor_app.ai_engine as ai
    from monitor_app.ai_engine import BasicMotionEngine, MotionOptimizedEngine
    AI_AVAILABLE = True
except Exception as e:
    print(f"AI Engine Import Error: {e}")
    ai = None
    BasicMotionEngine = None
    MotionOptimizedEngine = None
    AI_AVAILABLE = False

# Global engines (shared across feeds)
_pose_engine = None
_yolo_engine = None


class LocalMotionGater:
    """
    Perform local, lock-free, CPU-based motion check
    that mirrors the original MotionOptimizedEngine gating parameters.
    """
    def __init__(self):
        self.update_profile()
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=30, detectShadows=False
        )
        self.last_gray = None
        
        # Subscribe to profile updates
        try:
            from monitor_app.events import get_event_bus
            get_event_bus().subscribe("AI_PROFILE_CHANGED", self._on_profile_event)
        except Exception:
            pass

    def update_profile(self, profile=None, custom_vals=None):
        if profile is None:
            ai_cfg = profile_store.get_ai_settings()
            profile = ai_cfg.get("active_profile", "medium")
            custom_vals = ai_cfg.get("custom_settings") if profile == "custom" else None
        
        # Set parameters based on sensitivity
        if profile == "high":
            self.motion_threshold = 1200
            self.motion_ratio = 0.005
        elif profile == "low":
            self.motion_threshold = 3000
            self.motion_ratio = 0.012
        elif profile == "custom" and custom_vals:
            self.motion_threshold = int(custom_vals.get("motion_threshold", 1800))
            self.motion_ratio = float(custom_vals.get("motion_ratio", 0.008))
        else: # medium (default)
            self.motion_threshold = 1800
            self.motion_ratio = 0.008

    def _on_profile_event(self, profile="medium", custom_values=None, **kwargs):
        self.update_profile(profile, custom_values)

    def detect_motion(self, frame):
        if not CV2_AVAILABLE:
            return False, 0.0
            
        frame_h, frame_w = frame.shape[:2]
        adaptive_threshold = max(self.motion_threshold, int(frame_h * frame_w * self.motion_ratio))
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (15, 15), 0)
        mask = self.bg_subtractor.apply(gray)
        score = cv2.countNonZero(mask)

        if self.last_gray is not None:
            diff = cv2.absdiff(self.last_gray, gray)
            _, t = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            score = max(score, cv2.countNonZero(t))

        self.last_gray = gray
        return score > adaptive_threshold, score


class CameraManagementDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_refresh):
        super().__init__(parent)
        self.title("Manage Camera Network - BJMP Institutional Monitor")
        self.geometry("880x680")
        self.minsize(820, 620)
        self.on_refresh = on_refresh
        self.after(200, lambda: self.focus_force())
        
        # Adaptive Institutional Palette (Light / Dark mode compatible)
        self.PALETTE = {
            "page": ("#f1f5f9", "#0b0f14"),
            "card": ("#ffffff", "#131b24"),
            "card_subtle": ("#f8fafc", "#182330"),
            "border": ("#cbd5e1", "#223244"),
            "accent": ("#1d4ed8", "#4f84bb"),
            "accent_hover": ("#1e40af", "#426f9b"),
            "text": ("#0f172a", "#f1f5f9"),
            "muted": ("#64748b", "#8fa2b4"),
            "subtle": ("#94a3b8", "#5d7185"),
            "success": ("#16a34a", "#42c08d"),
            "warning": ("#d97706", "#d7a75a"),
            "danger": ("#dc2626", "#e05252"),
        }
        
        self.configure(fg_color=self.PALETTE["page"])
        self.selected_cam_id = None
        self._is_testing_connection = False

        # Form variables
        self.name_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.protocol_var = tk.StringVar(value="RTSP")
        self.ip_var = tk.StringVar()
        self.port_var = tk.StringVar(value="554")
        self.path_var = tk.StringVar(value="/stream1")
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.show_pass_var = tk.BooleanVar(value=False)
        self.preset_var = tk.StringVar(value="Custom")
        
        self._build_ui()
        self._apply_appearance()
        self._load_cameras()
        self._scan_local_cameras()

    def _build_ui(self):
        # 1. Header Toolbar
        header = ctk.CTkFrame(self, fg_color=self.PALETTE["card"], corner_radius=0, height=58)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        hdr_left = ctk.CTkFrame(header, fg_color="transparent")
        hdr_left.pack(side="left", padx=20, fill="y")

        ctk.CTkLabel(
            hdr_left,
            text="CAMERA INFRASTRUCTURE & VMS MANAGER",
            font=("Segoe UI Bold", 14),
            text_color=self.PALETTE["accent"]
        ).pack(anchor="w", pady=(10, 0))

        ctk.CTkLabel(
            hdr_left,
            text="Configure RTSP Network Streams & DirectShow USB Feeds",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["muted"]
        ).pack(anchor="w")

        # Capacity badge
        self.lbl_capacity_badge = ctk.CTkLabel(
            header,
            text="0 / 4 CHANNELS CONFIGURED",
            font=("Segoe UI Bold", 11),
            fg_color=self.PALETTE["card_subtle"],
            text_color=self.PALETTE["accent"],
            corner_radius=6,
            padx=12,
            pady=6
        )
        self.lbl_capacity_badge.pack(side="right", padx=20, pady=12)

        # 2. Bottom Action Footer
        footer = ctk.CTkFrame(self, fg_color=self.PALETTE["card"], corner_radius=0, height=54)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkLabel(
            footer,
            text="Optimized for Windows Laptop · NVIDIA RTX 2050 (Target: 20–30 FPS with MoveNet & YOLO)",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["subtle"]
        ).pack(side="left", padx=20)

        self.btn_back = ctk.CTkButton(
            footer,
            text="Close & Apply to Feeds",
            height=36,
            corner_radius=8,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            font=("Segoe UI Semibold", 12),
            command=self.close_and_refresh
        )
        self.btn_back.pack(side="right", padx=20, pady=9)

        # 3. Main Two-Column Master-Detail Body
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=14)
        main.grid_columnconfigure(0, weight=4, minsize=320)
        main.grid_columnconfigure(1, weight=5, minsize=440)
        main.grid_rowconfigure(0, weight=1)

        # ==========================================
        # LEFT COLUMN: Channel Inventory (Master)
        # ==========================================
        left_card = ctk.CTkFrame(main, fg_color=self.PALETTE["card"], corner_radius=12, border_width=1, border_color=self.PALETTE["border"])
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_card.grid_rowconfigure(1, weight=1)
        left_card.grid_columnconfigure(0, weight=1)

        # Left Header
        left_top = ctk.CTkFrame(left_card, fg_color="transparent")
        left_top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        
        ctk.CTkLabel(
            left_top,
            text="CONFIGURED INPUTS",
            font=("Segoe UI Bold", 12),
            text_color=self.PALETTE["text"]
        ).pack(side="left")

        ctk.CTkLabel(
            left_top,
            text="(Click to edit)",
            font=("Segoe UI", 10),
            text_color=self.PALETTE["muted"]
        ).pack(side="left", padx=6)

        # Treeview in Left Column
        tree_container = ctk.CTkFrame(left_card, fg_color="transparent")
        tree_container.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Cams.Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Cams.Treeview.Heading", font=("Segoe UI Bold", 10))

        self.tree = ttk.Treeview(
            tree_container,
            columns=("id", "name", "type", "source"),
            show="headings",
            style="Cams.Treeview",
            selectmode="browse"
        )
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="CAMERA NAME")
        self.tree.heading("type", text="TYPE")
        self.tree.heading("source", text="SOURCE / URI")

        self.tree.column("id", width=36, anchor="center")
        self.tree.column("name", width=120, anchor="w")
        self.tree.column("type", width=54, anchor="center")
        self.tree.column("source", width=150, anchor="w")

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Left Action Toolbar (Add / Delete)
        left_bot = ctk.CTkFrame(left_card, fg_color="transparent")
        left_bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 12))

        self.btn_new = ctk.CTkButton(
            left_bot,
            text="+ New Channel",
            height=32,
            corner_radius=8,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            font=("Segoe UI Semibold", 11),
            command=self._clear_form
        )
        self.btn_new.pack(side="left", padx=(0, 6))

        self.btn_del = ctk.CTkButton(
            left_bot,
            text="Delete",
            height=32,
            corner_radius=8,
            fg_color=self.PALETTE["card_subtle"],
            hover_color=self.PALETTE["danger"],
            text_color=self.PALETTE["danger"],
            border_width=1,
            border_color=self.PALETTE["border"],
            font=("Segoe UI Semibold", 11),
            command=self._delete_camera
        )
        self.btn_del.pack(side="left")

        self.btn_renumber = ctk.CTkButton(
            left_bot,
            text="Renumber (1..N)",
            height=32,
            corner_radius=8,
            fg_color=self.PALETTE["card_subtle"],
            hover_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
            border_width=1,
            border_color=self.PALETTE["border"],
            font=("Segoe UI Semibold", 11),
            command=self._renumber_cameras
        )
        self.btn_renumber.pack(side="right")

        # ==========================================
        # RIGHT COLUMN: Stream Configuration (Detail)
        # ==========================================
        right_card = ctk.CTkFrame(main, fg_color=self.PALETTE["card"], corner_radius=12, border_width=1, border_color=self.PALETTE["border"])
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_card.grid_columnconfigure(0, weight=1)
        right_card.grid_rowconfigure(1, weight=1)

        # Right Header (Status Banner)
        right_top = ctk.CTkFrame(right_card, fg_color="transparent")
        right_top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))

        self.lbl_detail_title = ctk.CTkLabel(
            right_top,
            text="CHANNEL CONFIGURATION",
            font=("Segoe UI Bold", 13),
            text_color=self.PALETTE["text"]
        )
        self.lbl_detail_title.pack(side="left")

        self.lbl_channel_tag = ctk.CTkLabel(
            right_top,
            text="NEW CHANNEL",
            font=("Segoe UI Bold", 10),
            fg_color=self.PALETTE["card_subtle"],
            text_color=self.PALETTE["muted"],
            corner_radius=6,
            padx=8,
            pady=3
        )
        self.lbl_channel_tag.pack(side="right")

        # Right Form Scrollable Container
        form_scroll = ctk.CTkScrollableFrame(right_card, fg_color="transparent")
        form_scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=0)
        form_scroll.grid_columnconfigure(0, weight=1)

        # 1. Camera Name
        ctk.CTkLabel(form_scroll, text="Camera Name / Sector", font=("Segoe UI Semibold", 11), text_color=self.PALETTE["muted"]).pack(anchor="w", pady=(4, 2))
        self.entry_name = ctk.CTkEntry(
            form_scroll,
            textvariable=self.name_var,
            placeholder_text="e.g. CAM 01 - Cell Block A East",
            height=34,
            corner_radius=8,
            border_color=self.PALETTE["border"]
        )
        self.entry_name.pack(fill="x", pady=(0, 10))

        # 2. Protocol Mode Toggle (RTSP vs Local USB)
        proto_bar = ctk.CTkFrame(form_scroll, fg_color="transparent")
        proto_bar.pack(fill="x", pady=(0, 8))
        
        ctk.CTkLabel(proto_bar, text="Stream Source Protocol", font=("Segoe UI Semibold", 11), text_color=self.PALETTE["muted"]).pack(side="left")
        
        self.proto_segmented = ctk.CTkSegmentedButton(
            proto_bar,
            values=["RTSP Stream", "USB Webcam"],
            command=self._on_protocol_change,
            height=28,
            corner_radius=6,
            font=("Segoe UI Semibold", 11),
            selected_color=self.PALETTE["accent"],
            selected_hover_color=self.PALETTE["accent_hover"]
        )
        self.proto_segmented.set("RTSP Stream")
        self.proto_segmented.pack(side="right")

        # 3. RTSP Configuration Group
        self.rtsp_card = ctk.CTkFrame(form_scroll, fg_color=self.PALETTE["card_subtle"], corner_radius=10, border_width=1, border_color=self.PALETTE["border"])
        self.rtsp_card.pack(fill="x", pady=(0, 10))
        self.rtsp_card.grid_columnconfigure((0, 1, 2), weight=1)

        # RTSP Vendor Preset
        preset_row = ctk.CTkFrame(self.rtsp_card, fg_color="transparent")
        preset_row.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(preset_row, text="Vendor URI Preset:", font=("Segoe UI Semibold", 10), text_color=self.PALETTE["muted"]).pack(side="left", padx=(0, 8))
        self.preset_menu = ctk.CTkOptionMenu(
            preset_row,
            values=[
                "Custom Path",
                "TP-Link / Tapo (/stream1)",
                "Hikvision (/Streaming/Channels/101)",
                "Dahua (/cam/realmonitor?channel=1&subtype=0)",
                "Generic ONVIF (/live/ch0)"
            ],
            variable=self.preset_var,
            command=self._on_preset_selected,
            height=28,
            corner_radius=6,
            font=("Segoe UI", 11),
            fg_color=self.PALETTE["border"],
            button_color=self.PALETTE["accent"],
            button_hover_color=self.PALETTE["accent_hover"],
            text_color=self.PALETTE["text"]
        )
        self.preset_menu.pack(side="left", fill="x", expand=True)

        # Credentials Row
        creds_grid = ctk.CTkFrame(self.rtsp_card, fg_color="transparent")
        creds_grid.pack(fill="x", padx=12, pady=4)
        creds_grid.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(creds_grid, text="RTSP Username", font=("Segoe UI", 10), text_color=self.PALETTE["muted"]).grid(row=0, column=0, sticky="w", padx=2)
        self.entry_user = ctk.CTkEntry(creds_grid, textvariable=self.user_var, placeholder_text="Username", height=30, corner_radius=6)
        self.entry_user.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(2, 6))

        pass_lbl_frame = ctk.CTkFrame(creds_grid, fg_color="transparent")
        pass_lbl_frame.grid(row=0, column=1, sticky="ew", padx=2)
        ctk.CTkLabel(pass_lbl_frame, text="RTSP Password", font=("Segoe UI", 10), text_color=self.PALETTE["muted"]).pack(side="left")
        
        self.btn_toggle_pass = ctk.CTkCheckBox(
            pass_lbl_frame,
            text="Show",
            variable=self.show_pass_var,
            command=self._toggle_password_mask,
            font=("Segoe UI", 10),
            checkbox_width=16,
            checkbox_height=16,
            text_color=self.PALETTE["muted"]
        )
        self.btn_toggle_pass.pack(side="right")

        self.entry_pass = ctk.CTkEntry(creds_grid, textvariable=self.pass_var, placeholder_text="Password", height=30, corner_radius=6, show="•")
        self.entry_pass.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(2, 6))

        # Host, Port, Path Grid
        addr_grid = ctk.CTkFrame(self.rtsp_card, fg_color="transparent")
        addr_grid.pack(fill="x", padx=12, pady=(0, 10))
        addr_grid.grid_columnconfigure(0, weight=3)
        addr_grid.grid_columnconfigure(1, weight=1)
        addr_grid.grid_columnconfigure(2, weight=2)

        ctk.CTkLabel(addr_grid, text="IP / Hostname", font=("Segoe UI", 10), text_color=self.PALETTE["muted"]).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(addr_grid, text="Port", font=("Segoe UI", 10), text_color=self.PALETTE["muted"]).grid(row=0, column=1, sticky="w", padx=6)
        ctk.CTkLabel(addr_grid, text="RTSP Stream Path", font=("Segoe UI", 10), text_color=self.PALETTE["muted"]).grid(row=0, column=2, sticky="w")

        self.entry_ip = ctk.CTkEntry(addr_grid, textvariable=self.ip_var, placeholder_text="192.168.1.100", height=30, corner_radius=6)
        self.entry_ip.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self.entry_port = ctk.CTkEntry(addr_grid, textvariable=self.port_var, placeholder_text="554", height=30, corner_radius=6)
        self.entry_port.grid(row=1, column=1, sticky="ew", padx=6, pady=(2, 0))

        self.entry_path = ctk.CTkEntry(addr_grid, textvariable=self.path_var, placeholder_text="/stream1", height=30, corner_radius=6)
        self.entry_path.grid(row=1, column=2, sticky="ew", pady=(2, 0))

        # 4. USB Webcam Options Group (Initially hidden or shown based on segmented)
        self.usb_card = ctk.CTkFrame(form_scroll, fg_color=self.PALETTE["card_subtle"], corner_radius=10, border_width=1, border_color=self.PALETTE["border"])
        # Initially unpacked; shown when USB Webcam is active

        usb_inner = ctk.CTkFrame(self.usb_card, fg_color="transparent")
        usb_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(usb_inner, text="Connected Video Device Index:", font=("Segoe UI Semibold", 10), text_color=self.PALETTE["muted"]).pack(anchor="w", pady=(0, 4))
        
        usb_controls = ctk.CTkFrame(usb_inner, fg_color="transparent")
        usb_controls.pack(fill="x")

        self.usb_combo = ctk.CTkComboBox(
            usb_controls,
            values=["0", "1", "2", "3"],
            height=30,
            corner_radius=6,
            command=lambda v: self.source_var.set(v)
        )
        self.usb_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_scan_usb = ctk.CTkButton(
            usb_controls,
            text="Scan Devices",
            width=90,
            height=30,
            corner_radius=6,
            fg_color=self.PALETTE["border"],
            hover_color=self.PALETTE["accent_hover"],
            font=("Segoe UI", 11),
            command=self._scan_local_cameras
        )
        self.btn_scan_usb.pack(side="right")

        # 5. Full Source URI Field & Build Action
        src_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        src_row.pack(fill="x", pady=(2, 2))

        ctk.CTkLabel(src_row, text="Active Video Source URI / Path", font=("Segoe UI Semibold", 11), text_color=self.PALETTE["muted"]).pack(side="left")
        
        self.btn_build_url = ctk.CTkButton(
            src_row,
            text="Auto-Build URI",
            width=90,
            height=22,
            corner_radius=5,
            fg_color=self.PALETTE["border"],
            hover_color=self.PALETTE["accent_hover"],
            font=("Segoe UI", 10),
            command=self._build_rtsp_url
        )
        self.btn_build_url.pack(side="right")

        self.entry_src = ctk.CTkComboBox(
            form_scroll,
            variable=self.source_var,
            values=["rtsp://..."],
            height=34,
            corner_radius=8
        )
        self.entry_src.pack(fill="x", pady=(2, 10))

        # 6. Live Stream Verification & Diagnostic Engine
        probe_card = ctk.CTkFrame(form_scroll, fg_color=self.PALETTE["card_subtle"], corner_radius=10, border_width=1, border_color=self.PALETTE["border"])
        probe_card.pack(fill="x", pady=(0, 12))

        probe_inner = ctk.CTkFrame(probe_card, fg_color="transparent")
        probe_inner.pack(fill="x", padx=12, pady=10)

        probe_top = ctk.CTkFrame(probe_inner, fg_color="transparent")
        probe_top.pack(fill="x")

        self.btn_test = ctk.CTkButton(
            probe_top,
            text="⚡ Test Stream Connection",
            height=30,
            corner_radius=6,
            fg_color=self.PALETTE["border"],
            hover_color=self.PALETTE["accent_hover"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=self._test_stream_connection
        )
        self.btn_test.pack(side="left")

        self.lbl_probe_status = ctk.CTkLabel(
            probe_inner,
            text="Ready to verify stream handshake (3.0s timeout)",
            font=("Segoe UI", 10),
            text_color=self.PALETTE["muted"],
            anchor="w"
        )
        self.lbl_probe_status.pack(fill="x", pady=(6, 0))

        # 7. Form Action Buttons (Save / Clear)
        right_bot = ctk.CTkFrame(right_card, fg_color="transparent")
        right_bot.grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 14))

        self.btn_save = ctk.CTkButton(
            right_bot,
            text="Add Camera",
            height=36,
            corner_radius=8,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            font=("Segoe UI Semibold", 12),
            command=self._save_camera
        )
        self.btn_save.pack(side="right", padx=(8, 0))

        self.btn_clear = ctk.CTkButton(
            right_bot,
            text="Clear Form",
            height=36,
            corner_radius=8,
            fg_color=self.PALETTE["card_subtle"],
            hover_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
            border_width=1,
            border_color=self.PALETTE["border"],
            font=("Segoe UI Semibold", 11),
            command=self._clear_form
        )
        self.btn_clear.pack(side="right")

    def _apply_appearance(self):
        is_light = ctk.get_appearance_mode() == "Light"
        bg_col = "#ffffff" if is_light else "#131b24"
        fg_col = "#0f172a" if is_light else "#f1f5f9"
        border_col = "#cbd5e1" if is_light else "#223244"
        head_bg = "#f1f5f9" if is_light else "#182330"

        style = ttk.Style()
        style.configure(
            "Cams.Treeview",
            background=bg_col,
            foreground=fg_col,
            fieldbackground=bg_col,
            bordercolor=border_col,
            rowheight=28
        )
        style.configure(
            "Cams.Treeview.Heading",
            background=head_bg,
            foreground=fg_col,
            bordercolor=border_col
        )
        style.map("Cams.Treeview", background=[("selected", "#1d4ed8" if is_light else "#4f84bb")])

    def _on_protocol_change(self, choice):
        if choice == "USB Webcam":
            self.rtsp_card.pack_forget()
            self.usb_card.pack(fill="x", pady=(0, 10))
            if not self.source_var.get() or self.source_var.get().startswith("rtsp"):
                self.source_var.set("0")
        else:
            self.usb_card.pack_forget()
            self.rtsp_card.pack(fill="x", pady=(0, 10))
            if self.source_var.get().isdigit():
                self._build_rtsp_url()

    def _on_preset_selected(self, choice):
        if "Tapo" in choice:
            self.path_var.set("/stream1")
            self.port_var.set("554")
        elif "Hikvision" in choice:
            self.path_var.set("/Streaming/Channels/101")
            self.port_var.set("554")
        elif "Dahua" in choice:
            self.path_var.set("/cam/realmonitor?channel=1&subtype=0")
            self.port_var.set("554")
        elif "ONVIF" in choice:
            self.path_var.set("/live/ch0")
            self.port_var.set("554")
        self._build_rtsp_url()

    def _toggle_password_mask(self):
        if self.show_pass_var.get():
            self.entry_pass.configure(show="")
        else:
            self.entry_pass.configure(show="•")

    def _test_stream_connection(self):
        if self._is_testing_connection:
            return

        self._build_rtsp_url()
        src = self.source_var.get().strip()
        if not src:
            self.lbl_probe_status.configure(
                text="✖ Please enter a source address or select a webcam device.",
                text_color=self.PALETTE["danger"]
            )
            return

        self._is_testing_connection = True
        self.btn_test.configure(state="disabled")
        self.lbl_probe_status.configure(
            text="⏳ Probing stream handshake (opening video stream)...",
            text_color=self.PALETTE["accent"]
        )

        import threading
        def _probe_worker():
            import cv2
            import time
            success = False
            details = ""
            cap = None
            try:
                # Local device or RTSP stream
                if src.isdigit():
                    device_idx = int(src)
                    cap = cv2.VideoCapture(device_idx, cv2.CAP_DSHOW)
                else:
                    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
                
                # Check opening and grab a single test frame
                start_t = time.time()
                while time.time() - start_t < 3.0:
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            h, w = frame.shape[:2]
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            fps_str = f"{int(fps)}" if fps > 0 else "25-30"
                            success = True
                            details = f"✔ Stream Verified: {w}x{h} @ {fps_str} FPS (Handshake OK)"
                            break
                    time.sleep(0.1)

                if not success:
                    details = "✖ Connection Failed: Stream timed out or host unreachable"
            except Exception as e:
                details = f"✖ Connection Error: {str(e)[:45]}"
            finally:
                if cap is not None:
                    # Release in background thread to avoid blocking GUI
                    def _rel(c):
                        try: c.release()
                        except: pass
                    threading.Thread(target=_rel, args=(cap,), daemon=True).start()

            def _update_ui():
                self._is_testing_connection = False
                self.btn_test.configure(state="normal")
                self.lbl_probe_status.configure(
                    text=details,
                    text_color=self.PALETTE["success"] if success else self.PALETTE["danger"]
                )

            self.after(0, _update_ui)

        threading.Thread(target=_probe_worker, daemon=True).start()

    def _renumber_cameras(self):
        profile_store.normalize_camera_ids()
        self._load_cameras()
        self._clear_form()
        self.on_refresh()
        messagebox.showinfo("Renumbered", "Camera IDs have been normalized sequentially from 1 to N.")

    def close_and_refresh(self):
        profile_store.normalize_camera_ids()
        self.on_refresh()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _load_cameras(self):
        profile_store.normalize_camera_ids()
        for i in self.tree.get_children():
            self.tree.delete(i)
        cams = profile_store.list_cameras()
        count = len(cams)
        self.lbl_capacity_badge.configure(text=f"{count} / 4 CHANNELS CONFIGURED")

        for c in cams:
            src = c["source"]
            is_rtsp = str(src).lower().startswith("rtsp://")
            stream_type = "RTSP" if is_rtsp else "USB"
            self.tree.insert(
                "",
                "end",
                iid=str(c["camera_id"]),
                values=(c["camera_id"], c["name"], stream_type, src)
            )

    def _scan_local_cameras(self):
        self.entry_src.configure(values=["Scanning local devices..."])
        import threading
        def _scan():
            import cv2
            available = []
            for i in range(6):
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap.isOpened():
                    available.append(str(i))
                    cap.release()
            self.after(0, lambda: self._update_source_combobox(available))
        threading.Thread(target=_scan, daemon=True).start()

    def _update_source_combobox(self, available):
        opts = available + ["rtsp://<ip>:<port>/stream"]
        self.entry_src.configure(values=opts)
        self.usb_combo.configure(values=available if available else ["0"])
        if available and not self.source_var.get():
            self.source_var.set(available[0])

    def _on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_cam_id = int(sel[0])
        val = self.tree.item(sel[0])["values"]
        cam_name = str(val[1])
        cam_src = str(val[3])

        self.name_var.set(cam_name)
        self.source_var.set(cam_src)
        self.btn_save.configure(text="Update Channel")
        self.lbl_channel_tag.configure(text=f"EDITING CAM {self.selected_cam_id}")

        if cam_src.isdigit():
            self.proto_segmented.set("USB Webcam")
            self._on_protocol_change("USB Webcam")
            self.usb_combo.set(cam_src)
        else:
            self.proto_segmented.set("RTSP Stream")
            self._on_protocol_change("RTSP Stream")
            self._parse_rtsp_url(cam_src)

    def _parse_rtsp_url(self, url):
        # Best-effort parse of rtsp://user:pass@host:port/path
        try:
            from urllib.parse import urlparse, unquote
            p = urlparse(url)
            if p.scheme == "rtsp":
                if p.username: self.user_var.set(unquote(p.username))
                if p.password: self.pass_var.set(unquote(p.password))
                if p.hostname: self.ip_var.set(p.hostname)
                if p.port: self.port_var.set(str(p.port))
                if p.path: self.path_var.set(p.path)
        except Exception:
            pass

    def _clear_form(self):
        self.selected_cam_id = None
        self.name_var.set("")
        self.source_var.set("")
        self.ip_var.set("")
        self.port_var.set("554")
        self.path_var.set("/stream1")
        self.user_var.set("")
        self.pass_var.set("")
        self.preset_var.set("Custom")
        self.btn_save.configure(text="Add Camera")
        self.lbl_channel_tag.configure(text="NEW CHANNEL")
        self.lbl_probe_status.configure(
            text="Ready to verify stream handshake (3.0s timeout)",
            text_color=self.PALETTE["muted"]
        )
        self.tree.selection_remove(self.tree.selection())

    def _build_rtsp_url(self):
        from urllib.parse import quote
        ip = self.ip_var.get().strip()
        port = self.port_var.get().strip() or "554"
        path = self.path_var.get().strip() or "/stream1"
        user = self.user_var.get().strip()
        pw = self.pass_var.get().strip()

        if not path.startswith("/"):
            path = "/" + path

        if ip:
            auth = ""
            if user:
                auth = quote(user, safe="")
                if pw:
                    auth += ":" + quote(pw, safe="")
                auth += "@"
            url = f"rtsp://{auth}{ip}:{port}{path}"
            vals = list(self.entry_src.cget("values"))
            if url not in vals:
                vals.append(url)
                self.entry_src.configure(values=vals)
            self.source_var.set(url)

    def _save_camera(self):
        name = self.name_var.get().strip()
        src = self.source_var.get().strip()
        if not name or not src:
            messagebox.showwarning("Incomplete", "Please provide both camera name and video source.")
            return

        # Check for duplicate source
        existing = profile_store.list_cameras()
        for cam in existing:
            if cam["source"] == src and cam["camera_id"] != self.selected_cam_id:
                messagebox.showwarning(
                    "Duplicate Source",
                    f"Source '{src}' is already assigned to camera '{cam['name']}'.\n"
                    "Multiple cameras cannot share the exact same hardware device or stream URI."
                )
                return

        try:
            if self.selected_cam_id:
                profile_store.update_camera(self.selected_cam_id, name, src)
            else:
                profile_store.add_camera(name, src)

            self._load_cameras()
            self._clear_form()
            self.on_refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _delete_camera(self):
        if not self.selected_cam_id:
            messagebox.showinfo("Select Channel", "Please select a camera channel from the list to remove.")
            return

        if not messagebox.askyesno("Confirm Removal", f"Remove camera channel ID {self.selected_cam_id} from monitoring network?"):
            return

        try:
            profile_store.delete_camera(self.selected_cam_id)
            self._load_cameras()
            self._clear_form()
            self.on_refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))


class CameraMonitorScreen(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        
        # Internal Theme
        self.PALETTE = {
            "bg": "#06090c",
            "header": "#0f161f",
            "accent": "#4f84bb",
            "border": "#1e2c3a"
        }

        self.cameras = []
        self.grid_container = None
        self.active_alert_incident_id = None
        self.active_alert_camera_id = None
        self.active_alert_contraband_ids = []
        self._alert_banner_visible = False
        self._alert_thumb_photo = None
        self._alert_auto_dismiss_job = None
        self._is_monitoring = False
        self._connecting = False
        self._connect_thread = None
        self._poll_connecting_job = None

        self.create_widgets()

        # Subscribe to detection & incident events
        from monitor_app.events import get_event_bus
        get_event_bus().subscribe("INCIDENT_START", self._on_incident_alert)
        get_event_bus().subscribe("DECISION_TRIGGER", self._on_decision_alert)

    def create_widgets(self):
        # 1. Header Bar
        self.header = ctk.CTkFrame(self, fg_color=self.PALETTE["header"], height=60, corner_radius=0)
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)
        
        ctk.CTkLabel(
            self.header, 
            text="LIVE MONITOR NETWORK", 
            font=("Segoe UI Bold", 13), 
            text_color=self.PALETTE["accent"]
        ).pack(side="left", padx=25)

        self.btn_benchmark = ctk.CTkButton(
            self.header,
            text="Start Benchmark",
            width=120, height=40,
            corner_radius=10,
            fg_color="#50d186",
            hover_color="#3fa86d",
            font=("Segoe UI Bold", 12),
            state="disabled",
            command=self.toggle_benchmark
        )
        self.btn_benchmark.pack(side="right", padx=5)
        self._poll_engine_ready()

        self.btn_dashboard = ctk.CTkButton(
            self.header,
            text="Validation Dashboard",
            width=150, height=40,
            corner_radius=10,
            fg_color="#4f84bb",
            hover_color="#3c6b9b",
            font=("Segoe UI Bold", 12),
            command=self.open_validation_dashboard
        )
        self.btn_dashboard.pack(side="right", padx=5)

        # 2. Live Incident Alert Preview Banner (Collapsible)
        self.alert_banner_frame = ctk.CTkFrame(
            self,
            fg_color="#220e11",
            border_width=2,
            border_color="#f25c5c",
            corner_radius=12,
            height=76
        )
        self.alert_banner_frame.pack_propagate(False)

        # Snapshot Preview Thumbnail
        self.alert_thumb_lbl = ctk.CTkLabel(
            self.alert_banner_frame,
            text="[Snapshot]",
            width=90,
            height=56,
            fg_color="#0e151c",
            corner_radius=8,
            font=("Segoe UI", 10),
            text_color="#8da1b4"
        )
        self.alert_thumb_lbl.pack(side="left", padx=12, pady=10)

        # Text Details
        text_wrap = ctk.CTkFrame(self.alert_banner_frame, fg_color="transparent")
        text_wrap.pack(side="left", fill="both", expand=True, pady=8)

        self.alert_title_lbl = ctk.CTkLabel(
            text_wrap,
            text="🚨 ACTIVE DETECTION ALERT",
            font=("Segoe UI Bold", 13),
            text_color="#f25c5c",
            anchor="w"
        )
        self.alert_title_lbl.pack(anchor="w")

        self.alert_sub_lbl = ctk.CTkLabel(
            text_wrap,
            text="Event details loading...",
            font=("Segoe UI", 11),
            text_color="#e1ebf5",
            anchor="w"
        )
        self.alert_sub_lbl.pack(anchor="w", pady=(2, 0))

        # Actions
        btn_wrap = ctk.CTkFrame(self.alert_banner_frame, fg_color="transparent")
        btn_wrap.pack(side="right", padx=14, pady=10)

        self.btn_alert_review = ctk.CTkButton(
            btn_wrap,
            text="Review Incident ➔",
            width=135,
            height=36,
            corner_radius=8,
            fg_color="#f25c5c",
            hover_color="#d64545",
            font=("Segoe UI Bold", 11),
            command=self._review_active_incident
        )
        self.btn_alert_review.pack(side="left", padx=(0, 8))

        self.btn_alert_dismiss = ctk.CTkButton(
            btn_wrap,
            text="Dismiss",
            width=70,
            height=36,
            corner_radius=8,
            fg_color="#2b3947",
            hover_color="#3d4f61",
            font=("Segoe UI Semibold", 11),
            command=self._dismiss_alert_banner
        )
        self.btn_alert_dismiss.pack(side="left")

        # 3. Camera Grid Container
        self.grid_container = ctk.CTkFrame(self, fg_color=self.PALETTE["bg"], corner_radius=0)
        self.grid_container.pack(fill="both", expand=True)

        self._load_feeds()

    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for confirmed incidents"""
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                c_ids = []
                if ai_results and isinstance(ai_results, dict):
                    for det in ai_results.get("detections", {}).get("contraband", []):
                        tid = det.get("track_id")
                        if tid is not None and tid != -1:
                            c_ids.append(tid)
                self.after_idle(lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity, ci=c_ids: self._show_alert_banner(c, i, e, f, severity=s, contraband_ids=ci))
        except Exception:
            pass

    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for fast preliminary decision triggers"""
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                c_ids = []
                if ai_results and isinstance(ai_results, dict):
                    for det in ai_results.get("detections", {}).get("contraband", []):
                        tid = det.get("track_id")
                        if tid is not None and tid != -1:
                            c_ids.append(tid)
                self.after_idle(lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity, ci=c_ids: self._show_alert_banner(c, i, e, f, sc, severity=s, contraband_ids=ci))
        except Exception:
            pass

    def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None, contraband_ids=None):
        if incident_id:
            self.active_alert_incident_id = incident_id
        self.active_alert_camera_id = str(camera_id)
        if contraband_ids:
            self.active_alert_contraband_ids = list(contraband_ids)
        elif not hasattr(self, "active_alert_contraband_ids"):
            self.active_alert_contraband_ids = []

        # Start continuous beating audio alert loop until dismissed
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().start_beating_loop(incident_id or f"ALERT_{camera_id}")
        except Exception:
            pass
        
        # Format title & subtitle with threshold indicators & severity
        sev_tag = f" [{severity}]" if severity else ""
        self.alert_title_lbl.configure(text=f"🚨 ALERT{sev_tag}: {event_type.upper()}")
        
        from datetime import datetime
        time_str = datetime.now().strftime("%H:%M:%S")
        sub_text = f"Camera {camera_id}  •  Detected at {time_str}"
        self.alert_sub_lbl.configure(text=sub_text)

        # Generate snapshot thumbnail
        if frame is not None:
            try:
                import cv2
                from PIL import Image, ImageTk
                # Resize to thumbnail 90x56
                thumb_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_thumb = Image.fromarray(thumb_rgb).resize((90, 56))
                self._alert_thumb_photo = ctk.CTkImage(light_image=pil_thumb, dark_image=pil_thumb, size=(90, 56))
                self.alert_thumb_lbl.configure(image=self._alert_thumb_photo, text="")
            except Exception as e:
                self.alert_thumb_lbl.configure(image=None, text="[Snapshot]")
        else:
            self.alert_thumb_lbl.configure(image=None, text="[Snapshot]")

        # Show banner
        if not self._alert_banner_visible:
            self.alert_banner_frame.pack(side="top", fill="x", padx=16, pady=(10, 4), before=self.grid_container)
            self._alert_banner_visible = True

        # Auto-dismiss after 20 seconds of inactivity
        if self._alert_auto_dismiss_job:
            self.after_cancel(self._alert_auto_dismiss_job)
        self._alert_auto_dismiss_job = self.after(20000, self._dismiss_alert_banner)

    def _dismiss_alert_banner(self):
        # 1. Stop beating sound immediately upon dismissal
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass

        # 2. Register dismissal for the active contraband track IDs on this camera
        try:
            from monitor_app.decision import get_dismissal_registry
            reg = get_dismissal_registry()
            cam_id = getattr(self, "active_alert_camera_id", None)
            if cam_id:
                for tid in getattr(self, "active_alert_contraband_ids", []):
                    reg.dismiss_track(cam_id, tid)
        except Exception:
            pass

        if self._alert_banner_visible:
            self.alert_banner_frame.pack_forget()
            self._alert_banner_visible = False
        if self._alert_auto_dismiss_job:
            self.after_cancel(self._alert_auto_dismiss_job)
            self._alert_auto_dismiss_job = None

    def _review_active_incident(self):
        """Jump to Incidents screen with the current active alert incident loaded."""
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass
        root = self.winfo_toplevel()
        target_id = getattr(self, "active_alert_incident_id", None)
        if not target_id:
            try:
                import os
                import sqlite3
                from monitor_app.utils import data_path
                db = data_path("incidents.db")
                if os.path.exists(db):
                    conn = sqlite3.connect(db)
                    c = conn.cursor()
                    c.execute("SELECT event_id FROM incidents ORDER BY timestamp_start DESC LIMIT 1")
                    row = c.fetchone()
                    conn.close()
                    if row:
                        target_id = row[0]
            except Exception as e:
                logger.error(f"Failed to fetch latest incident for review: {e}")
        if hasattr(root, "switch_screen"):
            root.switch_screen("Incidents", initial_incident_id=target_id)

    def _poll_engine_ready(self):
        from monitor_app.central_inference import get_inference_manager
        manager = get_inference_manager()
        from monitor_app.utils import GlobalState
        if manager.engine is not None:
            if not GlobalState.benchmark_active:
                self.btn_benchmark.configure(state="normal")
        else:
            self.btn_benchmark.configure(state="disabled")
        self.after(1000, self._poll_engine_ready)

    def _load_feeds(self):
        # Clear existing
        for cam in self.cameras:
            cam.stop()
            cam.destroy()
        self.cameras = []

        # Fetch from DB
        db_cams = profile_store.list_cameras()
        num_cams = len(db_cams)
        
        # Calculate grid (2 columns)
        cols = 2
        rows = (num_cams + 1) // cols
        
        for i in range(cols): self.grid_container.grid_columnconfigure(i, weight=1)
        for i in range(max(2, rows)): self.grid_container.grid_rowconfigure(i, weight=1)

        for i, cam_data in enumerate(db_cams):
            row = i // cols
            col = i % cols
            
            # Parse source
            src = cam_data["source"]
            if src.isdigit(): src = int(src)
            
            cam_feed = CameraFeedWidget(self.grid_container, camera_id=cam_data["camera_id"], name=cam_data["name"], source=src)
            cam_feed.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            self.cameras.append(cam_feed)

    def _open_management(self):
        # Open the modal
        dialog = CameraManagementDialog(self, on_refresh=self.refresh_cameras)
        dialog.grab_set()
        dialog.focus_force()
        # Bind WM_DELETE_WINDOW so X button also releases grab cleanly
        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.grab_release(), dialog.on_refresh(), dialog.destroy()))

    def refresh_cameras(self):
        # Re-initialize feeds without reloading the whole screen
        self._load_feeds()
        self.start_monitoring()

        # Force Windows compositor to fully repaint the window.
        # The alpha-flicker trick is the most reliable fix for the
        # "blurry / frosted glass" artifact left after a CTkToplevel with
        # grab_set() is closed on Windows.
        root = self.winfo_toplevel()
        root.update_idletasks()
        root.lift()
        root.focus_force()
        root.attributes("-alpha", 0.99)
        root.after(50, lambda: root.attributes("-alpha", 1.0))

    def start_monitoring(self):
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().start()
        
        self._is_monitoring = True
        self._connecting = True
        self._show_connecting_overlay()
        
        import threading
        
        def connect_camera(cam):
            cam.start()
            return cam

        def connect_all():
            if self.cameras:
                import time
                for cam in list(self.cameras):
                    if not getattr(self, "_is_monitoring", False):
                        break
                    try:
                        connect_camera(cam)
                    except Exception as e:
                        print(f"[Camera] Failed to connect {cam}: {e}")
                    time.sleep(0.08)  # 80ms stagger prevents USB bus contention
            self._connecting = False
            
        self._connect_thread = threading.Thread(target=connect_all, daemon=True)
        self._connect_thread.start()
        self._poll_connecting_status()

    def _poll_connecting_status(self):
        if not self.winfo_exists() or not getattr(self, "_is_monitoring", False):
            self._hide_connecting_overlay()
            return
        if not getattr(self, "_connecting", True):
            self._hide_connecting_overlay()
            self._refresh_camera_widgets()
        else:
            self._poll_connecting_job = self.after(100, self._poll_connecting_status)

    def _show_connecting_overlay(self):
        if not hasattr(self, 'loading_overlay') or not self.loading_overlay.winfo_exists():
            self.loading_overlay = ctk.CTkFrame(self.grid_container, fg_color="black", bg_color="black")
            self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            
            lbl = ctk.CTkLabel(
                self.loading_overlay, 
                text="Connecting to cameras...", 
                font=("Segoe UI Bold", 24), 
                text_color="white"
            )
            lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_connecting_overlay(self):
        if hasattr(self, 'loading_overlay') and self.loading_overlay.winfo_exists():
            self.loading_overlay.destroy()

    def _refresh_camera_widgets(self):
        pass

    def stop_monitoring(self):
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass
        self._is_monitoring = False
        self._connecting = False
        if hasattr(self, "_poll_connecting_job") and self._poll_connecting_job:
            try:
                self.after_cancel(self._poll_connecting_job)
            except Exception:
                pass
            self._poll_connecting_job = None
        if self._alert_auto_dismiss_job:
            try:
                self.after_cancel(self._alert_auto_dismiss_job)
            except Exception:
                pass
            self._alert_auto_dismiss_job = None
        try:
            from monitor_app.events import get_event_bus
            get_event_bus().unsubscribe("INCIDENT_START", self._on_incident_alert)
            get_event_bus().unsubscribe("DECISION_TRIGGER", self._on_decision_alert)
        except Exception:
            pass
        for cam in self.cameras:
            cam.stop()
        if hasattr(self, "_connect_thread") and self._connect_thread and self._connect_thread.is_alive():
            self._connect_thread.join(timeout=1.5)
            self._connect_thread = None
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().stop()

    def toggle_benchmark(self):
        from monitor_app.utils import GlobalState
        from monitor_app.benchmark.__main__ import CellWatchBenchmark, BenchmarkProfile, BenchmarkState
        import threading
        
        if GlobalState.benchmark_active:
            if hasattr(self, "benchmark_runner"):
                self.benchmark_runner.state = BenchmarkState.STOPPING
            return
            
        self.benchmark_runner = CellWatchBenchmark()
        
        def _run():
            # Start verification run directly on live feeds
            self.benchmark_runner.run_profile(BenchmarkProfile.QUICK, len(self.cameras))
            
        threading.Thread(target=_run, daemon=True).start()
        # Start updates loop
        self.after(1000, self.update_benchmark_metrics)

    def update_benchmark_metrics(self):
        from monitor_app.utils import GlobalState
        if not GlobalState.benchmark_active:
            self.btn_benchmark.configure(text="Start Benchmark", fg_color="#50d186", state="normal")
            return
            
        self.btn_benchmark.configure(text="Stop Benchmark", fg_color="#f25c5c", state="normal")
        self.after(500, self.update_benchmark_metrics)

    def open_validation_dashboard(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Validation Dashboard")
        dialog.geometry("1000x700")
        
        from monitor_app.telemetry.benchmark_center import ValidationCenterScreen
        screen = ValidationCenterScreen(dialog)
        screen.pack(fill="both", expand=True)
        
        dialog.grab_set()
        dialog.focus_force()
        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.grab_release(), dialog.destroy()))


class CameraFeedWidget(ttk.Frame):
    def __init__(self, parent, camera_id, name, source=None):
        super().__init__(parent, style="Card.TFrame")
        self.camera_id = camera_id
        self.name = name
        self.source = source
        self.cap = None
        self.running = False
        self.tk_image = None
        self.frame_index = 0  # unused with unified engine
        self.result_queue = queue.Queue(maxsize=1)
        self.worker_thread = None
        self.last_frame_rgb = None
        self.ui_frame_interval_ms = 33  # ~30 FPS UI refresh
        self.target_width = 320
        self.target_height = 240
        self.fallback_count = 0
        
        # Watchdog & Capture thread variables
        self.is_reconnecting = False
        self.frame_queue = queue.Queue(maxsize=1)
        self.cap_thread = None
        
        # Incident detection & recording logic
        self.recorder = IncidentRecorder(self.camera_id)
        self.last_alert_triggered = False
        self.last_alert_desc = ""
        self.is_offline = False
        self.is_stopped = False
        
        # Local CPU motion gating
        self.gater = LocalMotionGater()

        self.setup_ui()
        self.after(50, self.update_loop)

    def setup_ui(self):
        self.pack_propagate(False)

        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x", padx=5, pady=5)

        src_text = "Webcam" if self.source in (0, 1, 2, 3) else ("IP Camera" if isinstance(self.source, str) else "Simulated")
        self.lbl_title = ttk.Label(
            header,
            text=f"{self.name} ({src_text})",
            style="Card.TLabel",
            font=utils.FONT_BOLD
        )
        self.lbl_title.pack(side="left")

        self.lbl_status = ttk.Label(
            header,
            text="NORMAL",
            foreground=utils.COLOR_SUCCESS,
            style="Card.TLabel",
            font=utils.FONT_BOLD
        )
        self.lbl_status.pack(side="right")

        self.lbl_frame_counter = ttk.Label(
            header,
            text="",
            foreground="#a2b5c7",
            style="Card.TLabel",
            font=utils.FONT_BOLD
        )
        self.lbl_frame_counter.pack(side="right", padx=(0, 15))

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=2, highlightbackground="#1e2c3a")
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)

        self.draw_placeholder()

    def start(self):
        if self.running:
            return
        self.running = True
        self._consecutive_failures = 0

        # AlertManager and IncidentRecorder are now loosely coupled via EventBus
        from monitor_app.health import get_health_monitor, ComponentState
        get_health_monitor().register_component(
            f"Camera_{self.camera_id}", 
            lambda: ComponentState.RUNNING if (self.cap and self.cap.isOpened() and self.running) else (ComponentState.IDLE if not self.running else ComponentState.FAILED)
        )

        if CV2_AVAILABLE and self.source is not None:
            self._open_capture()

            # Start worker thread for real cameras
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
        
        # Track active cameras globally
        utils.GlobalState.register_camera(self.camera_id)

    def _open_capture(self):
        """Open (or reopen) the video capture with fallback backends."""
        if self.cap_thread and self.cap_thread.is_alive():
            logger.info(f"Waiting for old capture thread of camera {self.camera_id} to exit...", camera_id=self.camera_id)
            self.cap_thread.join(timeout=1.0)
            self.cap_thread = None

        if self.cap:
            old_cap = self.cap
            self.cap = None
            try:
                old_cap.release()
            except Exception:
                pass

        src = self.source
        # For integer webcams, prefer DSHOW on Windows because it releases cleanly and avoids MSMF device locks
        if isinstance(src, int):
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        else:
            backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]
        
        import os
        if not isinstance(src, int):
            # Low-latency RTSP: fflags;nobuffer + flags;low_delay drop FFmpeg's internal
            # frame buffering (removes the ~2s startup/live delay). max_delay;500000 caps
            # reorder buffering at 0.5s. stimeout;5000000 retained = 5s connection-hang
            # protection (do not remove; documented fix in capstone_progress_report.md).
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000|stimeout;5000000"
        else:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "stimeout;5000000"
        
        for backend in backends:
            try:
                cap = cv2.VideoCapture(src, backend)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                
                if cap.isOpened():
                    if isinstance(src, int):
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    else:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                    # Probe read: verify the device handle actually yields valid frames
                    test_ret, test_frame = cap.read()
                    if not test_ret or test_frame is None or getattr(test_frame, "size", 0) == 0:
                        cap.release()
                        continue
                        
                    self.cap = cap
                    self._consecutive_failures = 0
                    
                    actual_backend = cap.get(cv2.CAP_PROP_BACKEND)
                    backend_name = "UNKNOWN"
                    if actual_backend == cv2.CAP_FFMPEG:
                        backend_name = "FFMPEG"
                    elif actual_backend == cv2.CAP_MSMF:
                        backend_name = "MSMF"
                    elif actual_backend == cv2.CAP_DSHOW:
                        backend_name = "DSHOW"
                    else:
                        backend_name = str(actual_backend)
                        
                    log_msg = f"Camera {self.camera_id} opened with backend: {backend_name}"
                    if not isinstance(src, int) and backend_name != "FFMPEG":
                        log_msg += " (fallback)"
                        
                    print(log_msg)
                    logger.info(log_msg, camera_id=self.camera_id)
                    
                    # Clear any stale frames from queue
                    while not self.frame_queue.empty():
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            break
                            
                    # Spawn capture thread
                    self.cap_thread = threading.Thread(
                        target=self._capture_thread_loop,
                        args=(cap, self.frame_queue),
                        daemon=True
                    )
                    self.cap_thread.start()
                    return
                cap.release()
            except Exception as e:
                print(f"Camera {self.camera_id} backend {backend} failed: {e}")
        print(f"Camera {self.camera_id}: could not open source '{src}'")
        self.is_offline = True

    def _capture_thread_loop(self, cap, q):
        while self.running and self.cap == cap:
            try:
                ret, frame = cap.read()
                if not self.running or self.cap != cap:
                    break
                
                # Bounded queue put: drop oldest if full
                while self.running and self.cap == cap:
                    try:
                        q.put_nowait((ret, frame))
                        break
                    except queue.Full:
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            pass
                if not ret:
                    break
            except Exception as e:
                if self.running:
                    print(f"Capture thread exception (Cam {self.camera_id}): {e}")
                try:
                    q.put_nowait((False, None))
                except Exception:
                    pass
                break

    def _worker_loop(self):
        """Background thread for capturing and processing frames."""
        from monitor_app.config import get_config
        initial_backoff = get_config("camera_reconnect", "initial_backoff", 1.0)
        max_backoff = get_config("camera_reconnect", "max_backoff", 60.0)
        factor = get_config("camera_reconnect", "factor", 2.0)
        
        reconnect_delay = initial_backoff
        MAX_CONSECUTIVE_FAILURES = 60  # ~2 seconds of failures before reconnect
        
        benchmark_frame_idx = 0
        ai_frame_skip_counter = 0
        
        while self.running:
            if not self.cap or not self.cap.isOpened():
                logger.info(f"Attempting reconnect in {reconnect_delay:.1f}s...", camera_id=self.camera_id)
                # Sleep in small steps to respond quickly to self.running = False
                sleep_start = time.time()
                while self.running and (time.time() - sleep_start < reconnect_delay):
                    time.sleep(0.1)
                
                if not self.running:
                    break
                
                self._open_capture()
                if self.cap and self.cap.isOpened():
                    logger.info("Reconnect successful!", camera_id=self.camera_id)
                    reconnect_delay = initial_backoff
                else:
                    reconnect_delay = min(reconnect_delay * factor, max_backoff)
                continue

            try:
                ret, raw_frame = self.frame_queue.get(timeout=2.5)
                # Once we successfully retrieve a frame, we are no longer in reconnect status
                self.is_reconnecting = False
            except queue.Empty:
                if not self.running:
                    break
                logger.warning(f"Camera {self.camera_id} read watchdog triggered (no frames for 2.5s). Stalling connection.", camera_id=self.camera_id)
                ret = False
                raw_frame = None

            if not self.running:
                break

            if not ret or raw_frame is None or getattr(raw_frame, 'size', 0) == 0:
                if not self.running:
                    break
                self._consecutive_failures += 1
                self.is_reconnecting = True
                if self.cap:
                    old_cap = self.cap
                    self.cap = None
                    threading.Thread(target=lambda c: c.release(), args=(old_cap,), daemon=True).start()
                time.sleep(1.0)
                continue

            self._consecutive_failures = 0

            # Process AI in the background
            packet = None
            try:
                is_moving, score = self.gater.detect_motion(raw_frame)
                
                now = time.time()
                from monitor_app.config import get_config
                enable_delay = get_config("motion_gate", "enable_delay", 0.5)
                disable_delay = get_config("motion_gate", "disable_delay", 3.0)
                min_duration = get_config("motion_gate", "minimum_active_duration", 1.0)
                
                if is_moving:
                    if not hasattr(self, "_motion_first_seen") or self._motion_first_seen == 0.0:
                        self._motion_first_seen = now
                    self._last_motion_seen = now
                    
                    duration = now - self._motion_first_seen
                    required_duration = max(enable_delay, min_duration)
                    
                    if duration >= required_duration:
                        if not getattr(self, "_motion_gate_enabled", False):
                            self._motion_gate_enabled = True
                            logger.info("Motion Gate ENABLED", camera_id=self.camera_id)
                else:
                    self._motion_first_seen = 0.0
                    if getattr(self, "_motion_gate_enabled", False):
                        last_seen = getattr(self, "_last_motion_seen", 0.0)
                        if now - last_seen >= disable_delay:
                            self._motion_gate_enabled = False
                            logger.info("Motion Gate DISABLED", camera_id=self.camera_id)

                # Check tracking hysteresis: if we have active tracks, continue submitting to GPU
                from monitor_app.central_inference import get_inference_manager
                manager = get_inference_manager()
                has_active = manager.has_active_tracks(str(self.camera_id))
                
                # Check if ungated override is active
                from monitor_app.config import get_config
                gate_cfg = get_config("motion_gate") or {}
                movenet_gated = gate_cfg.get("motion_gate_movenet_enabled", True)
                yolo_gated = gate_cfg.get("motion_gate_yolo_enabled", True)
                ungated = (not movenet_gated) or (not yolo_gated)

                gate_active = getattr(self, "_motion_gate_enabled", False) or has_active or ungated
                
                if gate_active:
                    # Pacing check: if this camera already has an inference task in flight,
                    # don't pile onto task_queue to cause backpressure drop.
                    # Instead, push current frame directly into display queue (smooth 30 FPS display)
                    # while GPU processes the previous frame.
                    if manager.has_in_flight_task(str(self.camera_id)):
                        cw = self.target_width
                        ch = self.target_height
                        interp = cv2.INTER_AREA if (raw_frame.shape[1] > cw and raw_frame.shape[0] > ch) else cv2.INTER_LINEAR
                        resized_bgr = cv2.resize(raw_frame, (cw, ch), interpolation=interp)
                        rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                        img_pil = Image.fromarray(rgb)
                        
                        if self.result_queue.full():
                            try:
                                self.result_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self.result_queue.put((img_pil, getattr(self, "last_alert_triggered", False), getattr(self, "last_alert_desc", "")))
                        continue

                    # Initialize initial packet and submit to centralized GPU queue
                    from monitor_app.telemetry import TelemetryContext, get_telemetry_engine
                    telemetry_ctx = TelemetryContext(camera_id=str(self.camera_id), sequence_num=benchmark_frame_idx)
                    telemetry_ctx.mark("camera_read_end")
                    get_telemetry_engine().register_context(telemetry_ctx)
                    
                    from monitor_app.events import get_event_bus, TELEM_FRAME_READ
                    get_event_bus().publish(TELEM_FRAME_READ, TELEM_FRAME_READ, {
                        "camera_id": str(self.camera_id),
                        "frame_uuid": telemetry_ctx.frame_uuid,
                        "timestamps": {
                            "camera_read_start": telemetry_ctx.timestamps.get("camera_read_start", time.perf_counter()),
                            "camera_read_end": telemetry_ctx.timestamps.get("camera_read_end", time.perf_counter())
                        }
                    })
                    
                    packet = EvidencePacket(
                        camera_id=str(self.camera_id),
                        timestamp=time.time(),
                        frame=raw_frame,
                        motion_detected=True,  # Pre-detected by LocalMotionGater
                        motion_score=score,
                        frame_uuid=telemetry_ctx.frame_uuid
                    )
                    
                    # Non-blocking async submission: camera worker continues immediately
                    # while GPU processes in parallel
                    cam_self = self  # capture reference for callback closure
                    def _on_inference_complete(result_packet, _cam_self=cam_self, _bfidx=benchmark_frame_idx):
                        try:
                            frame_to_show = result_packet.frame
                            alert_active = result_packet.alert_triggered
                            
                            # OpenCV resize on background thread: use INTER_AREA when downscaling for crisp non-pixelated lines
                            cw = _cam_self.target_width
                            ch = _cam_self.target_height
                            interp = cv2.INTER_AREA if (frame_to_show.shape[1] > cw and frame_to_show.shape[0] > ch) else cv2.INTER_LINEAR
                            resized_bgr = cv2.resize(frame_to_show, (cw, ch), interpolation=interp)
                            rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                            img_pil = Image.fromarray(rgb)
                            
                            alert_desc = result_packet.alerts[0] if (getattr(result_packet, "alerts", None) and len(result_packet.alerts) > 0) else ""
                            if _cam_self.result_queue.full():
                                try:
                                    _cam_self.result_queue.get_nowait()
                                except queue.Empty:
                                    pass
                            _cam_self.result_queue.put((img_pil, alert_active, alert_desc))
                            
                            # Incident recording (only process full inference frames)
                            if getattr(result_packet, "processing_mode", None) != "Queue Drop (Backpressure)":
                                _cam_self.recorder.process_frame(frame_to_show, result_packet.to_dict())
                        except Exception as e:
                            print(f"Async callback error (Cam {_cam_self.camera_id}): {e}")
                    
                    # Submit every frame to the AI manager.
                    # The manager handles internal throttling (yolo_skip, movenet_skip)
                    # and correctly applies bounding boxes to non-inference frames.
                    manager.submit_task_async(packet, callback=_on_inference_complete)
                    
                    # Benchmark Logging Hook
                    from monitor_app.utils import GlobalState
                    if GlobalState.benchmark_active:
                        from monitor_app.benchmark.session_manager import get_session_manager
                        session = get_session_manager().get_active_session()
                        if session:
                            session.log_event(
                                timestamp=time.time(),
                                event_type="frame",
                                camera_id=str(self.camera_id),
                                confidence=score,
                                latency_ms=0.0,
                                message="Frame sent to GPU",
                                payload={
                                    "frame_index": benchmark_frame_idx,
                                    "boxes": [],
                                    "keypoints": []
                                }
                            )
                        benchmark_frame_idx += 1
                        def _update_lbl(idx=benchmark_frame_idx):
                            try:
                                self.lbl_frame_counter.configure(text=f"Frames: {idx}")
                            except Exception:
                                pass
                        self.after(0, _update_lbl)
                    else:
                        # Reset if benchmark just ended
                        if benchmark_frame_idx > 0:
                            benchmark_frame_idx = 0
                            def _clear_lbl():
                                try:
                                    self.lbl_frame_counter.configure(text="")
                                except Exception:
                                    pass
                            self.after(0, _clear_lbl)
                    
                    # Camera thread continues to next frame immediately
                    continue
                else:
                    # Skip full AI, gate locally on CPU (Power Saving)
                    annotated_frame = raw_frame.copy()
                    cv2.putText(annotated_frame, "Power Saving (No Motion)", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    packet = EvidencePacket(
                        camera_id=str(self.camera_id),
                        timestamp=time.time(),
                        frame=annotated_frame,
                        motion_detected=False,
                        motion_score=score,
                        processing_mode="Power Saving (No Motion)"
                    )
            except Exception as e:
                print(f"Worker AI Error (Cam {self.camera_id}): {e}")

            if packet is None:
                packet = EvidencePacket(
                    camera_id=str(self.camera_id),
                    timestamp=time.time(),
                    frame=raw_frame,
                    processing_mode="No Engine"
                )

            # Convert to RGB for non-AI frames (power saving / no engine)
            try:
                frame_to_show = packet.frame
                alert_active = packet.alert_triggered
                
                # Perform resize using INTER_AREA when downscaling to preserve bounding box clarity
                cw = self.target_width
                ch = self.target_height
                interp = cv2.INTER_AREA if (frame_to_show.shape[1] > cw and frame_to_show.shape[0] > ch) else cv2.INTER_LINEAR
                resized_bgr = cv2.resize(frame_to_show, (cw, ch), interpolation=interp)
                rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(rgb)
                
                if self.result_queue.full():
                    try:
                        self.result_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.result_queue.put((img_pil, alert_active))
                
                # --- INCIDENT RECORDING LOGIC ---
                self.recorder.process_frame(frame_to_show, packet.to_dict())
            except Exception as e:
                print(f"Worker process error: {e}")

    def stop(self):
        self.running = False
        self.is_stopped = True
        try:
            self.frame_queue.put_nowait((False, None))
        except Exception:
            pass

        # Join capture thread first so native read loop terminates
        if self.cap_thread and self.cap_thread.is_alive():
            self.cap_thread.join(timeout=0.5)

        # Release capture handle cleanly
        if self.cap:
            old_cap = self.cap
            self.cap = None
            if self.cap_thread and self.cap_thread.is_alive():
                # Cap thread still finishing a blocking read; let it finish then release
                def _safe_release(c, ct):
                    try:
                        ct.join(timeout=1.5)
                        c.release()
                    except Exception:
                        pass
                threading.Thread(target=_safe_release, args=(old_cap, self.cap_thread), daemon=True).start()
            else:
                try:
                    old_cap.release()
                except Exception as e:
                    logger.debug(f"Error releasing capture on camera {self.camera_id}: {e}")
            self.cap_thread = None

        # Join worker thread
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
            self.worker_thread = None

        # Cleanly finalize and close incident recorder
        if hasattr(self, "recorder") and self.recorder:
            try:
                self.recorder.close()
            except Exception as e:
                logger.error(f"Error closing recorder for camera {self.camera_id}: {e}")

        # Drain queues
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break

        # AlertManager and IncidentRecorder are loosely coupled via EventBus
        utils.GlobalState.unregister_camera(self.camera_id)

    def update_loop(self):
        if getattr(self, "is_stopped", False) or not self.winfo_exists():
            return

        if not self.running:
            self.after(50, self.update_loop)
            return

        if getattr(self, "is_offline", False):
            self.lbl_status.configure(text="OFFLINE", foreground="#f25c5c")
            self.draw_placeholder("Offline")
            self.after(self.ui_frame_interval_ms, self.update_loop)
            return

        frame_rgb = None
        alert_triggered = False

        # --- real camera (poll queue) ---
        if self.source is not None:
            try:
                # Try to get latest from worker (non-blocking)
                item = self.result_queue.get_nowait()
                if len(item) == 3:
                    frame_rgb, alert_triggered, alert_desc = item
                else:
                    frame_rgb, alert_triggered = item
                    alert_desc = ""
                self.last_alert_triggered = bool(alert_triggered)
                if alert_triggered and alert_desc:
                    self.last_alert_desc = alert_desc
            except queue.Empty:
                # If no new frame from worker, just continue with old or skip
                frame_rgb = None
                pass
            
            # Special case for "Signal Lost" or "Reconnecting" handled by worker not putting data
            is_recon = getattr(self, "is_reconnecting", False)
            if frame_rgb is None and (not self.cap or not self.cap.isOpened() or is_recon):
                status_text = "Reconnecting..." if is_recon else "Signal Lost"
                self.draw_placeholder(status_text)
                
                status_lbl = "RECONNECTING" if is_recon else "OFFLINE"
                status_color = "#ff9f43" if is_recon else "#f25c5c"
                self.lbl_status.configure(text=status_lbl, foreground=status_color)
                
                self.after(30, self.update_loop)
                return

        # --- simulated cams ---
        else:
            self.draw_mock_simulation()
            self.after(50, self.update_loop)  # 20 FPS
            return

        # --- draw to canvas ---
        if frame_rgb is None:
            frame_rgb = self.last_frame_rgb

        if frame_rgb is not None:
            t_start = time.perf_counter()
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw < 10 or ch < 10:
                cw, ch = 320, 240
            
            # Cache dimensions for background threads
            self.target_width = cw
            self.target_height = ch

            t0 = time.perf_counter()
            if isinstance(frame_rgb, Image.Image):
                if frame_rgb.size == (cw, ch):
                    img_pil = frame_rgb
                    t_resize = 0.0
                else:
                    # Fallback resize on main thread (e.g. during active window resizing)
                    img_pil = frame_rgb.resize((cw, ch))
                    self.fallback_count += 1
                    t_resize = (time.perf_counter() - t0) * 1000
            else:
                img_pil = Image.fromarray(frame_rgb)
                img_pil = img_pil.resize((cw, ch))
                t_resize = (time.perf_counter() - t0) * 1000
            
            t1 = time.perf_counter()
            self.tk_image = ImageTk.PhotoImage(img_pil)
            t_photo = (time.perf_counter() - t1) * 1000
            
            self.last_frame_rgb = frame_rgb
            
            t2 = time.perf_counter()
            # Optimized rendering: Update existing item instead of recreating
            if not hasattr(self, 'image_id') or self.image_id is None:
                self.image_id = self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")
            else:
                self.canvas.itemconfig(self.image_id, image=self.tk_image)
            t_canvas = (time.perf_counter() - t2) * 1000
            
            t_total = (time.perf_counter() - t_start) * 1000
            print(f"[UI TIME] Cam {self.camera_id}: Resize {t_resize:.1f}ms, PhotoImage {t_photo:.1f}ms, Canvas {t_canvas:.1f}ms (Total {t_total:.1f}ms) | Fallbacks: {self.fallback_count}", flush=True)


        # --- status ---
        # Show status from recorder or active AI detection
        rec_status, rec_color = self.recorder.get_status_info()
        if self.recorder.state == self.recorder.RECORDING:
            status_text = rec_status
            status_color = rec_color
            self.canvas.configure(highlightthickness=3, highlightbackground="#f25c5c")
            utils.GlobalState.set_alert(self.camera_id, True)
        elif self.recorder.state == self.recorder.COOLDOWN:
            status_text = rec_status
            status_color = rec_color
            self.canvas.configure(highlightthickness=2, highlightbackground="#ffa500")
            utils.GlobalState.set_alert(self.camera_id, False)
        elif getattr(self, "last_alert_triggered", False):
            tag = f": {self.last_alert_desc}" if getattr(self, "last_alert_desc", "") else ""
            status_text = f"ALERT{tag}"
            status_color = "#f25c5c"
            self.canvas.configure(highlightthickness=2, highlightbackground="#f25c5c")
            utils.GlobalState.set_alert(self.camera_id, True)
        else:
            status_text = "NORMAL"
            status_color = utils.COLOR_SUCCESS
            self.canvas.configure(highlightthickness=1, highlightbackground="#1e2c3a")
            utils.GlobalState.set_alert(self.camera_id, False)

        self.lbl_status.configure(text=status_text, foreground=status_color)

        self.after(self.ui_frame_interval_ms, self.update_loop)  # Target ~30 FPS for UI responsiveness

    def draw_placeholder(self, text="No Signal"):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10:
            w, h = 300, 200

        img = Image.new("RGB", (w, h), (40, 40, 40))
        d = ImageDraw.Draw(img)
        d.text((w // 2 - 30, h // 2), text, fill="white")
        self.tk_image = ImageTk.PhotoImage(img)

        # Reuse the same canvas image item to avoid leaking items
        if not hasattr(self, 'image_id') or self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")
        else:
            self.canvas.itemconfig(self.image_id, image=self.tk_image)

    def draw_mock_simulation(self):
        behavior, is_alert, _ = utils.MockAI.detect_behavior_frame(self.camera_id)

        if is_alert:
            self.lbl_status.configure(text=f"ALERT: {behavior.upper()}", foreground=utils.COLOR_ALERT)
        else:
            self.lbl_status.configure(text=f"Status: {behavior}", foreground=utils.COLOR_SUCCESS)

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10:
            w, h = 300, 200

        color = (100, 50, 50) if is_alert else (50, 50, 50)
        img = Image.new("RGB", (w, h), color)
        d = ImageDraw.Draw(img)
        d.text((10, 10), f"SIMULATION (Cam {self.camera_id})", fill="white")
        d.text((w // 2 - 40, h // 2), f"Person: {behavior}", fill="white")

        self.tk_image = ImageTk.PhotoImage(img)

        # Reuse the same canvas image item to avoid leaking items
        if not hasattr(self, 'image_id') or self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")
        else:
            self.canvas.itemconfig(self.image_id, image=self.tk_image)
