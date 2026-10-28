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
    "card_selected": ("#e0e7ff", "#1e293b"),
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


def _format_time_sec(seconds: float) -> str:
    total_sec = max(0, int(seconds))
    m = total_sec // 60
    s = total_sec % 60
    return f"{m:02d}:{s:02d}"


class IncidentsScreen(ctk.CTkFrame):
    def __init__(self, parent, current_user="Unknown"):
        super().__init__(parent, fg_color=PALETTE["page"], corner_radius=0)
        self.pack(fill="both", expand=True)
        from monitor_app.utils import data_path
        self.db_path = data_path("incidents.db")
        self.current_user = current_user
        self.summary_labels = {}
        self.summary_cards = {}

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

        # Real-time EventBus synchronization
        from monitor_app.events import get_event_bus, INCIDENT_START, INCIDENT_STOP, TELEM_DB_WRITE_COMPLETE
        bus = get_event_bus()
        self._bus_handlers = {
            "INCIDENT_START": self._on_live_incident_start,
            "INCIDENT_STOP": self._on_live_incident_stop,
            TELEM_DB_WRITE_COMPLETE: self._on_live_db_complete
        }
        for event, handler in self._bus_handlers.items():
            bus.subscribe(event, handler)

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
            text="INSTITUTIONAL EVIDENCE AUDIT CENTER",
            font=("Segoe UI Semibold", 10),
            text_color=PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            copy_block,
            text="Incidents",
            font=("Bahnschrift SemiBold", 24),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 4))

        ctk.CTkLabel(
            copy_block,
            text=(
                "Unified 3-Pane Incident Review: triage pending evidence clips, scrub timelines, "
                "validate threat telemetry, and maintain immutable audit decisions."
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
                width=124,
                height=86,
                cursor="hand2",
            )
            card.pack(side="left", padx=(0, 10))
            card.pack_propagate(False)

            title_lbl = ctk.CTkLabel(
                card,
                text=label,
                font=("Segoe UI Semibold", 11),
                text_color=PALETTE["muted"],
                anchor="w",
                cursor="hand2",
            )
            title_lbl.pack(anchor="w", padx=12, pady=(10, 2))

            value = ctk.CTkLabel(
                card,
                text="0",
                font=("Bahnschrift SemiBold", 22),
                text_color=PALETTE["text"],
                anchor="w",
                cursor="hand2",
            )
            value.pack(anchor="w", padx=12, pady=(0, 10))
            self.summary_labels[label] = value
            self.summary_cards[label] = card

            # Bind interactive filter click
            for w in (card, title_lbl, value):
                w.bind("<Button-1>", lambda e, l=label: self._filter_from_header(l))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=20, pady=14)

        btn_offline = ctk.CTkButton(
            actions,
            text="Offline Analysis Center",
            command=self._open_offline_analysis,
            fg_color=PALETTE["accent"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 12),
            height=38,
            corner_radius=10,
        )
        btn_offline.pack(side="right")

    def _filter_from_header(self, label: str):
        target_tab = "Incident Handling & Validation"
        if hasattr(self, "tabview") and self.tabview.get() != target_tab:
            self.tabview.set(target_tab)

        filter_map = {
            "Pending Queue": "PENDING",
            "Needs Review": "NEEDS REVIEW",
            "Confirmed": "CONFIRMED",
        }
        status_key = filter_map.get(label, "ALL")
        if hasattr(self, "review_tab") and self.review_tab:
            self.review_tab.set_queue_filter(status_key)

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
        self.review_tab.pack(fill="both", expand=True, padx=6, pady=6)

        self.log_tab = IncidentLogTable(self.tab_history, self.db_path, self.on_log_selected)
        self.log_tab.pack(fill="both", expand=True, padx=10, pady=10)

    def _on_live_incident_start(self, *args, **kwargs):
        self.after(300, self._refresh_live_state)

    def _on_live_incident_stop(self, *args, **kwargs):
        self.after(600, self._refresh_live_state)

    def _on_live_db_complete(self, *args, **kwargs):
        self.after(300, self._refresh_live_state)

    def _refresh_live_state(self):
        try:
            self.refresh_overview()
            if hasattr(self, "review_tab") and self.review_tab:
                self.review_tab.refresh_inbox(auto_select_first=False)
            if hasattr(self, "log_tab") and self.log_tab:
                self.log_tab.refresh_data()
        except Exception:
            pass

    def stop_monitoring(self):
        try:
            from monitor_app.events import get_event_bus
            bus = get_event_bus()
            for event, handler in getattr(self, "_bus_handlers", {}).items():
                bus.unsubscribe(event, handler)
            self._bus_handlers = {}
        except Exception:
            pass
        if hasattr(self, "review_tab") and self.review_tab:
            self.review_tab.stop_monitoring()

    def destroy(self):
        self.stop_monitoring()
        super().destroy()

    def apply_appearance_mode(self):
        if hasattr(self, "log_tab") and self.log_tab:
            self.log_tab.apply_appearance_mode()
        if hasattr(self, "review_tab") and self.review_tab:
            self.review_tab.apply_appearance_mode()

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
        self.review_tab.load_incident(event_data, update_inbox_selection=True)

    def select_incident_by_id(self, incident_id):
        """Auto-select and load a specific incident for immediate review."""
        if not incident_id or not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE event_id = ?", (incident_id,))
            row = cursor.fetchone()
            if row:
                data = dict(row)
                self.tabview.set("Incident Handling & Validation")
                self.review_tab.load_incident(data, update_inbox_selection=True)
            conn.close()
        except Exception as e:
            print(f"select_incident_by_id error: {e}")

    def on_incident_updated(self):
        if hasattr(self, "log_tab") and self.log_tab:
            self.log_tab.refresh_data()
        self.refresh_overview()


