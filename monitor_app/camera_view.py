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


class CameraManagementDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_refresh):
        super().__init__(parent)
        self.title("Manage Camera Network")
        self.geometry("640x520")
        self.on_refresh = on_refresh
        self.after(200, lambda: self.focus_force())
        
        # Institutional Palette
        self.PALETTE = {
            "bg": "#06090c",
            "card": "#0f161f",
            "accent": "#4f84bb",
            "border": "#1e2c3a",
            "text": "#ffffff",
            "muted": "#a2b5c7",
            "danger": "#f25c5c"
        }
        
        self.configure(fg_color=self.PALETTE["bg"])
        self.selected_cam_id = None
        
        self._build_ui()
        self._load_cameras()

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=self.PALETTE["card"], corner_radius=0)
        header.pack(fill="x", pady=(0, 2))
        
        ctk.CTkLabel(
            header, 
            text="CAMERA INFRASTRUCTURE", 
            font=("Segoe UI Bold", 13), 
            text_color=self.PALETTE["accent"],
            padx=20, pady=15
        ).pack(side="left")

        # Main Container
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Form
        form = ctk.CTkFrame(self.main, fg_color=self.PALETTE["card"], corner_radius=12, border_width=1, border_color=self.PALETTE["border"])
        form.pack(fill="x", pady=(0, 20))
        
        inner_form = ctk.CTkFrame(form, fg_color="transparent")
        inner_form.pack(fill="x", padx=15, pady=15)
        
        self.name_var = tk.StringVar()
        self.source_var = tk.StringVar()
        
        # Entry Fields
        ctk.CTkLabel(inner_form, text="Camera Name", font=("Segoe UI Semibold", 12), text_color=self.PALETTE["muted"]).grid(row=0, column=0, sticky="w", padx=5)
        self.entry_name = ctk.CTkEntry(inner_form, textvariable=self.name_var, placeholder_text="e.g. Front Gate", height=36, corner_radius=8)
        self.entry_name.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))
        
        ctk.CTkLabel(inner_form, text="Source (URL or Index)", font=("Segoe UI Semibold", 12), text_color=self.PALETTE["muted"]).grid(row=0, column=1, sticky="w", padx=5)
        self.entry_src = ctk.CTkEntry(inner_form, textvariable=self.source_var, placeholder_text="e.g. 0 or rtsp://...", height=36, corner_radius=8)
        self.entry_src.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))
        
        inner_form.grid_columnconfigure((0, 1), weight=1)
        
        # Action Buttons
        btn_box = ctk.CTkFrame(inner_form, fg_color="transparent")
        btn_box.grid(row=2, column=0, columnspan=2, sticky="e")
        
        self.btn_save = ctk.CTkButton(btn_box, text="Add Camera", height=32, corner_radius=8, fg_color=self.PALETTE["accent"], command=self._save_camera)
        self.btn_save.pack(side="right", padx=5)
        
        self.btn_clear = ctk.CTkButton(btn_box, text="Clear", height=32, corner_radius=8, fg_color=self.PALETTE["border"], command=self._clear_form)
        self.btn_clear.pack(side="right", padx=5)

        # List
        list_card = ctk.CTkFrame(self.main, fg_color=self.PALETTE["card"], corner_radius=12, border_width=1, border_color=self.PALETTE["border"])
        list_card.pack(fill="both", expand=True)
        
        # Treeview for cameras
        style = ttk.Style()
        style.configure("Cams.Treeview", background=self.PALETTE["card"], foreground=self.PALETTE["text"], fieldbackground=self.PALETTE["card"], rowheight=30)
        
        self.tree = ttk.Treeview(list_card, columns=("id", "name", "source"), show="headings", style="Cams.Treeview")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="NAME")
        self.tree.heading("source", text="SOURCE PATH")
        self.tree.column("id", width=40, anchor="center")
        self.tree.column("name", width=150)
        self.tree.column("source", width=250)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Delete Button
        self.btn_del = ctk.CTkButton(self.main, text="Delete Selected", height=32, corner_radius=8, fg_color="#2a1b1f", hover_color="#7a434e", command=self._delete_camera)
        self.btn_del.pack(side="left", anchor="sw", pady=(10, 0))

        # Explicit Return Button
        self.btn_back = ctk.CTkButton(self.main, text="RETURN TO MONITOR", height=40, corner_radius=12, fg_color=self.PALETTE["accent"], font=("Segoe UI Bold", 12), command=self.close_and_refresh)
        self.btn_back.pack(side="right", anchor="se", pady=(10, 0))

    def close_and_refresh(self):
        self.on_refresh()
        self.grab_release()
        self.destroy()

    def _load_cameras(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        cams = profile_store.list_cameras()
        for c in cams:
            self.tree.insert("", "end", iid=str(c["camera_id"]), values=(c["camera_id"], c["name"], c["source"]))

    def _on_select(self, _):
        sel = self.tree.selection()
        if not sel: return
        self.selected_cam_id = int(sel[0])
        val = self.tree.item(sel[0])["values"]
        self.name_var.set(val[1])
        self.source_var.set(val[2])
        self.btn_save.configure(text="Update Camera")

    def _clear_form(self):
        self.selected_cam_id = None
        self.name_var.set("")
        self.source_var.set("")
        self.btn_save.configure(text="Add Camera")
        self.tree.selection_remove(self.tree.selection())

    def _save_camera(self):
        name = self.name_var.get()
        src = self.source_var.get()
        if not name or not src:
            messagebox.showwarning("Incomplete", "Please provide both name and source.")
            return
        
        # Check for duplicate source
        existing = profile_store.list_cameras()
        for cam in existing:
            if cam["source"] == src and cam["camera_id"] != self.selected_cam_id:
                messagebox.showwarning(
                    "Duplicate Source",
                    f"Source '{src}' is already used by camera '{cam['name']}'.\n"
                    "Two cameras cannot share the same device index or URL."
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
        if not self.selected_cam_id: return
        if not messagebox.askyesno("Confirm", "Remove this camera input?"): return
        
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

        global _pose_engine, _yolo_engine

        # --- Load persisted AI profile ---
        ai_cfg = profile_store.get_ai_settings()
        _profile = ai_cfg["active_profile"]
        _custom_vals = ai_cfg["custom_settings"] if _profile == "custom" else None

        # --- motion-optimized engine (MoveNet + optional YOLO) ---
        if _pose_engine is None and AI_AVAILABLE and MotionOptimizedEngine is not None:
            try:
                print("Using MotionOptimizedEngine (MoveNet + optional YOLO)...")
                _pose_engine = MotionOptimizedEngine(
                    debug=False,
                    sensitivity=_profile,
                    custom_values=_custom_vals,
                    enable_yolo=True,
                    prefer_gpu=True,
                    force_gpu=True,
                    force_yolo_gpu=True
                )
                _yolo_engine = None
            except Exception as e:
                print(f"MotionOptimizedEngine init failed: {e}")
                _pose_engine = None

        # --- fallback motion engine (no TensorFlow) ---
        if _pose_engine is None and AI_AVAILABLE and BasicMotionEngine is not None:
            try:
                print("Using BasicMotionEngine (motion-only, no TensorFlow)...")
                _pose_engine = BasicMotionEngine(sensitivity=_profile)
            except Exception as e:
                print(f"BasicMotionEngine init failed: {e}")
                _pose_engine = None

        self.cameras = []
        self.grid_container = None
        self.create_widgets()

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

        self.btn_manage = ctk.CTkButton(
            self.header, 
            text="+", 
            width=40, height=40, 
            corner_radius=10,
            fg_color=self.PALETTE["accent"],
            font=("Segoe UI Bold", 20),
            command=self._open_management
        )
        self.btn_manage.pack(side="right", padx=20)

        # 2. Camera Grid Container
        self.grid_container = ctk.CTkFrame(self, fg_color=self.PALETTE["bg"], corner_radius=0)
        self.grid_container.pack(fill="both", expand=True)

        self._load_feeds()

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
        for cam in self.cameras:
            cam.start()

    def stop_monitoring(self):
        for cam in self.cameras:
            cam.stop()


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
        
        # Incident detection & recording logic
        self.recorder = IncidentRecorder(self.camera_id)

        self.setup_ui()

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

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)

        self.draw_placeholder()

    def start(self):
        if self.running:
            return
        self.running = True
        self._consecutive_failures = 0

        if CV2_AVAILABLE and self.source is not None:
            self._open_capture()

            # Start worker thread for real cameras
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
        
        # Track active cameras globally
        utils.GlobalState.register_camera(self.camera_id)
        self.update_loop()

    def _open_capture(self):
        """Open (or reopen) the video capture with fallback backends."""
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        src = self.source
        # Try MSMF first (Windows default), then DirectShow fallback
        backends = [cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY] if isinstance(src, int) else [cv2.CAP_ANY]
        for backend in backends:
            try:
                cap = cv2.VideoCapture(src, backend)
                if cap.isOpened():
                    if isinstance(src, int):
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.cap = cap
                    self._consecutive_failures = 0
                    print(f"Camera {self.camera_id} opened on backend {backend}")
                    return
                cap.release()
            except Exception as e:
                print(f"Camera {self.camera_id} backend {backend} failed: {e}")
        print(f"Camera {self.camera_id}: could not open source '{src}'")

    def _worker_loop(self):
        """Background thread for capturing and processing frames."""
        MAX_CONSECUTIVE_FAILURES = 60  # ~2 seconds of failures before reconnect
        while self.running:
            if not self.cap or not self.cap.isOpened():
                # Try to reconnect every 3 seconds
                time.sleep(3.0)
                if self.running:
                    print(f"Camera {self.camera_id}: attempting reconnect...")
                    self._open_capture()
                continue

            ret, raw_frame = self.cap.read()
            if not ret:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"Camera {self.camera_id}: {self._consecutive_failures} consecutive read failures, reconnecting...")
                    self._open_capture()
                time.sleep(0.03)
                continue

            self._consecutive_failures = 0

            # Process AI in the background
            global _pose_engine
            packet = None

            if _pose_engine:
                try:
                    if hasattr(_pose_engine, "detect_motion"):
                        is_moving, score = _pose_engine.detect_motion(raw_frame, str(self.camera_id))
                        if is_moving:
                            # Full AI mode
                            res = _pose_engine.process_frame(raw_frame, str(self.camera_id))
                            packet = EvidencePacket(
                                camera_id=str(self.camera_id),
                                timestamp=time.time(),
                                frame=res.get("frame", raw_frame),
                                motion_detected=True,
                                motion_score=score,
                                num_people=res.get("num_people", 0),
                                alert_triggered=bool(res.get("alert_triggered", False)),
                                alerts=res.get("alerts", []),
                                detections=res.get("detections", {"behavior": [], "contraband": []}),
                                processing_mode=res.get("processing_mode", "Standard")
                            )
                        else:
                            # Skip full AI, gate locally on CPU
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
                    else:
                        # Fallback for BasicMotionEngine
                        res = _pose_engine.process_frame(raw_frame, str(self.camera_id))
                        packet = EvidencePacket.from_dict(res)
                        packet.camera_id = str(self.camera_id)
                        packet.timestamp = time.time()
                except Exception as e:
                    print(f"Worker AI Error (Cam {self.camera_id}): {e}")

            if packet is None:
                packet = EvidencePacket(
                    camera_id=str(self.camera_id),
                    timestamp=time.time(),
                    frame=raw_frame,
                    processing_mode="No Engine"
                )

            # Convert to RGB and resize in background to save main thread time
            try:
                frame_to_show = packet.frame
                alert_active = packet.alert_triggered
                rgb = cv2.cvtColor(frame_to_show, cv2.COLOR_BGR2RGB)
                # We put the processed data into the queue
                if self.result_queue.full():
                    try:
                        self.result_queue.get_nowait() # Drop slowest if full
                    except queue.Empty:
                        pass
                self.result_queue.put((rgb, alert_active))
                
                # --- INCIDENT RECORDING LOGIC ---
                self.recorder.process_frame(frame_to_show, packet.to_dict())
            except Exception as e:
                print(f"Worker process error: {e}")

            # Small sleep to prevent 100% CPU usage if everything is too fast
            time.sleep(0.001)

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        # Unregister camera
        utils.GlobalState.unregister_camera(self.camera_id)

    def update_loop(self):
        if not self.running:
            return

        frame_rgb = None
        alert_triggered = False

        # --- real camera (poll queue) ---
        if self.source is not None:
            try:
                # Try to get latest from worker (non-blocking)
                rgb_data, alert_triggered = self.result_queue.get_nowait()
                frame_rgb = rgb_data
            except queue.Empty:
                # If no new frame from worker, just continue with old or skip
                frame_rgb = None
                # We don't return here so we don't break the loop, 
                # but we'll skip the drawing block if frame_rgb is None
                pass
            
            # Special case for "Signal Lost" handled by worker not putting data
            if frame_rgb is None and (not self.cap or not self.cap.isOpened()):
                self.draw_placeholder("Signal Lost")
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
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw < 10 or ch < 10:
                cw, ch = 320, 240

            img_pil = Image.fromarray(frame_rgb)
            img_pil = img_pil.resize((cw, ch))
            self.tk_image = ImageTk.PhotoImage(img_pil)
            self.last_frame_rgb = frame_rgb
            
            # Optimized rendering: Update existing item instead of recreating
            if not hasattr(self, 'image_id') or self.image_id is None:
                self.image_id = self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")
            else:
                self.canvas.itemconfig(self.image_id, image=self.tk_image)

        # --- status ---
        # Show status from the recorder (NORMAL, RECORDING, or COOLDOWN)
        status_text, status_color = self.recorder.get_status_info()
        self.lbl_status.configure(text=status_text, foreground=status_color)
        
        # Update global alert state
        utils.GlobalState.set_alert(self.camera_id, self.recorder.state == self.recorder.RECORDING)

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
