import os
import re
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
import shutil

import customtkinter as ctk
import cv2
from PIL import Image


PALETTE = {
    "page": ("#edf2f7", "#10161d"),
    "panel": ("#f8fafc", "#171f29"),
    "panel_alt": ("#e2e8f0", "#1c2531"),
    "card": ("#ffffff", "#1b2430"),
    "card_soft": ("#f1f5f9", "#202b38"),
    "surface": ("#ffffff", "#0d131a"),
    "border": ("#cbd5e1", "#26384a"),
    "text": ("#0f172a", "#f3f7fb"),
    "muted": ("#64748b", "#8da1b4"),
    "subtle": ("#94a3b8", "#617487"),
    "accent": ("#1d4ed8", "#4f84bb"),
    "accent_hover": ("#1e40af", "#426f9b"),
    "success": ("#16a34a", "#42c08d"),
    "warning": ("#d97706", "#d7a75a"),
    "danger": ("#dc2626", "#d86161"),
    "threat_danger_bg": ("#fee2e2", "#2d1517"),
    "threat_warning_bg": ("#fef3c7", "#2e2111"),
    "threat_accent_bg": ("#e0e7ff", "#131d33"),
    "threat_neutral_bg": ("#f1f5f9", "#1e293b"),
}


def parse_threat_telemetry(raw_type: str) -> list:
    """
    Parses complex, concatenated event telemetry strings (including multi-frame
    detections and confidence percentages) into deduplicated, structured records
    with category classifications, peak confidences, and detection counts.
    """
    if not raw_type or not str(raw_type).strip():
        return []

    tokens = [t.strip() for t in re.split(r'[\+\n,]+', str(raw_type)) if t.strip()]
    events = {}
    for tok in tokens:
        m = re.match(r'^(.*?)(?:\s*\(\s*(\d+)%.*?\))?$', tok)
        if m:
            name = m.group(1).strip()
            conf_str = m.group(2)
            conf = int(conf_str) if conf_str else None
        else:
            name = tok
            conf = None

        clean_name = " ".join(name.split())
        if not clean_name:
            continue

        if clean_name.lower() in ("cellphone", "knife", "alert", "gun", "phone"):
            clean_name = clean_name.capitalize()

        if clean_name not in events:
            events[clean_name] = {"count": 0, "max_conf": None}
        events[clean_name]["count"] += 1
        if conf is not None:
            if events[clean_name]["max_conf"] is None or conf > events[clean_name]["max_conf"]:
                events[clean_name]["max_conf"] = conf

    def _get_category_info(name):
        n = name.lower()
        if any(w in n for w in ["knife", "gun", "weapon"]):
            return "danger", "WEAPON"
        elif any(w in n for w in ["fight", "aggressive", "assault", "violence", "brawl"]):
            return "danger", "VIOLENCE"
        elif any(w in n for w in ["cellphone", "phone", "contraband", "cigarette", "lighter"]):
            return "warning", "CONTRABAND"
        elif any(w in n for w in ["movement", "motion", "running", "fall", "loiter"]):
            return "accent", "BEHAVIOR"
        return "neutral", "ALERT"

    threats = []
    for name, data in sorted(events.items(), key=lambda x: (x[1]["max_conf"] or 0, x[1]["count"]), reverse=True):
        cat, tag = _get_category_info(name)
        count = data["count"]
        max_c = data["max_conf"]
        detail_parts = []
        if max_c is not None:
            detail_parts.append(f"Peak: {max_c}%")
        if count > 1:
            detail_parts.append(f"{count} frames")
        detail = " | ".join(detail_parts) if detail_parts else "Detected"
        threats.append({
            "name": name,
            "category": cat,
            "tag": tag,
            "count": count,
            "max_conf": max_c,
            "detail": detail,
        })
    return threats


def summarize_event_type_short(raw_type: str, max_items: int = 3) -> str:
    """Returns a concise 1-line string summarizing detected threats for tables and overviews."""
    threats = parse_threat_telemetry(raw_type)
    if not threats:
        return raw_type or "Unknown"
    parts = []
    for t in threats[:max_items]:
        if t["max_conf"] is not None:
            parts.append(f"{t['name']} ({t['max_conf']}%)")
        elif t["count"] > 1:
            parts.append(f"{t['name']} ({t['count']}x)")
        else:
            parts.append(t["name"])
    if len(threats) > max_items:
        parts.append(f"+{len(threats) - max_items} more")
    return ", ".join(parts)


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


