from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from monitor_app import profile_store


class ReportsScreen(ttk.Frame):
    PALETTE = {
        "page": "#10161d",
        "panel": "#171f29",
        "panel_alt": "#1c2531",
        "card": "#1b2430",
        "card_soft": "#202b38",
        "surface": "#0d131a",
        "paper": "#f4f7fb",
        "paper_border": "#d5dce6",
        "paper_text": "#112033",
        "border": "#26384a",
        "text": "#f3f7fb",
        "muted": "#8da1b4",
        "subtle": "#617487",
        "accent": "#4f84bb",
        "accent_hover": "#426f9b",
        "success": "#42c08d",
        "success_hover": "#32956b",
        "warning": "#d7a75a",
    }

    REPORT_TYPES = [
        "Daily Incident Summary",
        "Weekly Behavior Analytics",
        "Alert Frequency Report",
        "System Health Log",
    ]

    REPORT_TYPE_SHORT = {
        "Daily Incident Summary": "Daily Summary",
        "Weekly Behavior Analytics": "Behavior Weekly",
        "Alert Frequency Report": "Alert Frequency",
        "System Health Log": "Health Log",
    }

    REPORT_INTROS = {
        "Daily Incident Summary": (
            "Operational digest of recorded incidents, review activity, and unresolved "
            "items for the selected reporting window."
        ),
        "Weekly Behavior Analytics": (
            "Behavior-focused overview intended to surface suspicious trends, higher-risk "
            "periods, and recurring operational patterns."
        ),
        "Alert Frequency Report": (
            "Frequency-oriented summary of alert generation volume, severity distribution, "
            "and operator handling cadence."
        ),
        "System Health Log": (
            "System-facing status preview covering platform health, evidence readiness, "
            "and monitoring continuity notes."
        ),
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self.branding = profile_store.get_branding()

        self.report_type_var = tk.StringVar(value=self.REPORT_TYPES[0])
        self.date_from_var = tk.StringVar()
        self.date_to_var = tk.StringVar()

        self.severity_vars = {
            "High (Aggressive)": tk.BooleanVar(value=True),
            "Medium (Suspicious)": tk.BooleanVar(value=True),
            "Low (General)": tk.BooleanVar(value=True),
        }

        self.summary_type_var = tk.StringVar(value=self.REPORT_TYPE_SHORT[self.REPORT_TYPES[0]])
        self.summary_range_var = tk.StringVar(value="Open Range")
        self.summary_output_var = tk.StringVar(value="PDF Export")
        self.preview_state_var = tk.StringVar(value="DRAFT")
        self.preview_meta_var = tk.StringVar(value="Preview has not been generated yet.")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.page = ctk.CTkFrame(self, fg_color=self.PALETTE["page"], corner_radius=0)
        self.page.grid(row=0, column=0, sticky="nsew")
        self.page.grid_columnconfigure(0, weight=4, uniform="reports")
        self.page.grid_columnconfigure(1, weight=9, uniform="reports")
        self.page.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_filter_panel()
        self._build_preview_panel()
        self.generate_preview()

    def _build_header(self):
        header = ctk.CTkFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=26,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=28, pady=(24, 18))
        header.grid_columnconfigure(0, weight=1)

        copy_block = ctk.CTkFrame(header, fg_color="transparent")
        copy_block.grid(row=0, column=0, sticky="w", padx=26, pady=22)

        ctk.CTkLabel(
            copy_block,
            text="REPORTING WORKSPACE",
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            copy_block,
            text="Generate Reports",
            font=("Bahnschrift SemiBold", 32),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w", pady=(8, 8))

        ctk.CTkLabel(
            copy_block,
            text=(
                "Build presentation-ready incident summaries and controlled reporting "
                "drafts from a cleaner institutional workspace."
            ),
            font=("Segoe UI", 14),
            text_color=self.PALETTE["muted"],
            justify="left",
            wraplength=690,
            anchor="w",
        ).pack(anchor="w")

        summary = ctk.CTkFrame(header, fg_color="transparent")
        summary.grid(row=0, column=1, sticky="e", padx=26, pady=22)

        cards = [
            ("Report Type", self.summary_type_var, self.PALETTE["accent"]),
            ("Date Window", self.summary_range_var, self.PALETTE["warning"]),
            ("Output", self.summary_output_var, self.PALETTE["success"]),
        ]

        for title, variable, accent in cards:
            card = ctk.CTkFrame(
                summary,
                fg_color=self.PALETTE["card"],
                corner_radius=18,
                border_width=1,
                border_color=self.PALETTE["border"],
                width=144,
                height=90,
            )
            card.pack(side="left", padx=(0, 10))
            card.pack_propagate(False)

            accent_bar = ctk.CTkFrame(
                card,
                fg_color=accent,
                height=4,
                corner_radius=999,
            )
            accent_bar.pack(fill="x", padx=14, pady=(12, 10))

            ctk.CTkLabel(
                card,
                text=title,
                font=("Segoe UI", 11),
                text_color=self.PALETTE["muted"],
                anchor="w",
            ).pack(anchor="w", padx=14)

            ctk.CTkLabel(
                card,
                textvariable=variable,
                font=("Segoe UI Semibold", 13),
                text_color=self.PALETTE["text"],
                anchor="w",
                justify="left",
                wraplength=110,
            ).pack(anchor="w", padx=14, pady=(6, 0))

    def _build_filter_panel(self):
        self.filter_panel = ctk.CTkFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=self.PALETTE["border"],
            width=320,
        )
        self.filter_panel.grid(row=1, column=0, sticky="nsew", padx=(28, 12), pady=(0, 28))
        self.filter_panel.grid_columnconfigure(0, weight=1)
        self.filter_panel.grid_rowconfigure(5, weight=1)

        intro = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        intro.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 18))

        ctk.CTkLabel(
            intro,
            text="Report Criteria",
            font=("Bahnschrift SemiBold", 24),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            intro,
            text="Choose report scope, date coverage, and severity filters before generating a draft.",
            font=("Segoe UI", 12),
            text_color=self.PALETTE["muted"],
            justify="left",
            wraplength=250,
            anchor="w",
        ).pack(anchor="w", pady=(8, 0))

        self._section_label(self.filter_panel, "Report Type", row=1)

        self.combo_type = ctk.CTkOptionMenu(
            self.filter_panel,
            variable=self.report_type_var,
            values=self.REPORT_TYPES,
            height=42,
            corner_radius=12,
            fg_color=self.PALETTE["accent"],
            button_color=self.PALETTE["accent_hover"],
            button_hover_color=self.PALETTE["accent_hover"],
            dropdown_fg_color=self.PALETTE["panel_alt"],
            dropdown_hover_color=self.PALETTE["card_soft"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=lambda _choice: self._sync_header_metrics(),
        )
        self.combo_type.grid(row=1, column=0, sticky="ew", padx=22, pady=(26, 18))

        self._section_label(self.filter_panel, "Date Window", row=2)

        date_frame = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        date_frame.grid(row=2, column=0, sticky="ew", padx=22, pady=(26, 18))
        date_frame.grid_columnconfigure((0, 2), weight=1)

        self.date_from = ctk.CTkEntry(
            date_frame,
            textvariable=self.date_from_var,
            placeholder_text="YYYY-MM-DD",
            height=40,
            corner_radius=12,
            fg_color=self.PALETTE["card"],
            border_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
        )
        self.date_from.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            date_frame,
            text="to",
            font=("Segoe UI", 12),
            text_color=self.PALETTE["muted"],
        ).grid(row=0, column=1, padx=10)

        self.date_to = ctk.CTkEntry(
            date_frame,
            textvariable=self.date_to_var,
            placeholder_text="YYYY-MM-DD",
            height=40,
            corner_radius=12,
            fg_color=self.PALETTE["card"],
            border_color=self.PALETTE["border"],
            text_color=self.PALETTE["text"],
        )
        self.date_to.grid(row=0, column=2, sticky="ew")

        self._section_label(self.filter_panel, "Severity Coverage", row=3)

        severity_wrap = ctk.CTkFrame(
            self.filter_panel,
            fg_color=self.PALETTE["card"],
            corner_radius=18,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        severity_wrap.grid(row=3, column=0, sticky="ew", padx=22, pady=(26, 18))
        severity_wrap.grid_columnconfigure(0, weight=1)

        for index, (label, variable) in enumerate(self.severity_vars.items()):
            checkbox = ctk.CTkCheckBox(
                severity_wrap,
                text=label,
                variable=variable,
                fg_color=self.PALETTE["accent"],
                hover_color=self.PALETTE["accent_hover"],
                checkmark_color=self.PALETTE["text"],
                border_color=self.PALETTE["border"],
                text_color=self.PALETTE["text"],
                font=("Segoe UI", 12),
            )
            checkbox.grid(row=index, column=0, sticky="w", padx=16, pady=(14 if index == 0 else 8, 0))

        ctk.CTkLabel(
            severity_wrap,
            text="Leave all selected to build a full-range operational summary.",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["subtle"],
            anchor="w",
            justify="left",
            wraplength=240,
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(12, 14))

        note = ctk.CTkFrame(
            self.filter_panel,
            fg_color=self.PALETTE["card_soft"],
            corner_radius=16,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        note.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 12))

        ctk.CTkLabel(
            note,
            text="Preview Mode",
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            note,
            text="This screen generates a presentation-oriented draft. PDF export is still demo-only.",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["muted"],
            justify="left",
            wraplength=245,
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(0, 12))

        actions = ctk.CTkFrame(self.filter_panel, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=22, pady=(10, 22))
        actions.grid_columnconfigure(0, weight=1)

        self.btn_generate = ctk.CTkButton(
            actions,
            text="Generate Preview",
            height=44,
            corner_radius=12,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 13),
            command=self.generate_preview,
        )
        self.btn_generate.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.btn_export = ctk.CTkButton(
            actions,
            text="Export PDF",
            height=44,
            corner_radius=12,
            fg_color=self.PALETTE["success"],
            hover_color=self.PALETTE["success_hover"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 13),
            command=self.export_pdf,
        )
        self.btn_export.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.btn_reset = ctk.CTkButton(
            actions,
            text="Reset Filters",
            height=40,
            corner_radius=12,
            fg_color=self.PALETTE["card_soft"],
            hover_color=self.PALETTE["panel_alt"],
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.reset_filters,
        )
        self.btn_reset.grid(row=2, column=0, sticky="ew")

    def _build_preview_panel(self):
        self.preview_panel = ctk.CTkFrame(
            self.page,
            fg_color=self.PALETTE["panel"],
            corner_radius=24,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        self.preview_panel.grid(row=1, column=1, sticky="nsew", padx=(12, 28), pady=(0, 28))
        self.preview_panel.grid_columnconfigure(0, weight=1)
        self.preview_panel.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 16))
        toolbar.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(toolbar, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_wrap,
            text="Report Preview",
            font=("Bahnschrift SemiBold", 28),
            text_color=self.PALETTE["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_wrap,
            textvariable=self.preview_meta_var,
            font=("Segoe UI", 12),
            text_color=self.PALETTE["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        status_block = ctk.CTkFrame(toolbar, fg_color="transparent")
        status_block.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            status_block,
            text="Preview State",
            font=("Segoe UI", 11),
            text_color=self.PALETTE["subtle"],
            anchor="e",
        ).pack(anchor="e")

        self.preview_state_chip = ctk.CTkLabel(
            status_block,
            textvariable=self.preview_state_var,
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["accent"],
            fg_color=self.PALETTE["card_soft"],
            corner_radius=999,
            padx=16,
            pady=8,
        )
        self.preview_state_chip.pack(anchor="e", pady=(8, 0))

        paper_shell = ctk.CTkFrame(
            self.preview_panel,
            fg_color=self.PALETTE["surface"],
            corner_radius=22,
            border_width=1,
            border_color=self.PALETTE["border"],
        )
        paper_shell.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        paper_shell.grid_columnconfigure(0, weight=1)
        paper_shell.grid_rowconfigure(0, weight=1)

        paper = ctk.CTkFrame(
            paper_shell,
            fg_color=self.PALETTE["paper"],
            corner_radius=20,
            border_width=1,
            border_color=self.PALETTE["paper_border"],
        )
        paper.grid(row=0, column=0, sticky="nsew", padx=22, pady=22)
        paper.grid_columnconfigure(0, weight=1)
        paper.grid_rowconfigure(0, weight=1)

        self.preview_text = ctk.CTkTextbox(
            paper,
            fg_color=self.PALETTE["paper"],
            border_width=0,
            text_color=self.PALETTE["paper_text"],
            font=("Consolas", 12),
            scrollbar_button_color="#b9c4d1",
            scrollbar_button_hover_color="#98a9bc",
            activate_scrollbars=True,
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.preview_text.configure(state="disabled")

    def _section_label(self, parent, text, row):
        ctk.CTkLabel(
            parent,
            text=text,
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["accent"],
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=22)

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
        return "Open Range"

    def _sync_header_metrics(self):
        report_type = self.report_type_var.get()
        self.summary_type_var.set(self.REPORT_TYPE_SHORT.get(report_type, report_type))
        self.summary_range_var.set(self._format_date_range())

    def _set_preview_text(self, content):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", content)
        self.preview_text.configure(state="disabled")

    def _build_preview_document(self):
        report_type = self.report_type_var.get()
        date_range = self._format_date_range()
        severities = ", ".join(self._selected_severities())
        generated_at = datetime.now().strftime("%B %d, %Y  %I:%M %p")

        intro = self.REPORT_INTROS.get(report_type, "Controlled report preview.")

        return (
            f"{self.branding['system_name'].upper()}\n"
            f"{self.branding['company_name']}\n"
            f"{report_type}\n"
            "\n"
            f"Prepared: {generated_at}\n"
            f"Coverage: {date_range}\n"
            f"Severity Filter: {severities}\n"
            "Document Status: Preview Draft\n"
            "\n"
            "EXECUTIVE SUMMARY\n"
            f"{intro}\n"
            "\n"
            "REPORT SNAPSHOT\n"
            "- Confirmed incidents: --\n"
            "- False alarms: --\n"
            "- Pending validations: --\n"
            "- Evidence files reviewed: --\n"
            "\n"
            "OPERATIONAL NOTES\n"
            "- This preview is currently presentation-oriented and not yet bound to live report queries.\n"
            "- Replace placeholders with aggregated database metrics once the reporting pipeline is connected.\n"
            "- Use this layout as the baseline for capstone screenshots, printouts, and demo walkthroughs.\n"
            "\n"
            "RECOMMENDED FOLLOW-UP\n"
            "- Validate incident counts against the incident review log.\n"
            "- Confirm severity filters before exporting final documentation.\n"
            "- Review unresolved items and update operator decisions before presenting.\n"
        )

    def reset_filters(self):
        self.report_type_var.set(self.REPORT_TYPES[0])
        self.date_from_var.set("")
        self.date_to_var.set("")
        for var in self.severity_vars.values():
            var.set(True)
        self.preview_state_var.set("RESET")
        self.preview_meta_var.set("Filters reset. Generate a new preview draft.")
        self._sync_header_metrics()
        self._set_preview_text(
            f"{self.branding['system_name'].upper()}\n\n"
            "Filters were reset.\n"
            "Generate a new preview to rebuild the report draft."
        )

    def generate_preview(self):
        self._sync_header_metrics()
        self.preview_state_var.set("READY")
        self.preview_meta_var.set(
            f"Updated {datetime.now().strftime('%H:%M:%S')} for {self.REPORT_TYPE_SHORT.get(self.report_type_var.get(), 'Report')}"
        )
        self._set_preview_text(self._build_preview_document())

    def export_pdf(self):
        messagebox.showinfo(
            "Export PDF",
            "PDF export is still a demo action in this build. The redesigned preview is ready for presentation.",
        )
