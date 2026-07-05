import os
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import customtkinter as ctk
import cv2
from PIL import Image


PALETTE = {
    "page": "#10161d",
    "panel": "#171f29",
    "panel_alt": "#1c2531",
    "card": "#1b2430",
    "card_soft": "#202b38",
    "surface": "#0d131a",
    "border": "#26384a",
    "text": "#f3f7fb",
    "muted": "#8da1b4",
    "subtle": "#617487",
    "accent": "#4f84bb",
    "accent_hover": "#426f9b",
    "success": "#42c08d",
    "warning": "#d7a75a",
    "danger": "#d86161",
}


def ensure_incidents_schema(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            event_id TEXT PRIMARY KEY,
            camera_id TEXT,
            timestamp_start TEXT,
            timestamp_end TEXT,
            event_type TEXT,
            confidence_scores TEXT,
            video_path TEXT,
            comments TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            retention_days INTEGER,
            review_status TEXT DEFAULT 'PENDING'
        )
        """
    )

    cursor.execute("PRAGMA table_info(incidents)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = [
        ("timestamp_end", "TEXT", None),
        ("event_type", "TEXT", None),
        ("confidence_scores", "TEXT", None),
        ("video_path", "TEXT", None),
        ("comments", "TEXT", None),
        ("reviewed_by", "TEXT", None),
        ("reviewed_at", "TEXT", None),
        ("retention_days", "INTEGER", None),
        ("review_status", "TEXT", "'PENDING'"),
    ]
    for name, col_type, default in columns:
        if name in existing:
            continue
        default_clause = f" DEFAULT {default}" if default is not None else ""
        cursor.execute(f"ALTER TABLE incidents ADD COLUMN {name} {col_type}{default_clause}")

    conn.commit()
    conn.close()


def _status_style(status):
    normalized = (status or "PENDING").upper()
    if normalized == "CONFIRMED":
        return "CONFIRMED", PALETTE["danger"]
    if normalized == "FALSE ALARM":
        return "FALSE ALARM", PALETTE["success"]
    if normalized == "NEEDS REVIEW":
        return "NEEDS REVIEW", PALETTE["warning"]
    return "PENDING", PALETTE["accent"]


class IncidentsScreen(ttk.Frame):
    def __init__(self, parent, current_user="Unknown"):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        from monitor_app.utils import data_path
        self.db_path = data_path("incidents.db")
        self.current_user = current_user
        self.summary_labels = {}

        try:
            ensure_incidents_schema(self.db_path)
            print("Database audit columns verified.")
        except Exception as e:
            print(f"Migration Warning: {e}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self.refresh_overview()

    def _build_header(self):
        header = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
        )
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(12, 10))
        header.grid_columnconfigure(0, weight=1)

        copy_block = ctk.CTkFrame(header, fg_color="transparent")
        copy_block.grid(row=0, column=0, sticky="w", padx=20, pady=14)

        ctk.CTkLabel(
            copy_block,
            text="INCIDENT REVIEW CENTER",
            font=("Segoe UI Semibold", 11),
            text_color=PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            copy_block,
            text="Incidents",
            font=("Bahnschrift SemiBold", 24),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(anchor="w", pady=(6, 6))

        ctk.CTkLabel(
            copy_block,
            text=(
                "Review recorded evidence, validate events, and maintain operator audit "
                "decisions from a single controlled workspace."
            ),
            font=("Segoe UI", 12),
            text_color=PALETTE["muted"],
            wraplength=560,
            justify="left",
            anchor="w",
        ).pack(anchor="w")

        summary = ctk.CTkFrame(header, fg_color="transparent")
        summary.grid(row=0, column=1, sticky="e", padx=20, pady=14)

        for label in ("Pending Queue", "Needs Review", "Confirmed"):
            card = ctk.CTkFrame(
                summary,
                fg_color=PALETTE["card"],
                corner_radius=18,
                border_width=1,
                border_color=PALETTE["border"],
                width=120,
                height=86,
            )
            card.pack(side="left", padx=(0, 10))
            card.pack_propagate(False)

            ctk.CTkLabel(
                card,
                text=label,
                font=("Segoe UI", 11),
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(10, 2))

            value = ctk.CTkLabel(
                card,
                text="0",
                font=("Bahnschrift SemiBold", 22),
                text_color=PALETTE["text"],
                anchor="w",
            )
            value.pack(anchor="w", padx=12, pady=(0, 10))
            self.summary_labels[label] = value

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=20, pady=14)

        btn_offline = ctk.CTkButton(
            actions,
            text="Offline Analysis Center",
            command=self._open_offline_analysis,
            fg_color=PALETTE["accent"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 12),
        )
        btn_offline.pack(side="right")

    def _open_offline_analysis(self):
        from monitor_app.offline_ui import OfflineAnalysisCenterDialog
        dlg = OfflineAnalysisCenterDialog(self)
        dlg.grab_set()

    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
            segmented_button_fg_color=PALETTE["card_soft"],
            segmented_button_selected_color=PALETTE["accent"],
            segmented_button_selected_hover_color=PALETTE["accent_hover"],
            segmented_button_unselected_color=PALETTE["card_soft"],
            segmented_button_unselected_hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            text_color_disabled=PALETTE["subtle"],
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 18))

        self.tab_handling = self.tabview.add("Incident Handling & Validation")
        self.tab_history = self.tabview.add("Incident History Log")

        self.review_tab = IncidentReviewDetail(
            self.tab_handling,
            self.db_path,
            self.on_incident_updated,
            self.current_user,
        )
        self.review_tab.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_tab = IncidentLogTable(self.tab_history, self.db_path, self.on_log_selected)
        self.log_tab.pack(fill="both", expand=True, padx=10, pady=10)

    def stop_monitoring(self):
        self.review_tab.stop_monitoring()

    def refresh_overview(self):
        snapshot = {
            "Pending Queue": 0,
            "Needs Review": 0,
            "Confirmed": 0,
        }

        if os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT review_status, COUNT(*) FROM incidents GROUP BY review_status")
                for status, count in cursor.fetchall():
                    normalized = (status or "PENDING").upper()
                    if normalized == "PENDING":
                        snapshot["Pending Queue"] = count
                    elif normalized == "NEEDS REVIEW":
                        snapshot["Needs Review"] = count
                    elif normalized == "CONFIRMED":
                        snapshot["Confirmed"] = count
            finally:
                conn.close()

        for label, widget in self.summary_labels.items():
            widget.configure(text=str(snapshot[label]))

    def on_log_selected(self, event_data):
        self.tabview.set("Incident Handling & Validation")
        self.review_tab.load_incident(event_data)

    def on_incident_updated(self):
        self.log_tab.refresh_data()
        self.refresh_overview()


class IncidentReviewDetail(ctk.CTkFrame):
    def __init__(self, parent, db_path, on_update_callback, current_user):
        super().__init__(parent, fg_color="transparent")
        self.db_path = db_path
        self.on_update_callback = on_update_callback
        self.current_user = current_user
        self.current_incident = None

        self.video_cap = None
        self.is_playing = False
        self._playback_job = None
        self._current_frame_img = None

        self.detail_vars = {
            "id": tk.StringVar(value="No selection"),
            "camera": tk.StringVar(value="-"),
            "time": tk.StringVar(value="-"),
            "type": tk.StringVar(value="-"),
            "reviewed_by": tk.StringVar(value="-"),
            "retention": tk.StringVar(value="-"),
        }

        self.grid_columnconfigure(0, weight=8, uniform="incidents_cols")
        self.grid_columnconfigure(1, weight=3, uniform="incidents_cols")
        self.grid_rowconfigure(0, weight=1)

        self.create_widgets()
        self._check_playback_stop()

    def stop_monitoring(self):
        self.stop_playback()

    def create_widgets(self):
        self.left_panel = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(1, weight=1)

        playback_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        playback_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        playback_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            playback_header,
            text="Evidence Playback",
            font=("Bahnschrift SemiBold", 23),
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.playback_state = ctk.CTkLabel(
            playback_header,
            text="Select an incident from the history log",
            font=("Segoe UI", 12),
            text_color=PALETTE["muted"],
            anchor="e",
        )
        self.playback_state.grid(row=0, column=1, sticky="e")

        self.video_player_container = ctk.CTkFrame(
            self.left_panel,
            fg_color=PALETTE["surface"],
            corner_radius=22,
            border_width=1,
            border_color=PALETTE["border"],
            width=640,
            height=360,
        )
        self.video_player_container.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        self.video_player_container.grid_propagate(False)
        self.video_player_container.grid_columnconfigure(0, weight=1)
        self.video_player_container.grid_rowconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(
            self.video_player_container,
            text="Select an incident from the history log to load evidence.",
            text_color=PALETTE["subtle"],
            font=("Segoe UI", 14),
            compound="center",
        )
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

        controls = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))

        control_row = ctk.CTkFrame(controls, fg_color="transparent")
        control_row.pack(fill="x")

        self.btn_back = ctk.CTkButton(
            control_row,
            text="<< 10s",
            width=98,
            height=40,
            corner_radius=12,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=lambda: self.seek_video(-10),
        )
        self.btn_back.pack(side="left", padx=(0, 10))

        self.btn_play = ctk.CTkButton(
            control_row,
            text="Play Evidence",
            height=40,
            corner_radius=12,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.open_video,
        )
        self.btn_play.pack(side="left", padx=(0, 10))

        self.btn_forward = ctk.CTkButton(
            control_row,
            text="10s >>",
            width=98,
            height=40,
            corner_radius=12,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=lambda: self.seek_video(10),
        )
        self.btn_forward.pack(side="left")

        self.playback_note = ctk.CTkLabel(
            controls,
            text="Playback controls are available once a valid incident clip is selected.",
            font=("Segoe UI", 11),
            text_color=PALETTE["subtle"],
            anchor="w",
            justify="left",
        )
        self.playback_note.pack(anchor="w", pady=(12, 0))

        self.right_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)

        self._build_details_card()

    def _build_details_card(self):
        self.details_card = ctk.CTkScrollableFrame(
            self.right_panel,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.details_card.grid(row=0, column=0, sticky="nsew")

        header = ctk.CTkFrame(self.details_card, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(18, 14))

        ctk.CTkLabel(
            header,
            text="Incident Details",
            font=("Bahnschrift SemiBold", 21),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(side="left")

        self.status_chip = ctk.CTkLabel(
            header,
            text="PENDING",
            font=("Segoe UI Semibold", 11),
            text_color=PALETTE["accent"],
            fg_color=PALETTE["card_soft"],
            corner_radius=999,
            padx=14,
            pady=7,
        )
        self.status_chip.pack(side="right")

        rows = ctk.CTkFrame(self.details_card, fg_color="transparent")
        rows.pack(fill="x", padx=18, pady=(0, 12))
        rows.grid_columnconfigure((0, 1), weight=1)

        field_layout = [
            ("Incident ID", "id", 0, 0),
            ("Camera", "camera", 0, 1),
            ("Timestamp", "time", 1, 0),
            ("Detected", "type", 1, 1),
            ("Reviewed By", "reviewed_by", 2, 0),
            ("Retention", "retention", 2, 1),
        ]

        for label, key, row, column in field_layout:
            tile = ctk.CTkFrame(
                rows,
                fg_color=PALETTE["card"],
                corner_radius=16,
                border_width=1,
                border_color=PALETTE["border"],
            )
            tile.grid(row=row, column=column, sticky="ew", padx=5, pady=5)

            ctk.CTkLabel(
                tile,
                text=label,
                font=("Segoe UI", 11),
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(9, 2))

            ctk.CTkLabel(
                tile,
                textvariable=self.detail_vars[key],
                font=("Segoe UI Semibold", 12),
                text_color=PALETTE["text"],
                anchor="w",
                justify="left",
                wraplength=120,
            ).pack(anchor="w", fill="x", padx=12, pady=(0, 9))

        validation_wrap = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card_soft"],
            corner_radius=18,
            border_width=1,
            border_color=PALETTE["border"],
        )
        validation_wrap.pack(fill="x", padx=18, pady=(6, 18))

        ctk.CTkLabel(
            validation_wrap,
            text="Decision & Notes",
            font=("Segoe UI Semibold", 12),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(12, 8))

        self.comment_box = ctk.CTkTextbox(
            validation_wrap,
            height=58,
            font=("Segoe UI", 12),
            fg_color=PALETTE["card"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text"],
        )
        self.comment_box.pack(fill="x", padx=14, pady=(0, 12))

        actions = ctk.CTkFrame(validation_wrap, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 10))
        actions.grid_columnconfigure((0, 1), weight=1)

        primary_buttons = [
            ("Confirm Incident", "CONFIRMED", PALETTE["danger"], "#b94f4f", 0),
            ("False Alarm", "FALSE ALARM", PALETTE["success"], "#32956b", 1),
        ]

        for text, status, color, hover, column in primary_buttons:
            ctk.CTkButton(
                actions,
                text=text,
                height=42,
                corner_radius=12,
                fg_color=color,
                hover_color=hover,
                text_color=PALETTE["text"],
                font=("Segoe UI Semibold", 12),
                command=lambda state=status: self.update_status(state),
            ).grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0), pady=(0, 10))

        ctk.CTkButton(
            actions,
            text="Mark for Review",
            height=38,
            corner_radius=12,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=lambda: self.update_status("NEEDS REVIEW"),
        ).grid(row=1, column=0, columnspan=2, sticky="ew")

        self.feedback_label = ctk.CTkLabel(
            validation_wrap,
            text="No incident selected.",
            font=("Segoe UI", 11),
            text_color=PALETTE["subtle"],
            justify="left",
            wraplength=280,
            anchor="w",
        )
        self.feedback_label.pack(fill="x", padx=14, pady=(0, 12))

    def load_incident(self, data):
        self.current_incident = data
        self.detail_vars["id"].set(data.get("event_id", "-"))
        self.detail_vars["camera"].set(f"Cam {data.get('camera_id', '-')}")
        self.detail_vars["time"].set(self._format_timestamp(data.get("timestamp_start", "")))
        self.detail_vars["type"].set(data.get("event_type", "Unknown"))
        self.detail_vars["reviewed_by"].set(data.get("reviewed_by") or "Unassigned")

        retention = data.get("retention_days")
        self.detail_vars["retention"].set(f"{retention} days" if retention else "Not set")

        status_text, status_color = _status_style(data.get("review_status"))
        self.status_chip.configure(text=status_text, text_color=status_color)

        self.comment_box.delete("1.0", tk.END)
        self.comment_box.insert("1.0", data.get("comments") or "")

        video_path = data.get("video_path", "")
        if video_path and os.path.exists(video_path):
            self.video_label.configure(text="Playback ready.\nClick Play Evidence to review the clip.", image="")
            self.playback_state.configure(text=os.path.basename(video_path))
            self.playback_note.configure(text="Loaded evidence clip is ready for review and time seeking.")
            self.feedback_label.configure(
                text="Incident loaded. Review notes and select the appropriate audit decision.",
                text_color=PALETTE["muted"],
            )
        else:
            self.video_label.configure(text="Video file not found.", image="")
            self.playback_state.configure(text="Missing evidence file")
            self.playback_note.configure(text="This incident record does not currently have a playable clip.")
            self.feedback_label.configure(
                text="Incident loaded, but the stored video file could not be found.",
                text_color=PALETTE["warning"],
            )

        self.stop_playback()

    def open_video(self):
        if self.is_playing:
            self.stop_playback()
            return

        if not self.current_incident:
            self.feedback_label.configure(text="Select an incident from the history log first.", text_color=PALETTE["warning"])
            return

        path = os.path.abspath(self.current_incident.get("video_path", ""))
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Video file no longer exists.")
            return

        self.start_playback(path)

    def start_playback(self, path):
        self.stop_playback()
        self.video_cap = cv2.VideoCapture(path)
        if not self.video_cap.isOpened():
            messagebox.showerror("Error", "Failed to open the stored evidence clip.")
            return

        self.is_playing = True
        self.btn_play.configure(text="Stop Playback", fg_color=PALETTE["danger"], hover_color="#b94f4f")
        self.feedback_label.configure(
            text="Playback started. Review the evidence before saving a decision.",
            text_color=PALETTE["muted"],
        )
        self._play_next_frame()

    def stop_playback(self):
        self.is_playing = False
        if self._playback_job:
            self.after_cancel(self._playback_job)
            self._playback_job = None
        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        self.btn_play.configure(
            text="Play Evidence",
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
        )
        if self.current_incident:
            self.video_label.configure(image="")

    def seek_video(self, seconds):
        if not self.video_cap:
            return

        fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 20
        current_frame = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES))
        target_frame = max(0, current_frame + int(seconds * fps))
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        if not self.is_playing:
            self._render_single_frame()

    def _render_single_frame(self):
        if not self.video_cap:
            return
        ret, frame = self.video_cap.read()
        if ret:
            self._display_frame(frame)

    def _play_next_frame(self):
        if not self.is_playing or not self.video_cap:
            return

        ret, frame = self.video_cap.read()
        if not ret:
            self.stop_playback()
            self.feedback_label.configure(
                text="Playback finished. You can start the clip again or save a decision.",
                text_color=PALETTE["muted"],
            )
            return

        self._display_frame(frame)
        self._playback_job = self.after(45, self._play_next_frame)

    def _display_frame(self, frame):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Use parent container's dimensions to prevent feedback loop resizing
        c_width = self.video_player_container.winfo_width()
        c_height = self.video_player_container.winfo_height()
        
        # Account for video_label's grid padding (padx=14, pady=14 -> 28 total)
        avail_w = c_width - 28
        avail_h = c_height - 28

        if avail_w > 10 and avail_h > 10:
            # Preserve original aspect ratio
            img_h, img_w = frame.shape[:2]
            ratio = min(avail_w / img_w, avail_h / img_h)
            new_w = max(1, int(img_w * ratio))
            new_h = max(1, int(img_h * ratio))
            
            frame = cv2.resize(frame, (new_w, new_h))
            target_size = (new_w, new_h)
        else:
            target_size = (frame.shape[1], frame.shape[0])

        image = Image.fromarray(frame)
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=target_size)
        self._current_frame_img = ctk_image
        self.video_label.configure(image=ctk_image, text="")

    def _check_playback_stop(self):
        if not self.is_playing and self.btn_play.cget("text") == "Stop Playback":
            self.stop_playback()
        self.after(1000, self._check_playback_stop)

    def update_status(self, status):
        if not self.current_incident:
            self.feedback_label.configure(
                text="Select an incident before saving a validation decision.",
                text_color=PALETTE["warning"],
            )
            return

        current_status = (self.current_incident.get("review_status") or "PENDING").upper()
        if current_status == "CONFIRMED":
            messagebox.showwarning("Security Audit", "Confirmed incidents are locked for evidence integrity.")
            return

        comments = self.comment_box.get("1.0", tk.END).strip()
        review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        retention_map = {"CONFIRMED": 90, "FALSE ALARM": 7, "NEEDS REVIEW": 15}
        retention = retention_map.get(status, 15)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE incidents
                SET review_status=?, comments=?, reviewed_by=?, reviewed_at=?, retention_days=?
                WHERE event_id=?
                """,
                (
                    status,
                    comments,
                    self.current_user,
                    review_time,
                    retention,
                    self.current_incident["event_id"],
                ),
            )
            conn.commit()
            conn.close()

            self.current_incident["review_status"] = status
            self.current_incident["comments"] = comments
            self.current_incident["reviewed_by"] = self.current_user
            self.current_incident["reviewed_at"] = review_time
            self.current_incident["retention_days"] = retention

            status_text, status_color = _status_style(status)
            self.status_chip.configure(text=status_text, text_color=status_color)
            self.detail_vars["reviewed_by"].set(self.current_user)
            self.detail_vars["retention"].set(f"{retention} days")
            self.feedback_label.configure(
                text=f"Audit saved at {review_time}. Decision recorded as {status_text}.",
                text_color=status_color,
            )

            if self.on_update_callback:
                self.on_update_callback()
        except Exception as e:
            messagebox.showerror("Database Error", str(e))

    def _format_timestamp(self, raw_timestamp):
        if not raw_timestamp:
            return "-"
        try:
            parsed = datetime.fromisoformat(raw_timestamp)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw_timestamp


