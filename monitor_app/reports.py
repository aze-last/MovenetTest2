import os
import re
import csv
import sqlite3
import webbrowser
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from monitor_app import profile_store
from monitor_app.incidents import parse_threat_telemetry, summarize_event_type_short


class ReportsScreen(ctk.CTkFrame):
    PALETTE = {
        "page": ("#edf2f7", "#10161d"),
        "panel": ("#f8fafc", "#171f29"),
        "panel_alt": ("#e2e8f0", "#1c2531"),
        "card": ("#ffffff", "#1b2430"),
        "card_soft": ("#f1f5f9", "#202b38"),
        "surface": ("#ffffff", "#0d131a"),
        "paper": ("#ffffff", "#151f2b"),
        "paper_border": ("#cbd5e1", "#26384a"),
        "paper_text": ("#0f172a", "#f3f7fb"),
        "border": ("#cbd5e1", "#26384a"),
        "text": ("#0f172a", "#f3f7fb"),
        "muted": ("#64748b", "#8da1b4"),
        "subtle": ("#94a3b8", "#617487"),
        "accent": ("#1d4ed8", "#4f84bb"),
        "accent_hover": ("#1e40af", "#426f9b"),
        "success": ("#16a34a", "#42c08d"),
        "success_hover": ("#15803d", "#32956b"),
        "warning": ("#d97706", "#d7a75a"),
        "danger": ("#dc2626", "#d86161"),
    }

    REPORT_TYPES = [
        "Daily Incident Digest",
        "Contraband & Weapons Seizure Audit",
        "Behavioral & Violence Threat Log",
        "Facility Camera & Security Health Report",
    ]

    REPORT_TYPE_SHORT = {
        "Daily Incident Digest": "Daily Summary",
        "Contraband & Weapons Seizure Audit": "Contraband Audit",
        "Behavioral & Violence Threat Log": "Violence Log",
        "Facility Camera & Security Health Report": "Security Health",
    }

    REPORT_INTROS = {
        "Daily Incident Digest": (
            "Comprehensive institutional operational summary of all recorded CCTV alerts, "
            "confirmed security violations, cleared false alarms, and officer audit decisions."
        ),
        "Contraband & Weapons Seizure Audit": (
            "Specialized forensic audit detailing illicit weapons (knives, blades) and prohibited "
            "contraband (cellular phones, electronics) localized and tracked across facility sectors."
        ),
        "Behavioral & Violence Threat Log": (
            "Aggressive behavior and violence telemetry analysis, surfacing fights, assaults, "
            "and abnormal movement anomalies captured by pose estimation."
        ),
        "Facility Camera & Security Health Report": (
            "Infrastructure and coverage audit evaluating active surveillance feeds, detection density, "
            "and monitoring continuity across correctional cell blocks."
        ),
    }

    def __init__(self, parent):
        super().__init__(parent, fg_color=self.PALETTE["page"], corner_radius=0)
        self.pack(fill="both", expand=True)
        from monitor_app.utils import data_path
        self.db_path = data_path("incidents.db")
        self.branding = profile_store.get_branding()

        self.report_type_var = tk.StringVar(value=self.REPORT_TYPES[0])
        self.date_from_var = tk.StringVar()
        self.date_to_var = tk.StringVar()
        self.camera_filter_var = tk.StringVar(value="All Cameras")
        self.status_filter_var = tk.StringVar(value="All Statuses")

        self.severity_vars = {
            "High (Weapons / Violence)": tk.BooleanVar(value=True),
            "Medium (Contraband)": tk.BooleanVar(value=True),
            "Low (Behavior Alerts)": tk.BooleanVar(value=True),
        }

        self.summary_type_var = tk.StringVar(value=self.REPORT_TYPE_SHORT[self.REPORT_TYPES[0]])
        self.summary_range_var = tk.StringVar(value="All Time")
        self.summary_output_var = tk.StringVar(value="PDF / CSV Export")
        self.preview_state_var = tk.StringVar(value="READY")
        self.preview_meta_var = tk.StringVar(value="Report generated from live audit registry.")

        # Summary Metric Variables
        self.metric_total_var = tk.StringVar(value="0")
        self.metric_confirmed_var = tk.StringVar(value="0")
        self.metric_false_rate_var = tk.StringVar(value="0%")
        self.metric_pending_var = tk.StringVar(value="0")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.page = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.page.grid(row=0, column=0, sticky="nsew")
        self.page.grid_columnconfigure(0, weight=4, uniform="reports")
        self.page.grid_columnconfigure(1, weight=9, uniform="reports")
        self.page.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_filter_panel()
        self._build_preview_panel()
        self.generate_preview()

    def apply_appearance_mode(self):
        self.generate_preview()

    # =========================================================================
    # HEADER SECTION
    # =========================================================================
    def _build_header(self):
        header = ctk.CTkFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)

        copy_block = ctk.CTkFrame(header, fg_color="transparent")
        copy_block.grid(row=0, column=0, sticky="w", padx=20, pady=16)

        ctk.CTkLabel(
            copy_block,
            text="INSTITUTIONAL AUDIT & ANALYTICS CENTER",
            font=("Segoe UI Semibold", 10),
            text_color=self.PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            copy_block,
            text="Reports & Analytics",
            font=("Bahnschrift SemiBold", 26),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 4))

        ctk.CTkLabel(
            copy_block,
            text=(
                "Generate presentation-ready incident reports, analyze contraband and violence trends, "
                "and export official chain-of-custody documentation for facility administration."
            ),
            font=("Segoe UI", 12),
            text_color=self.PALETTE["muted"],
            justify="left",
            wraplength=620,
            anchor="w",
        ).pack(anchor="w")

        # Top Live Metric Strip
        summary = ctk.CTkFrame(header, fg_color="transparent")
        summary.grid(row=0, column=1, sticky="e", padx=20, pady=16)

        cards = [
            ("Total Events", self.metric_total_var, self.PALETTE["accent"]),
            ("Confirmed", self.metric_confirmed_var, self.PALETTE["danger"]),
            ("False Positives", self.metric_false_rate_var, self.PALETTE["success"]),
            ("Pending Queue", self.metric_pending_var, self.PALETTE["warning"]),
        ]

        for title, variable, accent in cards:
            card = ctk.CTkFrame(
                summary,
                fg_color=self.PALETTE["card"],
                corner_radius=12,
                border_width=1,
                border_color=self.PALETTE["border"],
                width=110,
                height=78,
            )
            card.pack(side="left", padx=(0, 8))
            card.pack_propagate(False)

            accent_bar = ctk.CTkFrame(
                card,
                fg_color=accent,
                height=3,
                corner_radius=999,
            )
            accent_bar.pack(fill="x", padx=10, pady=(8, 4))

            ctk.CTkLabel(
                card,
                text=title,
                font=("Segoe UI", 9, "bold"),
                text_color=self.PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=10)

            ctk.CTkLabel(
                card,
                textvariable=variable,
                font=("Bahnschrift SemiBold", 18),
                text_color=self.PALETTE["text"],
                anchor="w",
            ).pack(anchor="w", padx=10, pady=(2, 0))

    # =========================================================================
    # LEFT PANEL: REPORT CRITERIA & CONTROLS
    # =========================================================================
    def _build_filter_panel(self):
        self.filter_panel = ctk.CTkScrollableFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=self.PALETTE["border"],
            width=330,
        )
        self.filter_panel.grid(row=1, column=0, sticky="nsew", padx=(24, 8), pady=(0, 20))
        self.filter_panel.grid_columnconfigure(0, weight=1)

        intro = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        intro.pack(fill="x", padx=16, pady=(16, 12))

        ctk.CTkLabel(
            intro,
            text="Report Parameters",
            font=("Bahnschrift SemiBold", 18),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            intro,
            text="Filter database records to generate customized audit reports.",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 1. Report Scope Selection
        self._section_label(self.filter_panel, "REPORT TYPE")
        self.combo_type = ctk.CTkOptionMenu(
            self.filter_panel,
            variable=self.report_type_var,
            values=self.REPORT_TYPES,
            height=36,
            corner_radius=10,
            fg_color=self.PALETTE["accent"],
            button_color=self.PALETTE["accent_hover"],
            button_hover_color=self.PALETTE["accent_hover"],
            dropdown_fg_color=self.PALETTE["panel_alt"],
            dropdown_hover_color=self.PALETTE["card_soft"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 11),
            command=lambda _choice: self._sync_header_metrics(),
        )
        self.combo_type.pack(fill="x", padx=16, pady=(0, 12))

        # 2. Quick Date Presets
        self._section_label(self.filter_panel, "DATE COVERAGE")
        preset_row = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        preset_row.pack(fill="x", padx=16, pady=(0, 8))

        presets = [
            ("Today", self._set_date_today),
            ("7 Days", self._set_date_7days),
            ("30 Days", self._set_date_30days),
            ("All Time", self._set_date_all),
        ]
        for txt, cmd in presets:
            ctk.CTkButton(
                preset_row,
                text=txt,
                height=26,
                corner_radius=6,
                fg_color=self.PALETTE["card"],
                border_width=1,
                border_color=self.PALETTE["border"],
                hover_color=self.PALETTE["card_soft"],
                text_color=self.PALETTE["text"],
                font=("Segoe UI", 10),
                command=cmd,
            ).pack(side="left", padx=(0, 4), expand=True, fill="x")

        date_frame = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        date_frame.pack(fill="x", padx=16, pady=(0, 12))
        date_frame.grid_columnconfigure((0, 2), weight=1)

        self.date_from = ctk.CTkEntry(
            date_frame,
            textvariable=self.date_from_var,
            placeholder_text="Start (YYYY-MM-DD)",
            height=34,
            corner_radius=8,
            fg_color=self.PALETTE["card"],
            border_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI", 11),
        )
        self.date_from.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            date_frame,
            text="to",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["muted"],
        ).grid(row=0, column=1, padx=6)

        self.date_to = ctk.CTkEntry(
            date_frame,
            textvariable=self.date_to_var,
            placeholder_text="End (YYYY-MM-DD)",
            height=34,
            corner_radius=8,
            fg_color=self.PALETTE["card"],
            border_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI", 11),
        )
        self.date_to.grid(row=0, column=2, sticky="ew")

        # 3. Camera Feed Filter
        self._section_label(self.filter_panel, "CAMERA / CELL SECTOR")
        cams = self._get_available_cameras()
        self.combo_cam = ctk.CTkOptionMenu(
            self.filter_panel,
            variable=self.camera_filter_var,
            values=["All Cameras"] + [f"Camera {c}" for c in cams],
            height=34,
            corner_radius=8,
            fg_color=self.PALETTE["card"],
            button_color=self.PALETTE["card_soft"],
            button_hover_color=self.PALETTE["panel_alt"],
            dropdown_fg_color=self.PALETTE["panel_alt"],
            dropdown_hover_color=self.PALETTE["card_soft"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI", 11),
        )
        self.combo_cam.pack(fill="x", padx=16, pady=(0, 12))

        # 4. Status Filter
        self._section_label(self.filter_panel, "AUDIT VALIDATION STATUS")
        self.combo_status = ctk.CTkOptionMenu(
            self.filter_panel,
            variable=self.status_filter_var,
            values=["All Statuses", "Confirmed Only", "False Alarm Only", "Pending Only", "Needs Review Only"],
            height=34,
            corner_radius=8,
            fg_color=self.PALETTE["card"],
            button_color=self.PALETTE["card_soft"],
            button_hover_color=self.PALETTE["panel_alt"],
            dropdown_fg_color=self.PALETTE["panel_alt"],
            dropdown_hover_color=self.PALETTE["card_soft"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI", 11),
        )
        self.combo_status.pack(fill="x", padx=16, pady=(0, 12))

        # 5. Severity Coverage
        self._section_label(self.filter_panel, "SEVERITY CLASSIFICATION")
        severity_wrap = ctk.CTkFrame(
            self.filter_panel,
            fg_color=self.PALETTE["card"],
            corner_radius=10,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        severity_wrap.pack(fill="x", padx=16, pady=(0, 16))

        for index, (label, variable) in enumerate(self.severity_vars.items()):
            checkbox = ctk.CTkCheckBox(
                severity_wrap,
                text=label,
                variable=variable,
                fg_color=self.PALETTE["accent"],
                hover_color=self.PALETTE["accent_hover"],
                checkmark_color="#ffffff",
                border_color=self.PALETTE["border"],
                text_color=self.PALETTE["text"],
                font=("Segoe UI", 11),
            )
            checkbox.pack(anchor="w", padx=14, pady=(10 if index == 0 else 6, 8 if index == 2 else 0))

        # 6. Action Buttons
        actions = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(4, 16))

        self.btn_generate = ctk.CTkButton(
            actions,
            text="⟳ Generate Report",
            height=38,
            corner_radius=8,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 12),
            command=self.generate_preview,
        )
        self.btn_generate.pack(fill="x", pady=(0, 8))

        self.btn_export = ctk.CTkButton(
            actions,
            text="📄 Export PDF / Print",
            height=38,
            corner_radius=8,
            fg_color=self.PALETTE["success"],
            hover_color=self.PALETTE["success_hover"],
            text_color="#ffffff",
            font=("Segoe UI Semibold", 12),
            command=self.export_pdf,
        )
        self.btn_export.pack(fill="x", pady=(0, 8))

        self.btn_csv = ctk.CTkButton(
            actions,
            text="📊 Export CSV Data",
            height=34,
            corner_radius=8,
            fg_color=self.PALETTE["card"],
            border_width=1,
            border_color=self.PALETTE["border"],
            hover_color=self.PALETTE["card_soft"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            command=self.export_csv,
        )
        self.btn_csv.pack(fill="x", pady=(0, 8))

        self.btn_reset = ctk.CTkButton(
            actions,
            text="Reset Parameters",
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.PALETTE["card_soft"],
            text_color=self.PALETTE["muted"],
            font=("Segoe UI", 11),
            command=self.reset_filters,
        )
        self.btn_reset.pack(fill="x")

    def _section_label(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=text,
            font=("Segoe UI", 9, "bold"),
            text_color=self.PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(6, 4))

    def _set_date_today(self):
        t = datetime.now().strftime("%Y-%m-%d")
        self.date_from_var.set(t)
        self.date_to_var.set(t)
        self.generate_preview()

    def _set_date_7days(self):
        now = datetime.now()
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        self.date_from_var.set(start)
        self.date_to_var.set(end)
        self.generate_preview()

    def _set_date_30days(self):
        now = datetime.now()
        start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        self.date_from_var.set(start)
        self.date_to_var.set(end)
        self.generate_preview()

    def _set_date_all(self):
        self.date_from_var.set("")
        self.date_to_var.set("")
        self.generate_preview()

    def _get_available_cameras(self):
        cams = []
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT camera_id FROM incidents WHERE camera_id IS NOT NULL ORDER BY camera_id")
                cams = [str(r[0]) for r in cur.fetchall()]
                conn.close()
            except Exception:
                pass
        return cams

    # =========================================================================
    # RIGHT PANEL: REPORT PREVIEW DOCUMENT
    # =========================================================================
    def _build_preview_panel(self):
        self.preview_panel = ctk.CTkFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=14,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        self.preview_panel.grid(row=1, column=1, sticky="nsew", padx=(8, 24), pady=(0, 20))
        self.preview_panel.grid_columnconfigure(0, weight=1)
        self.preview_panel.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 10))
        toolbar.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(toolbar, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_wrap,
            text="Institutional Report Dossier",
            font=("Bahnschrift SemiBold", 20),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_wrap,
            textvariable=self.preview_meta_var,
            font=("Segoe UI", 11),
            text_color=self.PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        status_block = ctk.CTkFrame(toolbar, fg_color="transparent")
        status_block.grid(row=0, column=1, sticky="e")

        self.preview_state_chip = ctk.CTkLabel(
            status_block,
            textvariable=self.preview_state_var,
            font=("Segoe UI Bold", 10),
            text_color=self.PALETTE["accent"],
            fg_color=self.PALETTE["card_soft"],
            corner_radius=6,
            padx=12,
            pady=4,
        )
        self.preview_state_chip.pack(anchor="e")

        # White Paper Shell for Document Presentation
        paper_shell = ctk.CTkFrame(
            self.preview_panel,
            fg_color=self.PALETTE["surface"],
            corner_radius=12,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        paper_shell.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        paper_shell.grid_columnconfigure(0, weight=1)
        paper_shell.grid_rowconfigure(0, weight=1)

        paper = ctk.CTkFrame(
            paper_shell,
            fg_color=self.PALETTE["paper"],
            corner_radius=10,
            border_width=1,
            border_color=self.PALETTE["paper_border"],
        )
        paper.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        paper.grid_columnconfigure(0, weight=1)
        paper.grid_rowconfigure(0, weight=1)

        self.preview_text = ctk.CTkTextbox(
            paper,
            fg_color=self.PALETTE["paper"],
            border_width=0,
            text_color=self.PALETTE["paper_text"],
            font=("Consolas", 11),
            scrollbar_button_color=("#cbd5e1", "#26384a"),
            scrollbar_button_hover_color=("#94a3b8", "#4f84bb"),
            activate_scrollbars=True,
            wrap="word",
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.preview_text.configure(state="disabled")

    # =========================================================================
    # DATA EXTRACTION & AGGREGATION
    # =========================================================================
    def _query_report_data(self):
        """Fetches and aggregates live records from incidents.db matching user filters."""
        if not os.path.exists(self.db_path):
            return {"rows": [], "metrics": {}}

        start_date = self.date_from_var.get().strip()
        end_date = self.date_to_var.get().strip()
        cam_filter = self.camera_filter_var.get().strip()
        status_filter = self.status_filter_var.get().strip()

        query = "SELECT * FROM incidents WHERE 1=1"
        params = []

        if start_date:
            query += " AND timestamp_start >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp_start <= ?"
            params.append(f"{end_date} 23:59:59")
        if cam_filter and cam_filter != "All Cameras":
            cam_clean = cam_filter.replace("Camera ", "").strip()
            query += " AND camera_id = ?"
            params.append(cam_clean)

        status_mapping = {
            "Confirmed Only": "CONFIRMED",
            "False Alarm Only": "FALSE ALARM",
            "Pending Only": "PENDING",
            "Needs Review Only": "NEEDS REVIEW",
        }
        if status_filter in status_mapping:
            query += " AND review_status = ?"
            params.append(status_mapping[status_filter])

        query += " ORDER BY timestamp_start DESC"

        rows = []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
        except Exception as e:
            print(f"Error querying report data: {e}")
            return {"rows": [], "metrics": {}}

        # Calculate metrics
        total = len(rows)
        confirmed = sum(1 for r in rows if (r.get("review_status") or "PENDING").upper() == "CONFIRMED")
        false_alarms = sum(1 for r in rows if (r.get("review_status") or "PENDING").upper() == "FALSE ALARM")
        pending = sum(1 for r in rows if (r.get("review_status") or "PENDING").upper() == "PENDING")
        needs_review = sum(1 for r in rows if (r.get("review_status") or "PENDING").upper() == "NEEDS REVIEW")

        false_rate = (false_alarms / total * 100) if total > 0 else 0.0

        # Threats aggregation
        weapon_count = 0
        contraband_count = 0
        violence_count = 0
        behavior_count = 0
        threat_breakdown = {}
        camera_counts = {}
        hour_counts = {h: 0 for h in range(24)}

        for r in rows:
            cam = str(r.get("camera_id", "Unknown"))
            camera_counts[cam] = camera_counts.get(cam, 0) + 1

            ts = r.get("timestamp_start", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    hour_counts[dt.hour] += 1
                except Exception:
                    pass

            raw_type = r.get("event_type", "")
            threats = parse_threat_telemetry(raw_type)
            for t in threats:
                tname = t["name"]
                tcat = t["category"]
                if tcat == "danger":
                    if "weapon" in t["tag"].lower() or "knife" in tname.lower() or "gun" in tname.lower():
                        weapon_count += 1
                    else:
                        violence_count += 1
                elif tcat == "warning":
                    contraband_count += 1
                else:
                    behavior_count += 1

                threat_breakdown[tname] = threat_breakdown.get(tname, 0) + t["count"]

        peak_hour = max(hour_counts, key=hour_counts.get) if total > 0 else 0
        peak_cam = max(camera_counts, key=camera_counts.get) if camera_counts else "N/A"

        metrics = {
            "total": total,
            "confirmed": confirmed,
            "false_alarms": false_alarms,
            "pending": pending,
            "needs_review": needs_review,
            "false_rate": false_rate,
            "weapon_count": weapon_count,
            "contraband_count": contraband_count,
            "violence_count": violence_count,
            "behavior_count": behavior_count,
            "threat_breakdown": threat_breakdown,
            "camera_counts": camera_counts,
            "peak_hour": peak_hour,
            "peak_cam": peak_cam,
        }

        # Update Live Header Metric Variables
        self.metric_total_var.set(str(total))
        self.metric_confirmed_var.set(str(confirmed))
        self.metric_false_rate_var.set(f"{false_rate:.1f}%")
        self.metric_pending_var.set(str(pending))

        return {"rows": rows, "metrics": metrics}

    def _selected_severities(self):
        selected = [label.split(" ")[0] for label, var in self.severity_vars.items() if var.get()]
        return selected or ["High", "Medium", "Low"]

    def _format_date_range(self):
        start = self.date_from_var.get().strip()
        end = self.date_to_var.get().strip()
        if start and end:
            return f"{start} to {end}"
        if start:
            return f"From {start}"
        if end:
            return f"Until {end}"
        return "All Time (Complete Historical Archive)"

    def _sync_header_metrics(self):
        report_type = self.report_type_var.get()
        self.summary_type_var.set(self.REPORT_TYPE_SHORT.get(report_type, report_type))
        self.summary_range_var.set(self._format_date_range())

    def _set_preview_text(self, content):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", content)
        self.preview_text.configure(state="disabled")

    # =========================================================================
    # DOCUMENT BUILDER (INSTITUTIONAL DOSSIER FORMAT)
    # =========================================================================
    def _build_preview_document(self):
        data = self._query_report_data()
        rows = data["rows"]
        m = data["metrics"]

        report_type = self.report_type_var.get()
        date_range = self._format_date_range()
        severities = ", ".join(self._selected_severities())
        generated_at = datetime.now().strftime("%B %d, %Y  %I:%M:%S %p")
        cam_scope = self.camera_filter_var.get()
        status_scope = self.status_filter_var.get()

        sys_name = (self.branding.get("system_name") or "CellWatch AI").upper()
        comp_name = (self.branding.get("company_name") or "Bureau of Jail Management and Penology").upper()
        intro = self.REPORT_INTROS.get(report_type, "Controlled institutional report preview.")

        doc_lines = []
        div = "=" * 80
        subdiv = "-" * 80

        # Header Block
        doc_lines.append(div)
        doc_lines.append(f"  {comp_name}")
        doc_lines.append(f"  {sys_name} - FORENSIC SURVEILLANCE AUDIT SYSTEM")
        doc_lines.append(f"  OFFICIAL CLASSIFICATION: LAW ENFORCEMENT & INSTITUTIONAL RECORD")
        doc_lines.append(div)
        doc_lines.append("")
        doc_lines.append(f"DOCUMENT TITLE   : {report_type.upper()}")
        doc_lines.append(f"GENERATION TIME  : {generated_at}")
        doc_lines.append(f"COVERAGE WINDOW  : {date_range}")
        doc_lines.append(f"CAMERA SCOPE     : {cam_scope}")
        doc_lines.append(f"STATUS SCOPE     : {status_scope}")
        doc_lines.append(f"SEVERITY FILTER  : {severities}")
        doc_lines.append("")

        # Section 1: Executive Summary
        doc_lines.append(div)
        doc_lines.append("I. EXECUTIVE INTELLIGENCE SUMMARY")
        doc_lines.append(div)
        doc_lines.append(intro)
        doc_lines.append("")
        ai_summary = self.generate_ai_summary(m, rows)
        doc_lines.append(ai_summary)
        doc_lines.append("")

        # Section 2: Key Operational Metrics
        doc_lines.append(div)
        doc_lines.append("II. AUDIT REGISTRY SNAPSHOT")
        doc_lines.append(div)
        doc_lines.append(f"  • Total Logged Surveillance Events : {m.get('total', 0)}")
        doc_lines.append(f"  • Verified Confirmed Incidents      : {m.get('confirmed', 0)}")
        doc_lines.append(f"  • Resolved Benign False Positives   : {m.get('false_alarms', 0)} ({m.get('false_rate', 0):.1f}% false alarm rate)")
        doc_lines.append(f"  • Pending Officer Validation Queue  : {m.get('pending', 0)}")
        doc_lines.append(f"  • Flagged for Secondary Review      : {m.get('needs_review', 0)}")
        doc_lines.append(f"  • Peak Activity Concentration Hour : {m.get('peak_hour', 0):02d}:00 hrs")
        doc_lines.append(f"  • Highest Alert Sector / Camera    : Camera {m.get('peak_cam', 'N/A')}")
        doc_lines.append("")

        # Section 3: Classified Threat Breakdown
        doc_lines.append(div)
        doc_lines.append("III. THREAT & CONTRABAND CLASSIFICATION BREAKDOWN")
        doc_lines.append(div)
        doc_lines.append(f"  [WEAPONS / BLADES]   : {m.get('weapon_count', 0)} detections")
        doc_lines.append(f"  [CONTRABAND / PHONES]: {m.get('contraband_count', 0)} detections")
        doc_lines.append(f"  [FIGHTS / VIOLENCE]  : {m.get('violence_count', 0)} detections")
        doc_lines.append(f"  [BEHAVIOR ANOMALIES] : {m.get('behavior_count', 0)} detections")
        doc_lines.append("")

        threat_dict = m.get("threat_breakdown", {})
        if threat_dict:
            doc_lines.append(f"  {'DETECTED THREAT CATEGORY':<36} | {'FRAME DETECTION COUNT':>22}")
            doc_lines.append(f"  {'-'*36}-+-{'-'*22}")
            for tname, tcnt in sorted(threat_dict.items(), key=lambda x: x[1], reverse=True)[:10]:
                doc_lines.append(f"  {tname:<36} | {tcnt:>22} hits")
            doc_lines.append("")

        # Section 4: Camera Sector Breakdown
        cam_dict = m.get("camera_counts", {})
        if cam_dict:
            doc_lines.append(div)
            doc_lines.append("IV. CAMERA SECTOR ACTIVITY MATRIX")
            doc_lines.append(div)
            doc_lines.append(f"  {'CAMERA FEED':<16} | {'SECTOR / LOCATION':<26} | {'TOTAL ALERTS':>14} | {'SHARE (%)':>10}")
            doc_lines.append(f"  {'-'*16}-+-{'-'*26}-+-{'-'*14}-+-{'-'*10}")
            tot = max(1, m.get("total", 1))
            for cid, cnt in sorted(cam_dict.items(), key=lambda x: x[1], reverse=True):
                pct = (cnt / tot) * 100
                doc_lines.append(f"  Cam {cid:<12} | {'Correctional Cell Block':<26} | {cnt:>14} | {pct:>9.1f}%")
            doc_lines.append("")

        # Section 5: Chronological Evidence Audit Registry
        doc_lines.append(div)
        doc_lines.append(f"V. CHRONOLOGICAL EVIDENCE AUDIT REGISTRY (Showing {min(len(rows), 25)} of {len(rows)} Records)")
        doc_lines.append(div)
        doc_lines.append(f"  {'EVENT ID':<22} | {'DATE & TIME':<16} | {'CAM':<5} | {'CLASSIFIED THREAT':<22} | {'STATUS':<12}")
        doc_lines.append(f"  {'-'*22}-+-{'-'*16}-+-{'-'*5}-+-{'-'*22}-+-{'-'*12}")

        if not rows:
            doc_lines.append("  No incident records found matching current query parameters.")
        else:
            for r in rows[:25]:
                eid = str(r.get("event_id", "-"))[:22]
                ts = str(r.get("timestamp_start", "-"))[:16].replace("T", " ")
                cam = str(r.get("camera_id", "-"))[:4]
                etype = summarize_event_type_short(r.get("event_type", ""), max_items=1)[:22]
                status = str(r.get("review_status", "PENDING")).upper()[:12]
                doc_lines.append(f"  {eid:<22} | {ts:<16} | {cam:<5} | {etype:<22} | {status:<12}")

        if len(rows) > 25:
            doc_lines.append(f"\n  [+ {len(rows) - 25} additional historical records omitted from preview; full registry included in PDF/CSV export]")

        doc_lines.append("")
        doc_lines.append(div)
        doc_lines.append("VI. INSTITUTIONAL CHAIN OF CUSTODY SIGN-OFF")
        doc_lines.append(div)
        doc_lines.append("")
        doc_lines.append("  Prepared By: ___________________________        Reviewed By: ___________________________")
        doc_lines.append("               Duty Intelligence Officer                       Shift Supervisor")
        doc_lines.append("")
        doc_lines.append("  Approved By: ___________________________        Date Signed: ___________________________")
        doc_lines.append("               Jail Warden / Superintendent")
        doc_lines.append("")
        doc_lines.append(div)
        doc_lines.append("  END OF OFFICIAL REPORT - GENERATED BY CELLWATCH AI SURVEILLANCE PLATFORM")
        doc_lines.append(div)

        return "\n".join(doc_lines)

    def generate_ai_summary(self, metrics=None, rows=None):
        """Generates dynamic institutional executive intelligence summary from real metrics."""
        if metrics is None:
            data = self._query_report_data()
            metrics = data["metrics"]
            rows = data["rows"]

        total = metrics.get("total", 0)
        if total == 0:
            return (
                "AI INTELLIGENCE EVALUATION:\n"
                "• Surveillance monitoring indicates zero critical incidents recorded during this operational window.\n"
                "• Perimeter and internal camera feeds report normal baseline behavior with no contraband detected."
            )

        confirmed = metrics.get("confirmed", 0)
        false_alarms = metrics.get("false_alarms", 0)
        weapons = metrics.get("weapon_count", 0)
        contraband = metrics.get("contraband_count", 0)
        violence = metrics.get("violence_count", 0)
        peak_cam = metrics.get("peak_cam", "N/A")
        peak_hour = metrics.get("peak_hour", 0)
        conf_rate = (confirmed / total * 100) if total > 0 else 0

        summary_pts = [
            f"AI INTELLIGENCE EVALUATION & TACTICAL SUMMARY:",
            f"• Operational Activity: During the selected period, CellWatch AI logged {total} total surveillance events. Duty officers have validated and confirmed {confirmed} incidents ({conf_rate:.1f}% confirmation rate), while {false_alarms} were cleared as false alarms.",
        ]

        if weapons > 0:
            summary_pts.append(f"• CRITICAL THREAT: {weapons} sharp weapon/blade detections localized. Immediate tactical search of associated sector recommended.")
        if contraband > 0:
            summary_pts.append(f"• CONTRABAND NOTICE: {contraband} contraband events (cellphones/electronics) recorded. Contraband screening protocols advised.")
        if violence > 0:
            summary_pts.append(f"• PHYSICAL ALTERCATION ALERT: {violence} aggressive behavior/fight anomalies detected by MoveNet pose engine.")

        summary_pts.append(f"• Risk Distribution: Sector Camera {peak_cam} experienced the highest incident concentration. Peak activity clustered around {peak_hour:02d}:00 hrs.")
        summary_pts.append("• Actionable Guidance: Prioritize officer rounds in high-density sectors; ensure remaining unreviewed queue events are triaged.")

        return "\n".join(summary_pts)

    def request_ai_polish(self):
        """Async cloud polish of current preview. Never blocks UI; silent fallback."""
        try:
            from monitor_app.cloud_verifier import get_cloud_verifier
            draft = self.preview_text.get("1.0", "end-1c") if hasattr(self, "preview_text") else ""
            if not draft:
                return False

            def _done(out):
                polished = (out or {}).get("polished", "")
                if polished and hasattr(self, "winfo_exists") and self.winfo_exists():
                    try:
                        self.after(0, lambda: self._set_preview_text(draft + "\n\nAI POLISH:\n" + polished))
                    except Exception:
                        pass

            return get_cloud_verifier().summarize_text_async(draft, callback=_done)
        except Exception:
            return False

    def reset_filters(self):
        self.report_type_var.set(self.REPORT_TYPES[0])
        self.date_from_var.set("")
        self.date_to_var.set("")
        self.camera_filter_var.set("All Cameras")
        self.status_filter_var.set("All Statuses")
        for var in self.severity_vars.values():
            var.set(True)
        self.preview_state_var.set("READY")
        self._sync_header_metrics()
        self.generate_preview()

    def generate_preview(self):
        self._sync_header_metrics()
        self.preview_state_var.set("READY")
        self.preview_meta_var.set(
            f"Generated {datetime.now().strftime('%H:%M:%S')} • {self.REPORT_TYPE_SHORT.get(self.report_type_var.get(), 'Report')}"
        )
        self._set_preview_text(self._build_preview_document())

    # =========================================================================
    # EXPORT ENGINES: PRINTABLE HTML / PDF & CSV DATA
    # =========================================================================
    def export_pdf(self):
        """
        Builds a high-fidelity institutional HTML report with CSS print layout and
        launches it in the default browser with an automatic print dialog.
        """
        data = self._query_report_data()
        rows = data["rows"]
        m = data["metrics"]

        os.makedirs("reports", exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_slug = re.sub(r'\W+', '_', self.report_type_var.get()).lower()
        html_file = os.path.abspath(os.path.join("reports", f"report_{report_slug}_{now_str}.html"))

        comp_name = self.branding.get("company_name") or "Bureau of Jail Management and Penology"
        sys_name = self.branding.get("system_name") or "CellWatch AI"
        report_title = self.report_type_var.get()
        date_window = self._format_date_range()
        gen_time = datetime.now().strftime("%B %d, %Y - %I:%M %p")

        # Build Table Rows HTML
        table_rows_html = ""
        for r in rows:
            eid = r.get("event_id", "-")
            ts = str(r.get("timestamp_start", "-")).replace("T", " ")[:19]
            cam = f"Cam {r.get('camera_id', '-')}"
            etype = summarize_event_type_short(r.get("event_type", ""), max_items=2)
            status = (r.get("review_status") or "PENDING").upper()
            status_cls = "badge-danger" if status == "CONFIRMED" else ("badge-success" if status == "FALSE ALARM" else "badge-warning")
            officer = r.get("reviewed_by") or "Unassigned"
            comments = r.get("comments") or "-"

            table_rows_html += f"""
            <tr>
                <td style="font-family:monospace; font-weight:bold;">{eid}</td>
                <td>{ts}</td>
                <td>{cam}</td>
                <td>{etype}</td>
                <td><span class="badge {status_cls}">{status}</span></td>
                <td>{officer}</td>
                <td style="font-size:11px; color:#555;">{comments}</td>
            </tr>
            """

        ai_summary_html = self.generate_ai_summary(m, rows).replace("\n", "<br>")

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_title} - {sys_name}</title>
    <style>
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            color: #1e293b;
            background: #f8fafc;
            margin: 0;
            padding: 24px;
        }}
        .report-page {{
            max-width: 960px;
            margin: 0 auto;
            background: #ffffff;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }}
        .header {{
            border-bottom: 2px solid #1d4ed8;
            padding-bottom: 20px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header-title {{
            font-size: 24px;
            font-weight: 700;
            color: #0f172a;
            margin: 0 0 6px 0;
        }}
        .header-sub {{
            font-size: 13px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin: 0;
        }}
        .meta-strip {{
            background: #f1f5f9;
            border-radius: 6px;
            padding: 12px 18px;
            margin-bottom: 24px;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            font-size: 12px;
        }}
        .meta-label {{
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 10px;
        }}
        .meta-value {{
            color: #0f172a;
            font-weight: 700;
            margin-top: 2px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 28px;
        }}
        .metric-card {{
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px;
            background: #ffffff;
        }}
        .metric-card-title {{
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
        }}
        .metric-card-val {{
            font-size: 24px;
            font-weight: 700;
            color: #0f172a;
            margin-top: 4px;
        }}
        .section-title {{
            font-size: 15px;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 8px;
            margin: 28px 0 14px 0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .summary-box {{
            background: #eff6ff;
            border-left: 4px solid #1d4ed8;
            padding: 14px 18px;
            border-radius: 4px;
            font-size: 13px;
            line-height: 1.6;
            color: #1e3a8a;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-top: 10px;
        }}
        th {{
            background: #f8fafc;
            color: #475569;
            text-align: left;
            padding: 10px;
            border-bottom: 2px solid #e2e8f0;
            font-weight: 600;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}
        .badge {{
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            display: inline-block;
        }}
        .badge-danger {{ background: #fee2e2; color: #dc2626; }}
        .badge-success {{ background: #dcfce7; color: #16a34a; }}
        .badge-warning {{ background: #fef3c7; color: #d97706; }}
        .signature-block {{
            margin-top: 48px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 24px;
            font-size: 12px;
        }}
        .sign-line {{
            border-top: 1px solid #0f172a;
            padding-top: 6px;
            text-align: center;
            font-weight: 600;
        }}
        .sign-title {{
            font-size: 11px;
            color: #64748b;
            text-align: center;
        }}
        @media print {{
            body {{ background: #ffffff; padding: 0; }}
            .report-page {{ box-shadow: none; padding: 0; }}
            .no-print {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="report-page">
        <div class="header">
            <div>
                <p class="header-sub">{comp_name}</p>
                <h1 class="header-title">{report_title}</h1>
                <p style="font-size:12px; color:#64748b; margin:0;">Platform: {sys_name} • Operational Decision Audit</p>
            </div>
            <div style="text-align:right;">
                <span style="display:inline-block; padding:4px 10px; background:#1e293b; color:#ffffff; font-size:10px; font-weight:bold; border-radius:4px;">OFFICIAL RECORD</span>
                <p style="font-size:11px; color:#64748b; margin:6px 0 0 0;">Generated: {gen_time}</p>
            </div>
        </div>

        <div class="meta-strip">
            <div>
                <div class="meta-label">Coverage Window</div>
                <div class="meta-value">{date_window}</div>
            </div>
            <div>
                <div class="meta-label">Camera Sector</div>
                <div class="meta-value">{self.camera_filter_var.get()}</div>
            </div>
            <div>
                <div class="meta-label">Validation Scope</div>
                <div class="meta-value">{self.status_filter_var.get()}</div>
            </div>
            <div>
                <div class="meta-label">Security Clearance</div>
                <div class="meta-value">Restricted Institutional</div>
            </div>
        </div>

        <div class="metrics-grid">
            <div class="metric-card" style="border-top:3px solid #1d4ed8;">
                <div class="metric-card-title">Total Logged Alerts</div>
                <div class="metric-card-val">{m.get('total', 0)}</div>
            </div>
            <div class="metric-card" style="border-top:3px solid #dc2626;">
                <div class="metric-card-title">Confirmed Incidents</div>
                <div class="metric-card-val" style="color:#dc2626;">{m.get('confirmed', 0)}</div>
            </div>
            <div class="metric-card" style="border-top:3px solid #16a34a;">
                <div class="metric-card-title">False Alarm Rate</div>
                <div class="metric-card-val" style="color:#16a34a;">{m.get('false_rate', 0):.1f}%</div>
            </div>
            <div class="metric-card" style="border-top:3px solid #d97706;">
                <div class="metric-card-title">Pending Officer Triage</div>
                <div class="metric-card-val" style="color:#d97706;">{m.get('pending', 0)}</div>
            </div>
        </div>

        <div class="section-title">I. Executive Intelligence & Behavioral Synthesis</div>
        <div class="summary-box">
            {ai_summary_html}
        </div>

        <div class="section-title">II. Forensic Incident Registry ({len(rows)} Records)</div>
        <table>
            <thead>
                <tr>
                    <th>Event ID</th>
                    <th>Date & Time</th>
                    <th>Camera</th>
                    <th>Classified Threat</th>
                    <th>Audit Status</th>
                    <th>Reviewing Officer</th>
                    <th>Remarks</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html}
            </tbody>
        </table>

        <div class="section-title">III. Institutional Sign-Off & Chain of Custody</div>
        <div class="signature-block">
            <div>
                <div class="sign-line">Duty Intelligence Officer</div>
                <div class="sign-title">Report Preparer</div>
            </div>
            <div>
                <div class="sign-line">Shift Security Supervisor</div>
                <div class="sign-title">Audit Reviewer</div>
            </div>
            <div>
                <div class="sign-line">Jail Warden / Superintendent</div>
                <div class="sign-title">Executive Approval</div>
            </div>
        </div>
    </div>
    <script>
        window.onload = function() {{
            setTimeout(function() {{ window.print(); }}, 400);
        }};
    </script>
</body>
</html>"""

        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            webbrowser.open(f"file:///{html_file}")
            messagebox.showinfo(
                "Report Exported",
                f"Printable report created successfully:\n\n{html_file}\n\nOpened in your web browser with print-to-PDF ready.",
            )
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to generate printable report: {e}")

    def export_csv(self):
        """Exports matching incident records to a CSV spreadsheet."""
        data = self._query_report_data()
        rows = data["rows"]
        if not rows:
            messagebox.showinfo("Export CSV", "No records found matching current query parameters.")
            return

        os.makedirs("reports", exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_slug = re.sub(r'\W+', '_', self.report_type_var.get()).lower()
        csv_file = os.path.abspath(os.path.join("reports", f"incidents_{report_slug}_{now_str}.csv"))

        fieldnames = [
            "event_id",
            "camera_id",
            "timestamp_start",
            "timestamp_end",
            "event_type",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "comments",
            "retention_days",
            "video_path",
        ]

        try:
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)

            resp = messagebox.askyesno(
                "CSV Export Complete",
                f"Exported {len(rows)} incidents to:\n\n{csv_file}\n\nWould you like to open the reports folder now?",
            )
            if resp:
                if hasattr(os, "startfile"):
                    os.startfile(os.path.dirname(csv_file))
                else:
                    webbrowser.open(f"file:///{os.path.dirname(csv_file)}")
        except Exception as e:
            messagebox.showerror("Export CSV Error", f"Failed to export CSV: {e}")