class IncidentReviewDetail(ctk.CTkFrame):
    """
    Unified 3-Pane Incident Review Center:
    - Column 0 (~25%): Interactive Incident Queue & Filter Bar
    - Column 1 (~45%): High-Fidelity Forensic Evidence Video Player & Timeline Scrubber
    - Column 2 (~30%): Forensic Dossier, Classified Threats & Auditor Action Panel
    """
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
        self._last_raw_frame = None
        self.fps = 20.0
        self.total_frames = 0
        self.duration_s = 0.0
        self.current_sec = 0.0
        self.is_looping = False
        self._is_scrubbing = False

        self.all_incidents = []
        self.filtered_incidents = []
        self.selected_event_id = None
        self.inbox_cards = {}
        self.current_filter = "ALL"
        self.search_query = ""

        self.detail_vars = {
            "id": tk.StringVar(value="No selection"),
            "camera": tk.StringVar(value="-"),
            "time": tk.StringVar(value="-"),
            "duration": tk.StringVar(value="-"),
            "type": tk.StringVar(value="-"),
            "reviewed_by": tk.StringVar(value="-"),
            "retention": tk.StringVar(value="-"),
        }
        self._raw_stream_visible = False

        # Unified 3-Pane Grid Setup
        self.grid_columnconfigure(0, weight=6, uniform="review_cols")
        self.grid_columnconfigure(1, weight=11, uniform="review_cols")
        self.grid_columnconfigure(2, weight=7, uniform="review_cols")
        self.grid_rowconfigure(0, weight=1)

        self.create_widgets()
        self.refresh_inbox(auto_select_first=True)
        self._check_playback_stop()

    def stop_monitoring(self):
        self.stop_playback()

    def apply_appearance_mode(self):
        # Refresh inbox styling if needed
        self._render_inbox_cards()

    def create_widgets(self):
        self._build_inbox_panel()
        self._build_evidence_player()
        self._build_details_card()

    # =========================================================================
    # PANE 1 (LEFT ~25%): INTERACTIVE INCIDENT QUEUE
    # =========================================================================
    def _build_inbox_panel(self):
        self.inbox_panel = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.inbox_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.inbox_panel.grid_columnconfigure(0, weight=1)
        self.inbox_panel.grid_rowconfigure(2, weight=1)

        # Header with Title, Count Chip and Refresh
        inbox_hdr = ctk.CTkFrame(self.inbox_panel, fg_color="transparent")
        inbox_hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        inbox_hdr.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(inbox_hdr, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_box,
            text="Incident Queue",
            font=("Bahnschrift SemiBold", 17),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(side="left")

        self.inbox_count_chip = ctk.CTkLabel(
            title_box,
            text="0",
            font=("Segoe UI Bold", 10),
            text_color=PALETTE["accent"],
            fg_color=PALETTE["card_soft"],
            corner_radius=8,
            padx=8,
            pady=2,
        )
        self.inbox_count_chip.pack(side="left", padx=(8, 0))

        btn_refresh = ctk.CTkButton(
            inbox_hdr,
            text="⟳",
            width=28,
            height=28,
            corner_radius=6,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI", 13, "bold"),
            command=lambda: self.refresh_inbox(auto_select_first=False),
        )
        btn_refresh.grid(row=0, column=1, sticky="e")

        # Search Bar & Filter Chips
        filter_box = ctk.CTkFrame(self.inbox_panel, fg_color="transparent")
        filter_box.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        filter_box.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            filter_box,
            placeholder_text="Search ID, camera, threat...",
            height=32,
            corner_radius=8,
            border_color=PALETTE["border"],
            fg_color=PALETTE["card"],
            text_color=PALETTE["text"],
            font=("Segoe UI", 11),
        )
        self.search_entry.pack(fill="x", pady=(0, 6))
        self.search_entry.bind("<KeyRelease>", self._on_search_typed)

        self.filter_chips_wrap = ctk.CTkFrame(filter_box, fg_color="transparent")
        self.filter_chips_wrap.pack(fill="x")

        self.filter_buttons = {}
        chip_labels = ["ALL", "PENDING", "CONFIRMED", "FALSE ALARM", "NEEDS REVIEW"]
        for opt in chip_labels:
            short_txt = opt.title() if opt != "ALL" else "All"
            if opt == "FALSE ALARM":
                short_txt = "False"
            elif opt == "NEEDS REVIEW":
                short_txt = "Review"

            btn = ctk.CTkButton(
                self.filter_chips_wrap,
                text=short_txt,
                height=24,
                corner_radius=6,
                fg_color=PALETTE["card_soft"],
                hover_color=PALETTE["panel_alt"],
                text_color=PALETTE["muted"],
                font=("Segoe UI Semibold", 10),
                command=lambda o=opt: self.set_queue_filter(o),
            )
            btn.pack(side="left", padx=(0, 4), expand=True, fill="x")
            self.filter_buttons[opt] = btn

        self._update_filter_button_styles()

        # Scrollable Incident Card Stream
        self.inbox_scroll = ctk.CTkScrollableFrame(
            self.inbox_panel,
            fg_color="transparent",
            corner_radius=0,
        )
        self.inbox_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 10))

    def _update_filter_button_styles(self):
        for opt, btn in self.filter_buttons.items():
            if opt == self.current_filter:
                btn.configure(
                    fg_color=PALETTE["accent"],
                    text_color="#ffffff",
                )
            else:
                btn.configure(
                    fg_color=PALETTE["card_soft"],
                    text_color=PALETTE["muted"],
                )

    def set_queue_filter(self, filter_name: str):
        self.current_filter = (filter_name or "ALL").upper()
        self._update_filter_button_styles()
        self._filter_inbox()

    def _on_search_typed(self, _event=None):
        self.search_query = self.search_entry.get().strip().lower()
        self._filter_inbox()

    def refresh_inbox(self, auto_select_first=False):
        self.all_incidents = []
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM incidents ORDER BY timestamp_start DESC")
                self.all_incidents = [dict(r) for r in cursor.fetchall()]
                conn.close()
            except Exception as e:
                print(f"refresh_inbox error: {e}")

        # Count pending items
        pending_cnt = sum(
            1 for r in self.all_incidents
            if (r.get("review_status") or "PENDING").upper() == "PENDING"
        )
        self.inbox_count_chip.configure(text=f"{pending_cnt} pending")

        self._filter_inbox(auto_select_first=auto_select_first)

    def _filter_inbox(self, auto_select_first=False):
        res = []
        for r in self.all_incidents:
            status = (r.get("review_status") or "PENDING").upper()
            if self.current_filter != "ALL" and status != self.current_filter:
                continue

            if self.search_query:
                eid = str(r.get("event_id", "")).lower()
                cam = str(r.get("camera_id", "")).lower()
                etype = str(r.get("event_type", "")).lower()
                if self.search_query not in eid and self.search_query not in cam and self.search_query not in etype:
                    continue

            res.append(r)

        self.filtered_incidents = res
        self._render_inbox_cards()

        if auto_select_first and self.filtered_incidents and not self.current_incident:
            self.load_incident(self.filtered_incidents[0], update_inbox_selection=True)

    def _render_inbox_cards(self):
        for child in self.inbox_scroll.winfo_children():
            child.destroy()
        self.inbox_cards.clear()

        if not self.filtered_incidents:
            empty_lbl = ctk.CTkLabel(
                self.inbox_scroll,
                text="No incidents found in this filter.",
                font=("Segoe UI", 11),
                text_color=PALETTE["subtle"],
            )
            empty_lbl.pack(pady=24)
            return

        display_limit = 50
        displayed = self.filtered_incidents[:display_limit]
        for inc in displayed:
            eid = inc["event_id"]
            card = self._create_inbox_card(inc)
            self.inbox_cards[eid] = card

        if len(self.filtered_incidents) > display_limit:
            more_lbl = ctk.CTkLabel(
                self.inbox_scroll,
                text=f"+ {len(self.filtered_incidents) - display_limit} older items (search or filter)",
                font=("Segoe UI", 10),
                text_color=PALETTE["subtle"],
            )
            more_lbl.pack(pady=8)

    def _create_inbox_card(self, inc):
        eid = inc["event_id"]
        status = (inc.get("review_status") or "PENDING").upper()
        status_text, status_color = _status_style(status)
        raw_type = inc.get("event_type", "")
        parsed = parse_threat_telemetry(raw_type)

        primary_cat = parsed[0]["category"] if parsed else "neutral"
        if primary_cat == "danger":
            strip_color = PALETTE["danger"]
        elif primary_cat == "warning":
            strip_color = PALETTE["warning"]
        elif primary_cat == "accent":
            strip_color = PALETTE["accent"]
        else:
            strip_color = PALETTE["subtle"]

        is_selected = (self.selected_event_id == eid)
        card_bg = PALETTE["card_selected"] if is_selected else PALETTE["card"]
        border_col = PALETTE["accent"] if is_selected else PALETTE["border"]
        border_w = 2 if is_selected else 1

        card = ctk.CTkFrame(
            self.inbox_scroll,
            fg_color=card_bg,
            corner_radius=10,
            border_width=border_w,
            border_color=border_col,
            cursor="hand2",
        )
        card.pack(fill="x", pady=4, padx=4)

        # Left threat color indicator bar
        strip = ctk.CTkFrame(
            card,
            fg_color=strip_color,
            width=5,
            corner_radius=2,
        )
        strip.pack(side="left", fill="y", padx=(4, 8), pady=4)

        body = ctk.CTkFrame(card, fg_color="transparent", cursor="hand2")
        body.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=6)

        # Top row: Camera badge + Time
        top_row = ctk.CTkFrame(body, fg_color="transparent", cursor="hand2")
        top_row.pack(fill="x")

        cam_txt = f"CAM {inc.get('camera_id', '-')}"
        cam_badge = ctk.CTkLabel(
            top_row,
            text=cam_txt,
            font=("Segoe UI Bold", 9),
            text_color=PALETTE["text"],
            fg_color=PALETTE["card_soft"],
            corner_radius=4,
            padx=6,
            pady=1,
            cursor="hand2",
        )
        cam_badge.pack(side="left")

        time_str = self._format_short_time(inc.get("timestamp_start", ""))
        time_lbl = ctk.CTkLabel(
            top_row,
            text=time_str,
            font=("Segoe UI", 10),
            text_color=PALETTE["muted"],
            anchor="e",
            cursor="hand2",
        )
        time_lbl.pack(side="right")

        # Threat Title
        short_threat = summarize_event_type_short(raw_type, max_items=2)
        threat_lbl = ctk.CTkLabel(
            body,
            text=short_threat,
            font=("Segoe UI Semibold", 11),
            text_color=PALETTE["text"],
            anchor="w",
            cursor="hand2",
        )
        threat_lbl.pack(fill="x", pady=(2, 2))

        # Bottom row: Event ID (clean) & Status Pill
        btm_row = ctk.CTkFrame(body, fg_color="transparent", cursor="hand2")
        btm_row.pack(fill="x")

        id_clean = eid.replace("INC_", "").replace("EVT_", "")
        if len(id_clean) > 16:
            id_clean = id_clean[:14] + ".."

        id_lbl = ctk.CTkLabel(
            btm_row,
            text=id_clean,
            font=("Consolas", 9),
            text_color=PALETTE["subtle"],
            anchor="w",
            cursor="hand2",
        )
        id_lbl.pack(side="left")

        stat_pill = ctk.CTkLabel(
            btm_row,
            text=status_text,
            font=("Segoe UI Bold", 9),
            text_color=status_color,
            fg_color=PALETTE["card_soft"],
            corner_radius=4,
            padx=6,
            pady=1,
            cursor="hand2",
        )
        stat_pill.pack(side="right")

        # Bind click handlers for whole card
        for w in (card, body, top_row, cam_badge, time_lbl, threat_lbl, btm_row, id_lbl, stat_pill):
            w.bind("<Button-1>", lambda e, d=inc: self.load_incident(d, update_inbox_selection=True))

        return card

    def _format_short_time(self, raw_ts):
        if not raw_ts:
            return "-"
        try:
            dt = datetime.fromisoformat(raw_ts)
            return dt.strftime("%b %d, %H:%M")
        except Exception:
            return str(raw_ts)[:16]

    # =========================================================================
    # PANE 2 (CENTER ~45%): HIGH-FIDELITY EVIDENCE VIDEO PLAYER & SCRUBBER
    # =========================================================================
    def _build_evidence_player(self):
        self.left_panel = ctk.CTkFrame(
            self,
            fg_color=PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.left_panel.grid(row=0, column=1, sticky="nsew", padx=4)
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(1, weight=1)

        # 1. Header with Title & Clip File Name
        playback_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        playback_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        playback_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            playback_header,
            text="Evidence Playback",
            font=("Bahnschrift SemiBold", 19),
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.playback_state = ctk.CTkLabel(
            playback_header,
            text="Select an incident from queue",
            font=("Consolas", 11),
            text_color=PALETTE["muted"],
            anchor="e",
        )
        self.playback_state.grid(row=0, column=1, sticky="e")

        # 2. Evidence Video Canvas Container (Frame 0 Poster Preview Target)
        self.video_player_container = ctk.CTkFrame(
            self.left_panel,
            fg_color=PALETTE["surface"],
            corner_radius=16,
            border_width=1,
            border_color=PALETTE["border"],
            width=580,
            height=340,
        )
        self.video_player_container.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.video_player_container.grid_propagate(False)
        self.video_player_container.grid_columnconfigure(0, weight=1)
        self.video_player_container.grid_rowconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(
            self.video_player_container,
            text="Select an incident from the queue to load evidence clip.",
            text_color=PALETTE["subtle"],
            font=("Segoe UI", 13),
            compound="center",
        )
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # 3. Interactive Forensic Timeline Scrubber Bar
        timeline_bar = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        timeline_bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))
        timeline_bar.grid_columnconfigure(1, weight=1)

        self.time_current_lbl = ctk.CTkLabel(
            timeline_bar,
            text="00:00",
            font=("Consolas", 11, "bold"),
            text_color=PALETTE["accent"],
            width=42,
        )
        self.time_current_lbl.grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.timeline_slider = ctk.CTkSlider(
            timeline_bar,
            from_=0,
            to=100,
            command=self._on_slider_scrub,
            progress_color=PALETTE["accent"],
            button_color=PALETTE["accent"],
            button_hover_color=PALETTE["accent_hover"],
            height=16,
        )
        self.timeline_slider.set(0)
        self.timeline_slider.grid(row=0, column=1, sticky="ew")
        self.timeline_slider.bind("<ButtonPress-1>", lambda e: self._on_scrub_start())
        self.timeline_slider.bind("<ButtonRelease-1>", lambda e: self._on_scrub_end())

        self.time_total_lbl = ctk.CTkLabel(
            timeline_bar,
            text="00:00",
            font=("Consolas", 11),
            text_color=PALETTE["muted"],
            width=42,
        )
        self.time_total_lbl.grid(row=0, column=2, sticky="e", padx=(6, 0))

        # 4. Multi-Speed Transport Controls
        controls = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        controls.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 10))

        transport_row = ctk.CTkFrame(controls, fg_color="transparent")
        transport_row.pack(fill="x")

        self.btn_back = ctk.CTkButton(
            transport_row,
            text="<< -5s",
            width=70,
            height=34,
            corner_radius=8,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=lambda: self.seek_video(-5),
        )
        self.btn_back.pack(side="left", padx=(0, 6))

        self.btn_play = ctk.CTkButton(
            transport_row,
            text="Play Evidence",
            width=116,
            height=34,
            corner_radius=8,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 12),
            command=self.open_video,
        )
        self.btn_play.pack(side="left", padx=(0, 6))

        self.btn_forward = ctk.CTkButton(
            transport_row,
            text="+5s >>",
            width=70,
            height=34,
            corner_radius=8,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=lambda: self.seek_video(5),
        )
        self.btn_forward.pack(side="left", padx=(0, 6))

        self.btn_snapshot = ctk.CTkButton(
            transport_row,
            text="📸 Snapshot",
            width=90,
            height=34,
            corner_radius=8,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=self.snapshot_current_frame,
        )
        self.btn_snapshot.pack(side="left", padx=(0, 6))

        self.btn_loop = ctk.CTkButton(
            transport_row,
            text="🔄 Loop: OFF",
            width=90,
            height=34,
            corner_radius=8,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["muted"],
            font=("Segoe UI Semibold", 11),
            command=self._toggle_loop,
        )
        self.btn_loop.pack(side="left")

        self.playback_note = ctk.CTkLabel(
            controls,
            text="Select an incident to review evidence with frame-accurate timeline scrubbing.",
            font=("Segoe UI", 10),
            text_color=PALETTE["subtle"],
            anchor="w",
            justify="left",
        )
        self.playback_note.pack(anchor="w", pady=(6, 0))

        # 5. Prominent 1-Click Continuous Triage Action Bar
        triage_frame = ctk.CTkFrame(
            self.left_panel,
            fg_color=PALETTE["card_soft"],
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
        )
        triage_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 14))

        triage_top = ctk.CTkFrame(triage_frame, fg_color="transparent")
        triage_top.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            triage_top,
            text="CONTINUOUS TRIAGE ACTIONS",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            triage_top,
            text="Auto-advances to next pending incident on action",
            font=("Segoe UI", 9),
            text_color=PALETTE["subtle"],
            anchor="e",
        ).pack(side="right")

        triage_btns = ctk.CTkFrame(triage_frame, fg_color="transparent")
        triage_btns.pack(fill="x", padx=12, pady=(0, 10))
        triage_btns.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.btn_confirm = ctk.CTkButton(
            triage_btns,
            text="✔ Confirm Threat",
            height=36,
            corner_radius=8,
            fg_color=PALETTE["danger"],
            hover_color="#b91c1c",
            text_color="#ffffff",
            font=("Segoe UI Semibold", 11),
            command=lambda: self.update_status("CONFIRMED"),
        )
        self.btn_confirm.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.btn_false = ctk.CTkButton(
            triage_btns,
            text="✖ False Alarm",
            height=36,
            corner_radius=8,
            fg_color=PALETTE["success"],
            hover_color="#15803d",
            text_color="#ffffff",
            font=("Segoe UI Semibold", 11),
            command=lambda: self.update_status("FALSE ALARM"),
        )
        self.btn_false.grid(row=0, column=1, sticky="ew", padx=3)

        self.btn_review = ctk.CTkButton(
            triage_btns,
            text="⚠ Needs Review",
            height=36,
            corner_radius=8,
            fg_color=PALETTE["warning"],
            hover_color="#b45309",
            text_color="#ffffff",
            font=("Segoe UI Semibold", 11),
            command=lambda: self.update_status("NEEDS REVIEW"),
        )
        self.btn_review.grid(row=0, column=2, sticky="ew", padx=3)

        self.btn_extract = ctk.CTkButton(
            triage_btns,
            text="💾 Dataset Export",
            height=36,
            corner_radius=8,
            fg_color=PALETTE["card"],
            border_width=1,
            border_color=PALETTE["border"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=self.extract_to_dataset,
        )
        self.btn_extract.grid(row=0, column=3, sticky="ew", padx=(3, 0))

        self.feedback_label = ctk.CTkLabel(
            triage_frame,
            text="Select an incident from queue to begin review.",
            font=("Segoe UI", 10),
            text_color=PALETTE["subtle"],
            anchor="w",
            justify="left",
            wraplength=480,
        )
        self.feedback_label.pack(fill="x", padx=12, pady=(0, 8))

    # =========================================================================
    # PANE 3 (RIGHT ~30%): FORENSIC DOSSIER & AUDITOR NOTES
    # =========================================================================
    def _build_details_card(self):
        self.right_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)

        self.details_card = ctk.CTkScrollableFrame(
            self.right_panel,
            fg_color=PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.details_card.grid(row=0, column=0, sticky="nsew")

        # 1. Header Card (Title, Status Chip, Record ID + Copy Button)
        header_card = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card"],
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
        )
        header_card.pack(fill="x", padx=12, pady=(12, 10))

        header_top = ctk.CTkFrame(header_card, fg_color="transparent")
        header_top.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header_top,
            text="Incident Dossier",
            font=("Bahnschrift SemiBold", 17),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(side="left")

        self.status_chip = ctk.CTkLabel(
            header_top,
            text="PENDING",
            font=("Segoe UI Bold", 10),
            text_color=PALETTE["accent"],
            fg_color=PALETTE["card_soft"],
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.status_chip.pack(side="right")

        id_bar = ctk.CTkFrame(header_card, fg_color="transparent")
        id_bar.pack(fill="x", padx=12, pady=(0, 10))

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
            font=("Consolas", 10, "bold"),
            text_color=PALETTE["text"],
            anchor="w",
        )
        self.id_label.pack(side="left")

        btn_copy_id = ctk.CTkButton(
            id_bar,
            text="📋",
            width=22,
            height=22,
            corner_radius=4,
            fg_color="transparent",
            hover_color=PALETTE["card_soft"],
            text_color=PALETTE["muted"],
            font=("Segoe UI", 10),
            command=self.copy_event_id,
        )
        btn_copy_id.pack(side="right")

        # 2. Metadata Grid (2x2 symmetrical key-value tiles)
        meta_grid = ctk.CTkFrame(self.details_card, fg_color="transparent")
        meta_grid.pack(fill="x", padx=12, pady=(0, 10))
        meta_grid.grid_columnconfigure((0, 1), weight=1)

        meta_layout = [
            ("CAMERA FEED", "camera", 0, 0),
            ("TIMESTAMP", "time", 0, 1),
            ("DURATION", "duration", 1, 0),
            ("AUDIT OFFICER", "reviewed_by", 1, 1),
        ]

        for label, key, row, col in meta_layout:
            tile = ctk.CTkFrame(
                meta_grid,
                fg_color=PALETTE["card"],
                corner_radius=10,
                border_width=1,
                border_color=PALETTE["border"],
            )
            tile.grid(row=row, column=col, sticky="ew", padx=3, pady=3)

            ctk.CTkLabel(
                tile,
                text=label,
                font=("Segoe UI", 8, "bold"),
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=10, pady=(6, 1))

            ctk.CTkLabel(
                tile,
                textvariable=self.detail_vars[key],
                font=("Segoe UI Semibold", 11),
                text_color=PALETTE["text"],
                anchor="w",
            ).pack(anchor="w", fill="x", padx=10, pady=(0, 6))

        # 3. Classified Threats & Evidence
        self.threat_panel = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card"],
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.threat_panel.pack(fill="x", padx=12, pady=(0, 10))

        threat_header = ctk.CTkFrame(self.threat_panel, fg_color="transparent")
        threat_header.pack(fill="x", padx=12, pady=(10, 4))

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
            pady=1,
        )
        self.threat_count_chip.pack(side="right")

        self.threat_badges_frame = ctk.CTkFrame(self.threat_panel, fg_color="transparent")
        self.threat_badges_frame.pack(fill="x", padx=12, pady=(0, 8))

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
        self.raw_stream_container.pack(fill="x", padx=12, pady=(0, 8))

        self.btn_toggle_raw = ctk.CTkButton(
            self.raw_stream_container,
            text="▸ View Raw Telemetry Stream",
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color=PALETTE["card_soft"],
            text_color=PALETTE["muted"],
            height=22,
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

        # 4. Operator Audit Notes with Fast Preset Tags
        notes_wrap = ctk.CTkFrame(
            self.details_card,
            fg_color=PALETTE["card_soft"],
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
        )
        notes_wrap.pack(fill="x", padx=12, pady=(0, 12))

        notes_head = ctk.CTkFrame(notes_wrap, fg_color="transparent")
        notes_head.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            notes_head,
            text="INVESTIGATION NOTES",
            font=("Segoe UI", 9, "bold"),
            text_color=PALETTE["muted"],
            anchor="w",
        ).pack(side="left")

        # Fast preset comment chips
        preset_row = ctk.CTkFrame(notes_wrap, fg_color="transparent")
        preset_row.pack(fill="x", padx=12, pady=(0, 6))

        presets = [
            ("Weapon", "Confirmed weapon threat, escalating to duty officer."),
            ("Contraband", "Contraband detected, inspection requested."),
            ("False Pos", "Benign activity; verified false positive."),
            ("Clear", "Event reviewed and cleared."),
        ]
        for btn_txt, phrase in presets:
            ctk.CTkButton(
                preset_row,
                text=f"+ {btn_txt}",
                height=22,
                corner_radius=4,
                fg_color=PALETTE["card"],
                hover_color=PALETTE["panel_alt"],
                text_color=PALETTE["muted"],
                font=("Segoe UI", 9),
                command=lambda p=phrase: self._insert_comment_preset(p),
            ).pack(side="left", padx=(0, 4))

        self.comment_box = ctk.CTkTextbox(
            notes_wrap,
            height=68,
            font=("Segoe UI", 11),
            fg_color=PALETTE["card"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text"],
            corner_radius=8,
            wrap="word",
        )
        self.comment_box.pack(fill="x", padx=12, pady=(0, 8))

        # Retention Notice
        retention_row = ctk.CTkFrame(notes_wrap, fg_color="transparent")
        retention_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            retention_row,
            text="RETENTION POLICY:",
            font=("Segoe UI", 8, "bold"),
            text_color=PALETTE["muted"],
        ).pack(side="left")

        self.retention_label = ctk.CTkLabel(
            retention_row,
            textvariable=self.detail_vars["retention"],
            font=("Segoe UI Semibold", 10),
            text_color=PALETTE["text"],
        )
        self.retention_label.pack(side="left", padx=(4, 0))

    def _insert_comment_preset(self, phrase: str):
        existing = self.comment_box.get("1.0", tk.END).strip()
        if existing:
            new_text = f"{existing} | {phrase}"
        else:
            new_text = phrase
        self.comment_box.delete("1.0", tk.END)
        self.comment_box.insert("1.0", new_text)

    def copy_event_id(self):
        eid = self.detail_vars["id"].get()
        if eid and eid != "No selection":
            self.clipboard_clear()
            self.clipboard_append(eid)
            self.feedback_label.configure(
                text=f"Copied Record ID to clipboard: {eid}",
                text_color=PALETTE["accent"],
            )

    def _toggle_raw_stream(self):
        if self._raw_stream_visible:
            self.raw_stream_box.pack_forget()
            self.btn_toggle_raw.configure(text="▸ View Raw Telemetry Stream")
            self._raw_stream_visible = False
        else:
            self.raw_stream_box.pack(fill="x", pady=(4, 0))
            self.btn_toggle_raw.configure(text="▾ Hide Raw Telemetry Stream")
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
                corner_radius=8,
                border_width=1,
                border_color=PALETTE["border"],
            )
            badge.pack(fill="x", pady=2)

            left_side = ctk.CTkFrame(badge, fg_color="transparent")
            left_side.pack(side="left", padx=8, pady=4)

            tag_lbl = ctk.CTkLabel(
                left_side,
                text=threat["tag"],
                font=("Segoe UI", 8, "bold"),
                text_color=fg_tag,
                fg_color=PALETTE["card"],
                corner_radius=4,
                padx=5,
                pady=1,
            )
            tag_lbl.pack(side="left", padx=(0, 6))

            name_lbl = ctk.CTkLabel(
                left_side,
                text=threat["name"],
                font=("Segoe UI Semibold", 11),
                text_color=PALETTE["text"],
                anchor="w",
            )
            name_lbl.pack(side="left")

            right_side = ctk.CTkFrame(badge, fg_color="transparent")
            right_side.pack(side="right", padx=8, pady=4)

            det_lbl = ctk.CTkLabel(
                right_side,
                text=threat["detail"],
                font=("Segoe UI", 10),
                text_color=PALETTE["muted"],
                anchor="e",
            )
            det_lbl.pack(side="right")

    # =========================================================================
    # INCIDENT LOADING & FRAME 0 POSTER PREVIEW
    # =========================================================================
    def load_incident(self, data, update_inbox_selection=True):
        self.stop_playback()
        self.current_incident = data
        eid = data.get("event_id", "-")
        self.selected_event_id = eid

        # Update highlighted state in inbox sidebar
        if update_inbox_selection:
            for cid, card_widget in self.inbox_cards.items():
                if cid == eid:
                    card_widget.configure(
                        fg_color=PALETTE["card_selected"],
                        border_color=PALETTE["accent"],
                        border_width=2,
                    )
                else:
                    card_widget.configure(
                        fg_color=PALETTE["card"],
                        border_color=PALETTE["border"],
                        border_width=1,
                    )

        self.detail_vars["id"].set(eid)
        self.detail_vars["camera"].set(f"Cam {data.get('camera_id', '-')}")
        self.detail_vars["time"].set(self._format_timestamp(data.get("timestamp_start", "")))

        # Compute duration if timestamps available
        t_start = data.get("timestamp_start")
        t_end = data.get("timestamp_end")
        duration_desc = "-"
        if t_start and t_end:
            try:
                d1 = datetime.fromisoformat(t_start)
                d2 = datetime.fromisoformat(t_end)
                delta_sec = max(0, int((d2 - d1).total_seconds()))
                duration_desc = f"{delta_sec}s ({_format_time_sec(delta_sec)})"
            except Exception:
                pass
        self.detail_vars["duration"].set(duration_desc)

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

        # Open video and load Frame 0 poster preview immediately
        video_path = data.get("video_path", "")
        if video_path and os.path.exists(video_path):
            self.playback_state.configure(text=os.path.basename(video_path))
            self._load_video_poster(video_path)
            self.feedback_label.configure(
                text="Evidence clip loaded. Review video and audit notes before saving decision.",
                text_color=PALETTE["muted"],
            )
            self.playback_note.configure(
                text="Loaded evidence clip is ready for playback and forensic scrubbing."
            )
        else:
            self.playback_state.configure(text="Missing evidence file")
            self.video_label.configure(
                text="Recorded evidence clip could not be found on disk.",
                image=None,
            )
            self.timeline_slider.set(0)
            self.time_current_lbl.configure(text="00:00")
            self.time_total_lbl.configure(text="00:00")
            self.feedback_label.configure(
                text="Incident loaded, but associated MP4 recording is missing.",
                text_color=PALETTE["warning"],
            )

    def _load_video_poster(self, video_path):
        """Extracts and renders Frame 0 immediately so canvas is never a blank white box."""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                self.video_label.configure(text="Failed to open video file.", image=None)
                return

            self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
            self.duration_s = self.total_frames / self.fps if self.fps > 0 else 0.0

            # Configure timeline slider
            steps = max(1, int(self.duration_s * 10))
            self.timeline_slider.configure(
                from_=0,
                to=max(1.0, self.duration_s),
                number_of_steps=steps,
            )
            self.timeline_slider.set(0)
            self.current_sec = 0.0

            self.time_current_lbl.configure(text="00:00")
            self.time_total_lbl.configure(text=_format_time_sec(self.duration_s))

            # Read frame 0
            ret, frame = cap.read()
            if ret:
                self._last_raw_frame = frame.copy()
                self._display_frame(frame)
            cap.release()
        except Exception as e:
            print(f"_load_video_poster error: {e}")
            self.video_label.configure(text="Error rendering video poster.", image=None)

    # =========================================================================
    # VIDEO PLAYBACK & FORENSIC TIMELINE SCRUBBING
    # =========================================================================
    def open_video(self):
        if self.is_playing:
            self.pause_playback()
            return

        if not self.current_incident:
            self.feedback_label.configure(
                text="Select an incident from the queue first.",
                text_color=PALETTE["warning"],
            )
            return

        path = os.path.abspath(self.current_incident.get("video_path", ""))
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Video file no longer exists.")
            return

        self.start_playback(path)

    def start_playback(self, path):
        if self._playback_job:
            self.after_cancel(self._playback_job)
            self._playback_job = None

        if not self.video_cap or not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(path)
            if not self.video_cap.isOpened():
                messagebox.showerror("Error", "Failed to open the stored evidence clip.")
                return

            self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 20.0
            self.duration_s = self.total_frames / self.fps if self.fps > 0 else 0.0

            # Seek to current scrub position if starting mid-way
            target_frame = int(self.current_sec * self.fps)
            if target_frame > 0:
                self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, min(target_frame, self.total_frames - 1))

        self.is_playing = True
        self.btn_play.configure(
            text="Pause Evidence",
            fg_color=PALETTE["danger"],
            hover_color="#b94f4f",
        )
        self.feedback_label.configure(
            text="Playback active. Reviewing evidence clip.",
            text_color=PALETTE["muted"],
        )
        self._play_next_frame()

    def pause_playback(self):
        self.is_playing = False
        if self._playback_job:
            self.after_cancel(self._playback_job)
            self._playback_job = None
        self.btn_play.configure(
            text="Play Evidence",
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
        )
        self.feedback_label.configure(
            text="Playback paused. Retaining current forensic frame.",
            text_color=PALETTE["muted"],
        )

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

    def _on_scrub_start(self):
        self._is_scrubbing = True

    def _on_scrub_end(self):
        self._is_scrubbing = False

    def _on_slider_scrub(self, val):
        self.current_sec = float(val)
        self.time_current_lbl.configure(text=_format_time_sec(self.current_sec))

        # Seek in video
        if not self.current_incident:
            return
        video_path = self.current_incident.get("video_path")
        if not video_path or not os.path.exists(video_path):
            return

        if not self.video_cap or not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(video_path)
            self.fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 20.0
            self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))

        target_frame = int(self.current_sec * self.fps)
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, min(target_frame, max(0, self.total_frames - 1)))

        if not self.is_playing:
            self._render_single_frame()

    def seek_video(self, delta_seconds):
        if not self.current_incident:
            return
        video_path = self.current_incident.get("video_path")
        if not video_path or not os.path.exists(video_path):
            return

        if not self.video_cap or not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(video_path)
            self.fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 20.0
            self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self.current_sec = max(0.0, min(self.duration_s, self.current_sec + delta_seconds))
        target_frame = int(self.current_sec * self.fps)
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, min(target_frame, max(0, self.total_frames - 1)))

        self.timeline_slider.set(self.current_sec)
        self.time_current_lbl.configure(text=_format_time_sec(self.current_sec))

        if not self.is_playing:
            self._render_single_frame()

    def _toggle_loop(self):
        self.is_looping = not self.is_looping
        if self.is_looping:
            self.btn_loop.configure(
                text="🔄 Loop: ON",
                fg_color=PALETTE["accent"],
                text_color="#ffffff",
            )
        else:
            self.btn_loop.configure(
                text="🔄 Loop: OFF",
                fg_color=PALETTE["card_soft"],
                text_color=PALETTE["muted"],
            )

    def snapshot_current_frame(self):
        if self._last_raw_frame is None:
            messagebox.showinfo("Snapshot", "No video frame currently loaded to capture.")
            return

        os.makedirs("snapshots", exist_ok=True)
        eid = self.detail_vars["id"].get()
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join("snapshots", f"snapshot_{eid}_{now_str}.jpg")
        try:
            cv2.imwrite(out_path, self._last_raw_frame)
            self.feedback_label.configure(
                text=f"📸 Forensic snapshot saved: {out_path}",
                text_color=PALETTE["accent"],
            )
        except Exception as e:
            messagebox.showerror("Snapshot Error", f"Failed to save snapshot: {e}")

    def _render_single_frame(self):
        if not self.video_cap:
            return
        ret, frame = self.video_cap.read()
        if ret:
            self._last_raw_frame = frame.copy()
            self._display_frame(frame)

    def _play_next_frame(self):
        if not self.is_playing or not self.video_cap:
            return

        ret, frame = self.video_cap.read()
        if not ret:
            if self.is_looping:
                self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.current_sec = 0.0
                self.timeline_slider.set(0)
                self.time_current_lbl.configure(text="00:00")
                self._playback_job = self.after(45, self._play_next_frame)
                return
            else:
                self.pause_playback()
                self.feedback_label.configure(
                    text="Playback completed. Frame retained for review.",
                    text_color=PALETTE["muted"],
                )
                return

        self._last_raw_frame = frame.copy()
        self._display_frame(frame)

        if not self._is_scrubbing:
            cur_frame = self.video_cap.get(cv2.CAP_PROP_POS_FRAMES)
            self.current_sec = cur_frame / self.fps if self.fps > 0 else 0.0
            self.timeline_slider.set(self.current_sec)
            self.time_current_lbl.configure(text=_format_time_sec(self.current_sec))

        self._playback_job = self.after(45, self._play_next_frame)

    def _display_frame(self, frame):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        c_width = self.video_player_container.winfo_width()
        c_height = self.video_player_container.winfo_height()

        avail_w = max(100, c_width - 24)
        avail_h = max(100, c_height - 24)

        img_h, img_w = frame.shape[:2]
        ratio = min(avail_w / img_w, avail_h / img_h)
        new_w = max(1, int(img_w * ratio))
        new_h = max(1, int(img_h * ratio))

        frame_resized = cv2.resize(frame, (new_w, new_h))
        image = Image.fromarray(frame_resized)
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(new_w, new_h))
        self._current_frame_img = ctk_image
        self.video_label.configure(image=ctk_image, text="")

    def _check_playback_stop(self):
        if not self.is_playing and self.btn_play.cget("text") == "Pause Evidence":
            self.stop_playback()
        self.after(1000, self._check_playback_stop)

    # =========================================================================
    # AUDIT DECISION & CONTINUOUS AUTO-ADVANCE TRIAGE
    # =========================================================================
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

        event_id = self.current_incident["event_id"]

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
                    event_id,
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

            # Update cache in all_incidents
            for inc in self.all_incidents:
                if inc["event_id"] == event_id:
                    inc["review_status"] = status
                    inc["comments"] = comments
                    inc["reviewed_by"] = self.current_user
                    inc["reviewed_at"] = review_time
                    inc["retention_days"] = retention
                    break

            if self.on_update_callback:
                self.on_update_callback()

            # Refresh inbox to update card badge
            self.refresh_inbox(auto_select_first=False)

            # Continuous Auto-Advance: automatically select next pending incident
            self.select_next_pending(after_event_id=event_id, last_status=status_text)
        except Exception as e:
            messagebox.showerror("Database Error", str(e))

    def select_next_pending(self, after_event_id=None, last_status=""):
        next_pending = None
        found_target = False if after_event_id else True

        for inc in self.all_incidents:
            if not found_target:
                if inc["event_id"] == after_event_id:
                    found_target = True
                continue
            if (inc.get("review_status") or "PENDING").upper() == "PENDING":
                next_pending = inc
                break

        # Wrap around to beginning of queue if not found after
        if not next_pending:
            for inc in self.all_incidents:
                if inc["event_id"] != after_event_id and (inc.get("review_status") or "PENDING").upper() == "PENDING":
                    next_pending = inc
                    break

        if next_pending:
            self.load_incident(next_pending, update_inbox_selection=True)
            self.feedback_label.configure(
                text=f"Decision '{last_status}' recorded. Auto-advanced to next pending incident: {next_pending['event_id']}",
                text_color=PALETTE["accent"],
            )
        else:
            self.feedback_label.configure(
                text=f"Decision '{last_status}' recorded. All pending incidents have been triaged!",
                text_color=PALETTE["success"],
            )

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

        dataset_base = os.path.join(os.path.dirname(self.db_path), "DatasetRecordings")
        target_dir = os.path.join(dataset_base, safe_slug)
        os.makedirs(target_dir, exist_ok=True)

        target_vid = os.path.join(target_dir, f"{event_id}.mp4")
        try:
            shutil.copy2(video_path, target_vid)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy video: {e}")
            return

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