class IncidentLogTable(ctk.CTkFrame):
    def __init__(self, parent, db_path, on_select_callback):
        super().__init__(parent, fg_color="transparent")
        self.db_path = db_path
        self.on_select_callback = on_select_callback
        self.rows = []
        self.count_label = None

        self._configure_tree_style()
        self.create_widgets()
        self.refresh_data()

    def _configure_tree_style(self):
        style = ttk.Style()
        style.configure(
            "Incidents.Treeview",
            background=PALETTE["card"],
            foreground=PALETTE["text"],
            fieldbackground=PALETTE["card"],
            rowheight=34,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "Incidents.Treeview",
            background=[("selected", PALETTE["accent"])],
            foreground=[("selected", PALETTE["text"])],
        )
        style.configure(
            "Incidents.Treeview.Heading",
            background=PALETTE["panel_alt"],
            foreground=PALETTE["text"],
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Incidents.Treeview.Heading",
            background=[("active", PALETTE["panel_alt"])],
            foreground=[("active", PALETTE["text"])],
        )

    def create_widgets(self):
        header = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
        )
        header.pack(fill="x", pady=(0, 14))

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.pack(side="left", padx=22, pady=22)

        ctk.CTkLabel(
            title_wrap,
            text="Incident History Log",
            font=("Bahnschrift SemiBold", 26),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_wrap,
            text="Review archived events and load any row directly into the validation workspace.",
            font=("Segoe UI", 12),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        toolbar = ctk.CTkFrame(header, fg_color="transparent")
        toolbar.pack(side="right", padx=22, pady=22)

        self.count_label = ctk.CTkLabel(
            toolbar,
            text="0 incidents",
            font=("Segoe UI", 12),
            text_color=PALETTE["muted"],
        )
        self.count_label.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            toolbar,
            text="Refresh Log",
            width=112,
            height=38,
            corner_radius=12,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.refresh_data,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            toolbar,
            text="Open Records",
            width=122,
            height=38,
            corner_radius=12,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.open_records_folder,
        ).pack(side="left")

        table_card = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=PALETTE["border"],
        )
        table_card.pack(fill="both", expand=True)

        table_wrap = tk.Frame(table_card, bg=PALETTE["panel"])
        table_wrap.pack(fill="both", expand=True, padx=18, pady=18)

        columns = ("id", "time", "cam", "type", "status")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            style="Incidents.Treeview",
        )

        headings = {
            "id": "Event ID",
            "time": "Timestamp",
            "cam": "Camera",
            "type": "Incident Type",
            "status": "Validation Status",
        }
        widths = {
            "id": 190,
            "time": 150,
            "cam": 100,
            "type": 240,
            "status": 160,
        }

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center")

        y_scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_row_click)

        self.tree.tag_configure("CONFIRMED", foreground=PALETTE["danger"])
        self.tree.tag_configure("FALSE ALARM", foreground=PALETTE["success"])
        self.tree.tag_configure("NEEDS REVIEW", foreground=PALETTE["warning"])
        self.tree.tag_configure("PENDING", foreground=PALETTE["accent"])

    def open_records_folder(self):
        records_dir = "recordings"
        os.makedirs(records_dir, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(records_dir)
        else:
            messagebox.showinfo("Records", os.path.abspath(records_dir))

    def refresh_data(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not os.path.exists(self.db_path):
            self.count_label.configure(text="0 incidents")
            return

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents ORDER BY timestamp_start DESC")
            self.rows = cursor.fetchall()
            conn.close()

            for row in self.rows:
                display_time = self._format_row_time(row["timestamp_start"])
                status_text, _ = _status_style(row["review_status"])
                self.tree.insert(
                    "",
                    tk.END,
                    iid=row["event_id"],
                    values=(
                        row["event_id"],
                        display_time,
                        f"Cam {row['camera_id']}",
                        row["event_type"],
                        status_text,
                    ),
                    tags=(status_text,),
                )

            self.count_label.configure(text=f"{len(self.rows)} incidents")
        except Exception as e:
            print(f"Table Refresh Error: {e}")

    def on_row_click(self, _event):
        selected = self.tree.selection()
        if not selected:
            return

        event_id = selected[0]
        for row in self.rows:
            if row["event_id"] == event_id:
                if self.on_select_callback:
                    self.on_select_callback(dict(row))
                break

    def _format_row_time(self, timestamp):
        if not timestamp:
            return "-"
        try:
            parsed = datetime.fromisoformat(timestamp)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return timestamp