class IncidentsScreen(ctk.CTkFrame):
    def __init__(self, parent, current_user="Unknown"):
        super().__init__(parent, fg_color=PALETTE["page"], corner_radius=0)
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
            corner_radius=14,
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
                corner_radius=14,
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
            corner_radius=14,
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

    def apply_appearance_mode(self):
        if hasattr(self, "log_tab") and self.log_tab:
            self.log_tab.apply_appearance_mode()

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

    def select_incident_by_id(self, incident_id):
        """Auto-select and load a specific incident for immediate review."""
        if not incident_id or not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE event_id = ?", (incident_id,))
            row = cursor.fetchone()
            if row:
                columns = [col[0] for col in cursor.description]
                data = dict(zip(columns, row))
                self.tabview.set("Incident Handling & Validation")
                self.review_tab.load_incident(data)
            conn.close()
        except Exception as e:
            print(f"select_incident_by_id error: {e}")

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
        self._raw_stream_visible = False

        self.grid_columnconfigure(0, weight=13, uniform="incidents_cols")
        self.grid_columnconfigure(1, weight=7, uniform="incidents_cols")
        self.grid_rowconfigure(0, weight=1)

        self.create_widgets()
        self._check_playback_stop()

    def stop_monitoring(self):
        self.stop_playback()

    def create_widgets(self):
        self.left_panel = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=14,
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
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.details_card.grid(row=0, column=0, sticky="nsew")

        # 1. Header Card (Title, Status Chip, Record ID)
        header_card = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        header_card.pack(fill="x", padx=16, pady=(16, 12))

        header_top = ctk.CTkFrame(header_card, fg_color="transparent")
        header_top.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(
            header_top,
            text="Incident Details",
            font=("Bahnschrift SemiBold", 19),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(side="left")

        self.status_chip = ctk.CTkLabel(
            header_top,
            text="PENDING",
            font=("Segoe UI Bold", 10),
            text_color=PALETTE["accent"],
            fg_color=PALETTE["card_soft"],
            corner_radius=8,
            padx=12,
            pady=5,
        )
        self.status_chip.pack(side="right")

        id_bar = ctk.CTkFrame(header_card, fg_color="transparent")
        id_bar.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(
            id_bar,
            text="RECORD ID:",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(side="left", padx=(0, 6))

        self.id_label = ctk.CTkLabel(
            id_bar,
            textvariable=self.detail_vars["id"],
            font=("Consolas", 11, "bold"),
            text_color=PALETTE["text"],
            anchor="w",
        )
        self.id_label.pack(side="left")

        # 2. Metadata Grid (2x2 symmetrical key-value tiles)
        meta_grid = ctk.CTkFrame(self.details_card, fg_color="transparent")
        meta_grid.pack(fill="x", padx=16, pady=(0, 12))
        meta_grid.grid_columnconfigure((0, 1), weight=1)

        meta_layout = [
            ("CAMERA FEED", "camera", 0, 0),
            ("TIMESTAMP", "time", 0, 1),
            ("AUDIT OFFICER", "reviewed_by", 1, 0),
            ("RETENTION", "retention", 1, 1),
        ]

        for label, key, row, col in meta_layout:
            tile = ctk.CTkFrame(
                meta_grid,
                fg_color=PALETTE["card"],
                corner_radius=12,
                border_width=1,
                border_color=PALETTE["border"],
            )
            tile.grid(row=row, column=col, sticky="ew", padx=4, pady=4)

            ctk.CTkLabel(
                tile,
                text=label,
                font=("Segoe UI", 9, "bold"),
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(8, 2))

            ctk.CTkLabel(
                tile,
                textvariable=self.detail_vars[key],
                font=("Segoe UI Semibold", 12),
                text_color=PALETTE["text"],
                anchor="w",
            ).pack(anchor="w", fill="x", padx=12, pady=(0, 8))

        # 3. Classified Threats & Evidence
        self.threat_panel = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.threat_panel.pack(fill="x", padx=16, pady=(0, 12))

        threat_header = ctk.CTkFrame(self.threat_panel, fg_color="transparent")
        threat_header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            threat_header,
            text="CLASSIFIED THREATS & EVIDENCE",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(side="left")

        self.threat_count_chip = ctk.CTkLabel(
            threat_header,
            text="0 items",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            fg_color=PALETTE["card_soft"],
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.threat_count_chip.pack(side="right")

        self.threat_badges_frame = ctk.CTkFrame(self.threat_panel, fg_color="transparent")
        self.threat_badges_frame.pack(fill="x", padx=14, pady=(0, 10))

        self.empty_threat_label = ctk.CTkLabel(
            self.threat_badges_frame,
            text="No threat telemetry recorded.",
            font=("Segoe UI", 11),
            text_color=PALETTE["subtle"],
            anchor="w",
        )
        self.empty_threat_label.pack(anchor="w", pady=4)

        # Raw Stream Toggle & Textbox (Bounded Collapsible)
        self.raw_stream_container = ctk.CTkFrame(self.threat_panel, fg_color="transparent")
        self.raw_stream_container.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_toggle_raw = ctk.CTkButton(
            self.raw_stream_container,
            text="▸ View Raw Stream",
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color=PALETTE["card_soft"],
            text_color=PALETTE["muted"],
            height=24,
            anchor="w",
            command=self._toggle_raw_stream,
        )
        self.btn_toggle_raw.pack(anchor="w")

        self.raw_stream_box = ctk.CTkTextbox(
            self.raw_stream_container,
            height=60,
            font=("Consolas", 10),
            fg_color=PALETTE["panel"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["muted"],
            wrap="word",
        )

        # 4. Operator Audit & Notes Section
        validation_wrap = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card_soft"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        validation_wrap.pack(fill="x", padx=16, pady=(0, 16))

        val_head = ctk.CTkFrame(validation_wrap, fg_color="transparent")
        val_head.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            val_head,
            text="OPERATOR AUDIT & NOTES",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(side="left")

        self.comment_box = ctk.CTkTextbox(
            validation_wrap,
            height=62,
            font=("Segoe UI", 12),
            fg_color=PALETTE["card"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text"],
            corner_radius=10,
        )
        self.comment_box.pack(fill="x", padx=14, pady=(0, 10))

        actions = ctk.CTkFrame(validation_wrap, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 10))
        actions.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            actions,
            text="Confirm Incident",
            height=40,
            corner_radius=10,
            fg_color=PALETTE["danger"],
            hover_color="#b91c1c",
            text_color=("#ffffff", "#ffffff"),
            font=("Segoe UI Semibold", 12),
            command=lambda: self.update_status("CONFIRMED"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 8))

        ctk.CTkButton(
            actions,
            text="False Alarm",
            height=40,
            corner_radius=10,
            fg_color=PALETTE["success"],
            hover_color="#15803d",
            text_color=("#ffffff", "#ffffff"),
            font=("Segoe UI Semibold", 12),
            command=lambda: self.update_status("FALSE ALARM"),
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 8))

        ctk.CTkButton(
            actions,
            text="Mark for Review",
            height=36,
            corner_radius=10,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=lambda: self.update_status("NEEDS REVIEW"),
        ).grid(row=1, column=0, sticky="ew", padx=(0, 4))

        self.btn_extract = ctk.CTkButton(
            actions,
            text="Extract Dataset",
            height=36,
            corner_radius=10,
            fg_color=PALETTE["card"],
            border_width=1,
            border_color=PALETTE["border"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=self.extract_to_dataset,
        )
        self.btn_extract.grid(row=1, column=1, sticky="ew", padx=(4, 0))

        self.feedback_label = ctk.CTkLabel(
            validation_wrap,
            text="No incident selected.",
            font=("Segoe UI", 11),
            text_color=PALETTE["subtle"],
            justify="left",
            wraplength=340,
            anchor="w",
        )
        self.feedback_label.pack(fill="x", padx=14, pady=(8, 12))

    def _toggle_raw_stream(self):
        if self._raw_stream_visible:
            self.raw_stream_box.pack_forget()
            self.btn_toggle_raw.configure(text="▸ View Raw Stream")
            self._raw_stream_visible = False
        else:
            self.raw_stream_box.pack(fill="x", pady=(4, 0))
            self.btn_toggle_raw.configure(text="▾ Hide Raw Stream")
            self._raw_stream_visible = True

    def _update_threat_badges(self, parsed_threats, raw_type):
        for child in self.threat_badges_frame.winfo_children():
            child.destroy()

        self.raw_stream_box.delete("1.0", tk.END)
        self.raw_stream_box.insert("1.0", raw_type or "No raw telemetry.")

        if not parsed_threats:
            ctk.CTkLabel(
                self.threat_badges_frame,
                text="No specific threat classification.",
                font=("Segoe UI", 11),
                text_color=PALETTE["subtle"],
                anchor="w",
            ).pack(anchor="w", pady=4)
            self.threat_count_chip.configure(text="0 items", text_color=PALETTE["muted"])
            return

        total_detections = sum(t["count"] for t in parsed_threats)
        self.threat_count_chip.configure(
            text=f"{len(parsed_threats)} types | {total_detections} hits",
            text_color=PALETTE["accent"],
        )

        cat_colors = {
            "danger": (PALETTE["danger"], PALETTE["threat_danger_bg"]),
            "warning": (PALETTE["warning"], PALETTE["threat_warning_bg"]),
            "accent": (PALETTE["accent"], PALETTE["threat_accent_bg"]),
            "neutral": (PALETTE["muted"], PALETTE["threat_neutral_bg"]),
        }

        for threat in parsed_threats:
            fg_tag, bg_badge = cat_colors.get(threat["category"], cat_colors["neutral"])

            badge = ctk.CTkFrame(
                self.threat_badges_frame,
                fg_color=bg_badge,
                corner_radius=10,
                border_width=1,
                border_color=PALETTE["border"],
            )
            badge.pack(fill="x", pady=3)

            left_side = ctk.CTkFrame(badge, fg_color="transparent")
            left_side.pack(side="left", padx=10, pady=6)

            tag_lbl = ctk.CTkLabel(
                left_side,
                text=threat["tag"],
                font=("Segoe UI", 9, "bold"),
                text_color=fg_tag,
                fg_color=PALETTE["card"],
                corner_radius=4,
                padx=6,
                pady=1,
            )
            tag_lbl.pack(side="left", padx=(0, 8))

            name_lbl = ctk.CTkLabel(
                left_side,
                text=threat["name"],
                font=("Segoe UI Semibold", 12),
                text_color=PALETTE["text"],
                anchor="w",
            )
            name_lbl.pack(side="left")

            right_side = ctk.CTkFrame(badge, fg_color="transparent")
            right_side.pack(side="right", padx=10, pady=6)

            det_lbl = ctk.CTkLabel(
                right_side,
                text=threat["detail"],
                font=("Segoe UI", 11),
                text_color=PALETTE["muted"],
                anchor="e",
            )
            det_lbl.pack(side="right")

    def load_incident(self, data):
        self.current_incident = data
        self.detail_vars["id"].set(data.get("event_id", "-"))
        self.detail_vars["camera"].set(f"Cam {data.get('camera_id', '-')}")
        self.detail_vars["time"].set(self._format_timestamp(data.get("timestamp_start", "")))

        raw_type = data.get("event_type", "")
        parsed_threats = parse_threat_telemetry(raw_type)
        if parsed_threats:
            short_summary = ", ".join([t["name"] for t in parsed_threats[:3]])
            self.detail_vars["type"].set(short_summary)
        else:
            self.detail_vars["type"].set(raw_type or "Unknown")

        self.detail_vars["reviewed_by"].set(data.get("reviewed_by") or "Unassigned")

        retention = data.get("retention_days")
        self.detail_vars["retention"].set(f"{retention} days" if retention else "Not set")

        status_text, status_color = _status_style(data.get("review_status"))
        self.status_chip.configure(text=status_text, text_color=status_color)

        self._update_threat_badges(parsed_threats, raw_type)

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

    def extract_to_dataset(self):
        if not self.current_incident:
            messagebox.showerror("Error", "No incident selected.")
            return
        
        status = (self.current_incident.get("review_status") or "PENDING").upper()
        if status != "CONFIRMED":
            messagebox.showinfo("Extraction Restricted", "Only CONFIRMED incidents can be extracted to the dataset.")
            return

        video_path = self.current_incident.get("video_path")
        if not video_path or not os.path.exists(video_path):
            messagebox.showerror("Error", "Video file not found.")
            return

        raw_event = self.current_incident.get("event_type", "unknown")
        parsed = parse_threat_telemetry(raw_event)
        primary_slug = parsed[0]["name"].replace(" ", "_") if parsed else "incident"
        safe_slug = re.sub(r'[^\w\-_\.]', '_', primary_slug).strip('_')[:40] or "incident"
        event_id = self.current_incident.get("event_id", "incident")

        # Create target directories
        dataset_base = os.path.join(os.path.dirname(self.db_path), "DatasetRecordings")
        target_dir = os.path.join(dataset_base, safe_slug)
        os.makedirs(target_dir, exist_ok=True)

        # Copy video
        target_vid = os.path.join(target_dir, f"{event_id}.mp4")
        try:
            shutil.copy2(video_path, target_vid)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy video: {e}")
            return

        # Extract frame
        target_img = os.path.join(target_dir, f"{event_id}_frame.jpg")
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                mid_frame = max(0, total_frames // 2)
                cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
                ret, frame = cap.read()
                if ret:
                    cv2.imwrite(target_img, frame)
                cap.release()
        except Exception as e:
            print(f"Frame extraction failed: {e}")
            
        messagebox.showinfo("Extraction Complete", f"Saved to DatasetRecordings/{safe_slug}\n- {event_id}.mp4\n- {event_id}_frame.jpg")


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
        mode = ctk.get_appearance_mode()
        is_light = mode == "Light"

        bg_card = "#ffffff" if is_light else "#1b2430"
        fg_text = "#0f172a" if is_light else "#f3f7fb"
        bg_heading = "#e2e8f0" if is_light else "#1c2531"
        fg_heading = "#1e293b" if is_light else "#f3f7fb"
        sel_bg = "#2563eb" if is_light else "#4f84bb"
        sel_fg = "#ffffff"

        style = ttk.Style()
        style.configure(
            "Incidents.Treeview",
            background=bg_card,
            foreground=fg_text,
            fieldbackground=bg_card,
            rowheight=34,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "Incidents.Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)],
        )
        style.configure(
            "Incidents.Treeview.Heading",
            background=bg_heading,
            foreground=fg_heading,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Incidents.Treeview.Heading",
            background=[("active", bg_heading)],
            foreground=[("active", fg_heading)],
        )

        if hasattr(self, "tree") and self.tree:
            self._configure_tree_tags(is_light)

    def _configure_tree_tags(self, is_light=None):
        if is_light is None:
            is_light = ctk.get_appearance_mode() == "Light"
        danger = "#dc2626" if is_light else "#d86161"
        success = "#16a34a" if is_light else "#42c08d"
        warning = "#d97706" if is_light else "#d7a75a"
        accent = "#1d4ed8" if is_light else "#4f84bb"

        if hasattr(self, "tree") and self.tree:
            self.tree.tag_configure("CONFIRMED", foreground=danger)
            self.tree.tag_configure("FALSE ALARM", foreground=success)
            self.tree.tag_configure("NEEDS REVIEW", foreground=warning)
            self.tree.tag_configure("PENDING", foreground=accent)

    def apply_appearance_mode(self):
        self._configure_tree_style()

    def create_widgets(self):
        header = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=14,
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
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        table_card.pack(fill="both", expand=True)

        table_wrap = ctk.CTkFrame(table_card, fg_color="transparent")
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

        self._configure_tree_tags()

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
                display_type = summarize_event_type_short(row["event_type"])
                self.tree.insert(
                    "",
                    tk.END,
                    iid=row["event_id"],
                    values=(
                        row["event_id"],
                        display_time,
                        f"Cam {row['camera_id']}",
                        display_type,
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
