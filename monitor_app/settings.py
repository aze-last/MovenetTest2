import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image

from monitor_app import profile_store


PALETTE = {
    "page": "#10161d",
    "panel": "#171f29",
    "panel_alt": "#1c2531",
    "card": "#1b2430",
    "card_soft": "#202b38",
    "border": "#26384a",
    "text": "#f3f7fb",
    "muted": "#8da1b4",
    "subtle": "#617487",
    "accent": "#4f84bb",
    "accent_hover": "#426f9b",
    "success": "#42c08d",
    "success_hover": "#32956b",
    "warning": "#d7a75a",
    "danger": "#d86161",
}


class CTkTooltip:
    def __init__(self, widget, text):
        # Bind to underlying tkinter widget if it's a CustomTkinter widget
        self.widget = getattr(widget, "_label", widget)
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)
        self.widget.bind("<Button-1>", self.hide_tip)
        self.widget.bind("<Destroy>", self.hide_tip, add="+")

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        frame = tk.Frame(
            tw,
            background="#202b38",
            highlightbackground="#26384a",
            highlightthickness=1
        )
        frame.pack()
        
        label = tk.Label(
            frame,
            text=self.text,
            justify="left",
            background="#202b38",
            foreground="#f3f7fb",
            font=("Segoe UI", 10),
            wraplength=280,
            padx=12,
            pady=8
        )
        label.pack()

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            try:
                tw.destroy()
            except Exception:
                pass


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, parent, current_user=None, on_profile_updated=None, mode="profile"):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)

        profile_store.ensure_app_state()
        self.current_user = current_user or {}
        self.on_profile_updated = on_profile_updated
        self.is_admin = self.current_user.get("role") == "ADMIN"
        self.mode = mode
        self.show_identity = mode == "profile"
        self.show_monitoring = mode == "monitoring"

        if mode not in {"profile", "monitoring"}:
            raise ValueError("Settings mode must be 'profile' or 'monitoring'.")

        self.selected_user_id = None
        self.selected_logo_source = None
        self.selected_photo_source = None
        self.logo_preview_image = None
        self.photo_preview_image = None
        self.admin_only_widgets = []

        self.company_name_var = tk.StringVar()
        self.system_name_var = tk.StringVar()
        self.branding_status_var = tk.StringVar(value="Ready")
        self.account_count_var = tk.StringVar(value="0 accounts")
        self.access_level_var = tk.StringVar(value="Admin Access" if self.is_admin else "Read Only")
        self.camera_summary_var = tk.StringVar(value="4 camera inputs")
        self.monitoring_state_var = tk.StringVar(value="Local Only")
        self.account_status_var = tk.StringVar(value="Create a new account or select one from the directory.")
        self.account_photo_caption_var = tk.StringVar(value="No profile photo selected")
        self.account_action_var = tk.StringVar(value="Create Account")
        self.account_full_name_var = tk.StringVar()
        self.account_username_var = tk.StringVar()
        self.account_role_var = tk.StringVar(value="OPERATOR")
        self.account_digital_id_var = tk.StringVar(value="Generated on create")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.main_view = ctk.CTkScrollableFrame(
            self,
            fg_color=PALETTE["page"],
            corner_radius=0,
            scrollbar_button_color=PALETTE["card_soft"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        self.main_view.grid(row=0, column=0, sticky="nsew")
        self.main_view.grid_columnconfigure(0, weight=1)

        self._configure_tree_style()
        self.create_widgets()
        if self.show_identity:
            self.load_profile()
            self.load_users()
            self.reset_account_form()
        self._apply_access_rules()

    def create_widgets(self):
        self._build_header()
        row_index = 1
        if self.show_identity:
            self._build_identity_section(row_index)
            row_index += 1
        if self.show_monitoring:
            self._build_monitoring_section(row_index)

    def _build_header(self):
        if self.show_identity:
            eyebrow = "PROFILE IDENTITY CENTER"
            title = "Profile Settings"
            description = (
                "Manage company branding, operator identities, and local access control "
                "from a dedicated administrative workspace."
            )
            summary_cards = (
                ("Access", self.access_level_var, PALETTE["accent"]),
                ("Accounts", self.account_count_var, PALETTE["warning"]),
                ("Profile Save", self.branding_status_var, PALETTE["success"]),
            )
        else:
            eyebrow = "MONITORING CONFIGURATION"
            title = "Settings"
            description = (
                "Configure camera endpoints and local AI threshold tuning while keeping "
                "identity and account administration in the separate profile workspace."
            )
            summary_cards = (
                ("Access", self.access_level_var, PALETTE["accent"]),
                ("Inputs", self.camera_summary_var, PALETTE["warning"]),
                ("Persistence", self.monitoring_state_var, PALETTE["success"]),
            )

        header = ctk.CTkFrame(
            self.main_view,
            fg_color=PALETTE["panel"],
            corner_radius=26,
            border_width=1,
            border_color=PALETTE["border"],
        )
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 18))
        header.grid_columnconfigure(0, weight=1)

        copy_block = ctk.CTkFrame(header, fg_color="transparent")
        copy_block.grid(row=0, column=0, sticky="w", padx=28, pady=24)

        ctk.CTkLabel(
            copy_block,
            text=eyebrow,
            font=("Segoe UI Semibold", 11),
            text_color=PALETTE["accent"],
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            copy_block,
            text=title,
            font=("Bahnschrift SemiBold", 34),
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(anchor="w", pady=(8, 8))
        ctk.CTkLabel(
            copy_block,
            text=description,
            font=("Segoe UI", 14),
            text_color=PALETTE["muted"],
            justify="left",
            wraplength=690,
            anchor="w",
        ).pack(anchor="w")

        summary = ctk.CTkFrame(header, fg_color="transparent")
        summary.grid(row=0, column=1, sticky="e", padx=28, pady=24)

        for title, variable, accent in summary_cards:
            card = ctk.CTkFrame(
                summary,
                fg_color=PALETTE["card"],
                corner_radius=18,
                border_width=1,
                border_color=PALETTE["border"],
                width=150,
                height=92,
            )
            card.pack(side="left", padx=(0, 10))
            card.pack_propagate(False)
            ctk.CTkFrame(card, fg_color=accent, height=4, corner_radius=999).pack(fill="x", padx=14, pady=(12, 10))
            ctk.CTkLabel(card, text=title, font=("Segoe UI", 11), text_color=PALETTE["muted"], anchor="w").pack(anchor="w", padx=14)
            ctk.CTkLabel(
                card,
                textvariable=variable,
                font=("Segoe UI Semibold", 13),
                text_color=PALETTE["text"],
                anchor="w",
                justify="left",
                wraplength=118,
            ).pack(anchor="w", padx=14, pady=(6, 0))

    def _build_identity_section(self, row_index):
        content = ctk.CTkFrame(self.main_view, fg_color="transparent")
        content.grid(row=row_index, column=0, sticky="nsew", padx=28)
        content.grid_columnconfigure((0, 1), weight=1)

        self._build_system_profile_card(content)
        self._build_account_editor_card(content)
        self._build_account_directory_card(content)

    def _build_system_profile_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=PALETTE["panel"], corner_radius=24, border_width=1, border_color=PALETTE["border"])
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 14))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="System Profile", font=("Bahnschrift SemiBold", 24), text_color=PALETTE["text"], anchor="w").grid(row=0, column=0, sticky="w", padx=22, pady=(22, 6))
        ctk.CTkLabel(
            card,
            text="Configure company identity, visible system name, and the logo used by login and navigation.",
            font=("Segoe UI", 12),
            text_color=PALETTE["muted"],
            justify="left",
            wraplength=360,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 16))

        preview = ctk.CTkFrame(card, fg_color=PALETTE["card"], corner_radius=18, border_width=1, border_color=PALETTE["border"])
        preview.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 16))
        preview.grid_columnconfigure(1, weight=1)

        self.logo_preview_label = ctk.CTkLabel(preview, text="No Logo", width=84, height=84, corner_radius=16, fg_color=PALETTE["card_soft"], text_color=PALETTE["subtle"])
        self.logo_preview_label.grid(row=0, column=0, rowspan=3, padx=16, pady=16)
        self.logo_caption_label = ctk.CTkLabel(preview, text="Default application logo", font=("Segoe UI", 11), text_color=PALETTE["subtle"], anchor="w", justify="left", wraplength=220)
        self.logo_caption_label.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=(18, 6))

        self.logo_button = ctk.CTkButton(
            preview,
            text="Browse Logo",
            height=36,
            width=120,
            corner_radius=10,
            fg_color=PALETTE["card_soft"],
            hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.browse_logo,
        )
        self.logo_button.grid(row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 16))
        self.admin_only_widgets.append(self.logo_button)

        self.company_entry = self._entry_field(card, "Company Name", self.company_name_var, 3)
        self.system_entry = self._entry_field(card, "System Name", self.system_name_var, 5)
        self.admin_only_widgets.extend([self.company_entry, self.system_entry])

        ctk.CTkLabel(card, textvariable=self.branding_status_var, font=("Segoe UI", 12), text_color=PALETTE["subtle"], anchor="w").grid(row=7, column=0, sticky="w", padx=22, pady=(0, 10))
        self.save_branding_button = ctk.CTkButton(card, text="Save Branding", height=42, corner_radius=12, fg_color=PALETTE["success"], hover_color=PALETTE["success_hover"], text_color=PALETTE["page"], font=("Segoe UI Semibold", 13), command=self.save_branding)
        self.save_branding_button.grid(row=8, column=0, sticky="e", padx=22, pady=(0, 22))
        self.admin_only_widgets.append(self.save_branding_button)

    def _build_account_editor_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=PALETTE["panel"], corner_radius=24, border_width=1, border_color=PALETTE["border"])
        card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 14))
        card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(card, text="Account Editor", font=("Bahnschrift SemiBold", 24), text_color=PALETTE["text"], anchor="w").grid(row=0, column=0, sticky="w", padx=22, pady=(22, 6))
        ctk.CTkLabel(card, text="Create or update local admin/operator accounts for the monitoring workspace.", font=("Segoe UI", 12), text_color=PALETTE["muted"], justify="left", wraplength=360, anchor="w").grid(row=1, column=0, columnspan=2, sticky="w", padx=22, pady=(0, 16))

        self.photo_preview_label = ctk.CTkLabel(card, text="Photo", width=82, height=82, corner_radius=16, fg_color=PALETTE["card"], text_color=PALETTE["subtle"])
        self.photo_preview_label.grid(row=2, column=0, sticky="w", padx=22, pady=(0, 8))
        ctk.CTkLabel(card, textvariable=self.account_photo_caption_var, font=("Segoe UI", 11), text_color=PALETTE["subtle"], anchor="w", justify="left", wraplength=250).grid(row=2, column=1, sticky="w", padx=(0, 22))

        self.photo_button = ctk.CTkButton(card, text="Browse Photo", height=36, width=130, corner_radius=10, fg_color=PALETTE["card_soft"], hover_color=PALETTE["panel_alt"], text_color=PALETTE["text"], font=("Segoe UI Semibold", 12), command=self.browse_photo)
        self.photo_button.grid(row=3, column=0, sticky="w", padx=22, pady=(0, 16))
        self.admin_only_widgets.append(self.photo_button)

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.grid(row=4, column=0, columnspan=2, sticky="ew", padx=22)
        form.grid_columnconfigure((0, 1), weight=1)

        self.account_full_name_entry = self._form_entry(form, "Full Name", self.account_full_name_var, 0, 0)
        self.account_username_entry = self._form_entry(form, "Username", self.account_username_var, 0, 1)
        self.admin_only_widgets.extend([self.account_full_name_entry, self.account_username_entry])

        ctk.CTkLabel(form, text="Role", font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.role_option = ctk.CTkOptionMenu(form, variable=self.account_role_var, values=["ADMIN", "OPERATOR"], height=40, corner_radius=10, fg_color=PALETTE["accent"], button_color=PALETTE["accent_hover"], button_hover_color=PALETTE["accent_hover"], dropdown_fg_color=PALETTE["panel_alt"], dropdown_hover_color=PALETTE["card_soft"], text_color=PALETTE["text"], font=("Segoe UI Semibold", 12))
        self.role_option.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 14))
        self.admin_only_widgets.append(self.role_option)

        ctk.CTkLabel(form, text="Digital ID", font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=2, column=1, sticky="w", pady=(0, 8))
        self.digital_id_chip = ctk.CTkLabel(form, textvariable=self.account_digital_id_var, height=40, corner_radius=10, fg_color=PALETTE["card"], text_color=PALETTE["text"], anchor="w", padx=12)
        self.digital_id_chip.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 14))

        self.account_password_entry = self._password_entry(form, "Password", 4, 0)
        self.account_confirm_entry = self._password_entry(form, "Confirm Password", 4, 1)
        self.admin_only_widgets.extend([self.account_password_entry, self.account_confirm_entry])

        ctk.CTkLabel(form, text="Description", font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.account_description_box = ctk.CTkTextbox(form, height=90, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["text"], font=("Segoe UI", 12))
        self.account_description_box.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.admin_only_widgets.append(self.account_description_box)

        ctk.CTkLabel(card, textvariable=self.account_status_var, font=("Segoe UI", 12), text_color=PALETTE["subtle"], anchor="w", justify="left", wraplength=420).grid(row=5, column=0, columnspan=2, sticky="w", padx=22, pady=(0, 12))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 22))
        actions.grid_columnconfigure((0, 1, 2), weight=1)

        self.account_save_button = ctk.CTkButton(actions, textvariable=self.account_action_var, height=42, corner_radius=12, fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], text_color=PALETTE["text"], font=("Segoe UI Semibold", 13), command=self.save_account)
        self.account_save_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.account_reset_button = ctk.CTkButton(actions, text="Clear Form", height=42, corner_radius=12, fg_color=PALETTE["card_soft"], hover_color=PALETTE["panel_alt"], text_color=PALETTE["text"], font=("Segoe UI Semibold", 12), command=self.reset_account_form)
        self.account_reset_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.account_disable_button = ctk.CTkButton(actions, text="Disable Account", height=42, corner_radius=12, fg_color="#2a1b1f", hover_color="#7a434e", text_color=PALETTE["text"], font=("Segoe UI Semibold", 12), command=self.disable_selected_account)
        self.account_disable_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.admin_only_widgets.extend([self.account_save_button, self.account_reset_button, self.account_disable_button])

    def _build_account_directory_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=PALETTE["panel"], corner_radius=24, border_width=1, border_color=PALETTE["border"])
        card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 16))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(22, 14))
        header.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_wrap, text="Account Directory", font=("Bahnschrift SemiBold", 24), text_color=PALETTE["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(title_wrap, text="Disabled accounts remain visible for accountability and audit traceability.", font=("Segoe UI", 12), text_color=PALETTE["muted"], anchor="w").pack(anchor="w", pady=(6, 0))

        self.new_account_button = ctk.CTkButton(header, text="New Account", height=38, width=120, corner_radius=12, fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], text_color=PALETTE["text"], font=("Segoe UI Semibold", 12), command=self.reset_account_form)
        self.new_account_button.grid(row=0, column=1, sticky="e")
        self.admin_only_widgets.append(self.new_account_button)

        table_wrap = tk.Frame(card, bg=PALETTE["panel"])
        table_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        columns = ("digital_id", "full_name", "username", "role", "status")
        self.account_tree = ttk.Treeview(table_wrap, columns=columns, show="headings", style="Accounts.Treeview", height=8)
        for column, heading, width in (
            ("digital_id", "Digital ID", 140),
            ("full_name", "Full Name", 220),
            ("username", "Username", 150),
            ("role", "Role", 100),
            ("status", "Status", 110),
        ):
            self.account_tree.heading(column, text=heading)
            self.account_tree.column(column, width=width, anchor="center")

        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)
        self.account_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.account_tree.bind("<<TreeviewSelect>>", self.on_account_selected)
        self.account_tree.tag_configure("ACTIVE", foreground=PALETTE["success"])
        self.account_tree.tag_configure("DISABLED", foreground=PALETTE["danger"])

    def _build_monitoring_section(self, row_index):
        # ── Profile Definitions ──
        self._profile_presets = {
            "high": {
                "conf_thr": 0.25, "agg_thr": 450.0, "active_thr": 140.0,
                "alert_frames": 2, "motion_threshold": 4500, "motion_ratio": 0.009,
                "yolo_knife_conf": 0.30, "yolo_cell_conf": 0.30, "yolo_fallback_conf": 0.50,
            },
            "medium": {
                "conf_thr": 0.22, "agg_thr": 180.0, "active_thr": 90.0,
                "alert_frames": 3, "motion_threshold": 5000, "motion_ratio": 0.010,
                "yolo_knife_conf": 0.30, "yolo_cell_conf": 0.30, "yolo_fallback_conf": 0.50,
            },
            "low": {
                "conf_thr": 0.18, "agg_thr": 700.0, "active_thr": 250.0,
                "alert_frames": 5, "motion_threshold": 6000, "motion_ratio": 0.012,
                "yolo_knife_conf": 0.30, "yolo_cell_conf": 0.30, "yolo_fallback_conf": 0.50,
            },
        }
        self._profile_descriptions = {
            "high": "Designed for rapid detection of significant movement while maintaining stricter validation to reduce false aggression alerts.",
            "medium": "Standard monitoring configuration. Balanced sensitivity for typical activity levels.",
            "low": "Conservative monitoring mode designed to minimize false alerts by requiring stronger evidence before triggering detections.",
            "custom": "User-configured threshold settings for MoveNet behavior tracking and YOLO26s contraband detection.",
        }

        # ── Load persisted settings ──
        ai_cfg = profile_store.get_ai_settings()
        saved_profile = ai_cfg["active_profile"]
        saved_custom = ai_cfg["custom_settings"]

        group = ctk.CTkFrame(self.main_view, fg_color=PALETTE["panel"], corner_radius=24, border_width=1, border_color=PALETTE["border"])
        group.grid(row=row_index, column=0, sticky="ew", padx=28, pady=(0, 28))
        group.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(group, text="Monitoring Tuning", font=("Bahnschrift SemiBold", 24), text_color=PALETTE["text"], anchor="w").grid(row=0, column=0, sticky="w", padx=22, pady=(22, 6))
        ctk.CTkLabel(group, text="AI thresholds and confidence levels can be tuned here. Camera management is now handled directly via the Live Monitor [+] portal.", font=("Segoe UI", 12), text_color=PALETTE["muted"], justify="left", wraplength=820, anchor="w").grid(row=1, column=0, sticky="w", padx=22, pady=(0, 16))

        # Define configurations
        self.PARAMS_CFG = {
            "conf_thr": ("Pose Confidence", 0.05, 0.95, 90, "Minimum average MoveNet confidence required before a detected pose is considered valid for movement analysis. Increasing this reduces false alarms but may cause actual movements to be ignored. Decreasing this detects more but increases false positives.", False),
            "active_thr": ("Fast Movement (px/sec)", 10.0, 500.0, 98, "Movement speed threshold used to classify activity as fast movement. Measured in pixels per second.", False),
            "agg_thr": ("Aggressive Movement (px/sec)", 50.0, 1000.0, 95, "Movement speed threshold used to classify behavior as aggressive or potentially violent. Measured in pixels per second.", False),
            "alert_frames": ("Alert Frame Count", 1, 15, 14, "Number of consecutive frames that must satisfy detection conditions before an alert is generated.", True),
            "motion_threshold": ("Motion Threshold (pixels)", 500, 20000, 195, "Minimum amount of pixel change required before AI analysis is activated.", True),
            "motion_ratio": ("Motion Ratio", 0.001, 0.050, 49, "Percentage of the image frame that must change before the AI engine wakes from motion-gating mode.", False),
            "yolo_knife_conf": ("Knife Confidence", 0.05, 0.95, 90, "Minimum YOLO26s confidence score required before a knife detection is accepted. Increasing this reduces false alarms but may miss actual weapons. Decreasing this detects more but increases false positives.", False),
            "yolo_cell_conf": ("Cellphone Confidence", 0.05, 0.95, 90, "Minimum YOLO26s confidence score required before a cellphone detection is accepted. Increasing this reduces false alarms but may miss actual devices. Decreasing this detects more but increases false positives.", False),
            "yolo_fallback_conf": ("Fallback Confidence", 0.05, 0.95, 90, "General confidence threshold used for detections that do not have a dedicated class-specific threshold. Increasing this reduces false alarms. Decreasing this detects more but increases false positives.", False)
        }

        self.PRESETS = {
            "high": {
                "conf_thr": 0.25, "active_thr": 140.0, "agg_thr": 450.0, "alert_frames": 2, "motion_threshold": 4500, "motion_ratio": 0.009, "yolo_knife_conf": 0.30, "yolo_cell_conf": 0.30, "yolo_fallback_conf": 0.50
            },
            "medium": {
                "conf_thr": 0.22, "active_thr": 90.0, "agg_thr": 180.0, "alert_frames": 3, "motion_threshold": 5000, "motion_ratio": 0.010, "yolo_knife_conf": 0.30, "yolo_cell_conf": 0.30, "yolo_fallback_conf": 0.50
            },
            "low": {
                "conf_thr": 0.18, "active_thr": 250.0, "agg_thr": 700.0, "alert_frames": 5, "motion_threshold": 6000, "motion_ratio": 0.012, "yolo_knife_conf": 0.40, "yolo_cell_conf": 0.40, "yolo_fallback_conf": 0.60
            }
        }

        # Dropdown for profile selection
        profile_frame = ctk.CTkFrame(group, fg_color="transparent")
        profile_frame.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 10))
        
        ctk.CTkLabel(profile_frame, text="Active Detection Profile", font=("Segoe UI Semibold", 13), text_color=PALETTE["muted"]).pack(side="left", padx=(0, 10))
        
        self.profile_var = tk.StringVar(value="Medium")
        self.profile_menu = ctk.CTkOptionMenu(
            profile_frame,
            variable=self.profile_var,
            values=["High", "Medium", "Low", "Custom"],
            width=140,
            height=36,
            corner_radius=8,
            fg_color=PALETTE["accent"],
            button_color=PALETTE["accent_hover"],
            button_hover_color=PALETTE["accent_hover"],
            dropdown_fg_color=PALETTE["panel_alt"],
            dropdown_hover_color=PALETTE["card_soft"],
            text_color=PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self._on_profile_change
        )
        self.profile_menu.pack(side="left")
        self.admin_only_widgets.append(self.profile_menu)

        grid_frame = ctk.CTkFrame(group, fg_color="transparent")
        grid_frame.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 10))
        grid_frame.grid_columnconfigure((0, 1), weight=1, uniform="tuning_cols")

        behavior_card = ctk.CTkFrame(grid_frame, fg_color=PALETTE["card"], corner_radius=18, border_width=1, border_color=PALETTE["border"])
        behavior_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        behavior_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(behavior_card, text="Pose & Motion Gating", font=("Segoe UI Bold", 14), text_color=PALETTE["accent"]).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        yolo_card = ctk.CTkFrame(grid_frame, fg_color=PALETTE["card"], corner_radius=18, border_width=1, border_color=PALETTE["border"])
        yolo_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        yolo_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(yolo_card, text="YOLO26s Contraband Detection", font=("Segoe UI Bold", 14), text_color=PALETTE["accent"]).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        self.sliders = {}
        self.slider_val_labels = {}

        behavior_keys = ["conf_thr", "active_thr", "agg_thr", "alert_frames", "motion_threshold", "motion_ratio"]
        for idx, key in enumerate(behavior_keys, start=1):
            self._create_slider_row(behavior_card, key, idx)

        yolo_keys = ["yolo_knife_conf", "yolo_cell_conf", "yolo_fallback_conf"]
        for idx, key in enumerate(yolo_keys, start=1):
            self._create_slider_row(yolo_card, key, idx)

        info_box = ctk.CTkFrame(yolo_card, fg_color=PALETTE["card_soft"], corner_radius=12)
        info_box.grid(row=4, column=0, sticky="ew", padx=16, pady=(10, 16))
        info_text = ("Note: YOLO26s model (best.pt) handles class 0 (knife) and class 1 (cellphone).\n"
                     "Heavy inference is gated by motion detection to conserve power.")
        ctk.CTkLabel(info_box, text=info_text, font=("Segoe UI", 11), text_color=PALETTE["muted"], justify="left", wraplength=320).pack(padx=12, pady=10)

        db_settings = profile_store.get_ai_settings()
        active_prof = db_settings.get("active_profile", "medium").title()
        self.profile_var.set(active_prof)
        custom_vals = db_settings.get("custom_settings", {})
        profile_key = active_prof.lower()
        current_vals = self.PRESETS[profile_key] if profile_key in self.PRESETS else custom_vals

        for key in self.PARAMS_CFG:
            val = current_vals.get(key, self.PARAMS_CFG[key][1])
            self.sliders[key].set(val)
            is_int = self.PARAMS_CFG[key][5]
            if is_int: self.slider_val_labels[key].configure(text=f"{int(val)}")
            else: self.slider_val_labels[key].configure(text=f"{val:.3f}" if key == "motion_ratio" else f"{val:.2f}")
            if profile_key in self.PRESETS or not self.is_admin: self.sliders[key].configure(state="disabled")

        # Developer Options Card
        dev_frame = ctk.CTkFrame(group, fg_color=PALETTE["card"], corner_radius=12, border_width=1, border_color="#e5c07b")
        dev_frame.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 10))
        ctk.CTkLabel(dev_frame, text="DEVELOPER OPTIONS (EXPERIMENTAL)", font=("Segoe UI Bold", 13), text_color="#e5c07b").pack(anchor="w", padx=16, pady=(12, 5))
        
        dev_content = ctk.CTkFrame(dev_frame, fg_color="transparent")
        dev_content.pack(fill="x", padx=16, pady=(0, 12))
        
        # imgsz radio buttons
        ctk.CTkLabel(dev_content, text="YOLO Inference Resolution (imgsz):", font=("Segoe UI Semibold", 12), text_color=PALETTE["text"]).grid(row=0, column=0, sticky="w", pady=(5, 5))
        self.dev_imgsz_var = tk.IntVar(value=960)
        imgsz_frame = ctk.CTkFrame(dev_content, fg_color="transparent")
        imgsz_frame.grid(row=0, column=1, sticky="w", padx=15)
        for val in [640, 960, 1280]:
            rb = ctk.CTkRadioButton(imgsz_frame, text=str(val), variable=self.dev_imgsz_var, value=val, font=("Segoe UI", 12), fg_color="#e5c07b", hover_color="#d19a66", text_color=PALETTE["text"])
            rb.pack(side="left", padx=(0, 15))
            self.admin_only_widgets.append(rb)
            
        # motion gate toggles
        ctk.CTkLabel(dev_content, text="Motion Gating (Disable to run every frame, lowering FPS):", font=("Segoe UI Semibold", 12), text_color=PALETTE["text"]).grid(row=1, column=0, sticky="w", pady=(10, 5))
        gate_frame = ctk.CTkFrame(dev_content, fg_color="transparent")
        gate_frame.grid(row=1, column=1, sticky="w", padx=15, pady=(10, 5))
        
        self.dev_gate_movenet_var = tk.BooleanVar(value=True)
        self.dev_gate_yolo_var = tk.BooleanVar(value=True)
        
        gate_m = ctk.CTkSwitch(gate_frame, text="MoveNet Gated", variable=self.dev_gate_movenet_var, font=("Segoe UI", 12), progress_color="#e5c07b", text_color=PALETTE["text"])
        gate_m.pack(side="left", padx=(0, 15))
        self.admin_only_widgets.append(gate_m)
        
        gate_y = ctk.CTkSwitch(gate_frame, text="YOLO Gated", variable=self.dev_gate_yolo_var, font=("Segoe UI", 12), progress_color="#e5c07b", text_color=PALETTE["text"])
        gate_y.pack(side="left")
        self.admin_only_widgets.append(gate_y)
        
        # Load values
        from monitor_app.config import get_config
        self.dev_imgsz_var.set(get_config("yolo", "inference_imgsz", 960))
        self.dev_gate_movenet_var.set(get_config("motion_gate", "motion_gate_movenet_enabled", True))
        self.dev_gate_yolo_var.set(get_config("motion_gate", "motion_gate_yolo_enabled", True))

        footer = ctk.CTkFrame(group, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=22, pady=(0, 22))
        ctk.CTkLabel(footer, text="Settings are saved locally and applied to the AI engine on startup.", font=("Segoe UI", 12), text_color=PALETTE["subtle"], anchor="w").pack(side="left")
        
        self.monitoring_save_button = ctk.CTkButton(footer, text="Save AI Preferences", font=("Segoe UI Semibold", 13), fg_color=PALETTE["success"], hover_color=PALETTE["success_hover"], text_color=PALETTE["page"], height=44, corner_radius=12, command=self.save_settings)
        self.monitoring_save_button.pack(side="right")
        self.admin_only_widgets.append(self.monitoring_save_button)

        self.btn_manage_cams = ctk.CTkButton(
            footer, text="Manage Camera Network", font=("Segoe UI Semibold", 13),
            fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["page"], height=44, corner_radius=12,
            command=self._open_camera_management
        )
        self.btn_manage_cams.pack(side="right", padx=(0, 10))
        self.admin_only_widgets.append(self.btn_manage_cams)

        self.monitoring_reset_button = ctk.CTkButton(
            footer, text="Reset Custom to Medium", font=("Segoe UI Semibold", 13),
            fg_color=PALETTE["card_soft"], hover_color=PALETTE["panel_alt"],
            text_color=PALETTE["text"], height=44, corner_radius=12,
            border_width=1, border_color=PALETTE["border"],
            command=self.reset_custom_to_medium
        )
        self.monitoring_reset_button.pack(side="right", padx=(0, 12))
        self.admin_only_widgets.append(self.monitoring_reset_button)

    def _create_slider_row(self, parent_card, key, row_idx):
        label_text, val_min, val_max, steps, tooltip_text, is_int = self.PARAMS_CFG[key]
        row_frame = ctk.CTkFrame(parent_card, fg_color="transparent")
        row_frame.grid(row=row_idx, column=0, sticky="ew", padx=16, pady=(0, 14))
        row_frame.grid_columnconfigure(1, weight=1)
        lbl_container = ctk.CTkFrame(row_frame, fg_color="transparent")
        lbl_container.grid(row=0, column=0, sticky="w", columnspan=3, pady=(0, 4))
        ctk.CTkLabel(lbl_container, text=label_text, font=("Segoe UI Semibold", 12), text_color=PALETTE["text"]).pack(side="left")
        help_btn = ctk.CTkLabel(lbl_container, text=" (?)", font=("Segoe UI", 11, "bold"), text_color=PALETTE["subtle"], cursor="question_arrow")
        help_btn.pack(side="left", padx=(4, 0))
        CTkTooltip(help_btn, tooltip_text)
        val_lbl = ctk.CTkLabel(row_frame, text="0.00", font=("Segoe UI Semibold", 12), text_color=PALETTE["accent"], width=50, anchor="e")
        val_lbl.grid(row=1, column=2, sticky="e")
        self.slider_val_labels[key] = val_lbl
        slider = ctk.CTkSlider(row_frame, from_=val_min, to=val_max, number_of_steps=steps, button_color=PALETTE["accent"], button_hover_color=PALETTE["accent_hover"], progress_color=PALETTE["accent"], command=lambda val, k=key: self._on_slider_move(k, val))
        slider.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        self.sliders[key] = slider
        self.admin_only_widgets.append(slider)

    def _on_slider_move(self, key, val):
        is_int = self.PARAMS_CFG[key][5]
        formatted_val = f"{int(val)}" if is_int else (f"{val:.3f}" if key == "motion_ratio" else f"{val:.2f}")
        self.slider_val_labels[key].configure(text=formatted_val)
        if self.profile_var.get() != "Custom": self.profile_var.set("Custom")

    def _on_profile_change(self, selected_profile):
        selected_profile = selected_profile.lower()
        if selected_profile in self.PRESETS:
            preset_vals = self.PRESETS[selected_profile]
            for key, val in preset_vals.items():
                self.sliders[key].set(val)
                is_int = self.PARAMS_CFG[key][5]
                formatted_val = f"{int(val)}" if is_int else (f"{val:.3f}" if key == "motion_ratio" else f"{val:.2f}")
                self.slider_val_labels[key].configure(text=formatted_val)
                self.sliders[key].configure(state="disabled")
        else:
            for key in self.PARAMS_CFG:
                if self.is_admin: self.sliders[key].configure(state="normal")

    def reset_custom_to_medium(self):
        if not self.is_admin:
            return
            
        self.profile_var.set("Custom")
        self._on_profile_change("Custom")
        
        medium_preset = self.PRESETS["medium"]
        for key, val in medium_preset.items():
            self.sliders[key].set(val)
            is_int = self.PARAMS_CFG[key][5]
            if is_int:
                self.slider_val_labels[key].configure(text=f"{int(val)}")
            else:
                self.slider_val_labels[key].configure(text=f"{val:.3f}" if key == "motion_ratio" else f"{val:.2f}")
                
        messagebox.showinfo("Monitoring Preferences", "Custom settings reset to Medium preset baseline. Click Save to persist.")

    def _open_camera_management(self):
        from monitor_app.camera_view import CameraManagementDialog
        from monitor_app.main import CellWatchApp
        # Get reference to the root app to refresh Live Monitor
        root = self.winfo_toplevel()
        
        def _on_refresh():
            if hasattr(root, "frames") and "Live Monitor" in root.frames:
                root.frames["Live Monitor"].refresh_cameras()

        dialog = CameraManagementDialog(self, on_refresh=_on_refresh)
        dialog.grab_set()
        dialog.focus_force()
        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.grab_release(), dialog.on_refresh(), dialog.destroy()))

    def _configure_tree_style(self):
        style = ttk.Style()
        style.configure("Accounts.Treeview", background=PALETTE["card"], foreground=PALETTE["text"], fieldbackground=PALETTE["card"], rowheight=32, borderwidth=0, relief="flat", font=("Segoe UI", 10))
        style.map("Accounts.Treeview", background=[("selected", PALETTE["accent"])], foreground=[("selected", PALETTE["text"])])
        style.configure("Accounts.Treeview.Heading", background=PALETTE["panel_alt"], foreground=PALETTE["text"], relief="flat", borderwidth=0, font=("Segoe UI Semibold", 10))
        style.map("Accounts.Treeview.Heading", background=[("active", PALETTE["panel_alt"])], foreground=[("active", PALETTE["text"])])

    def _entry_field(self, parent, label, variable, row):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=row, column=0, sticky="w", padx=22, pady=(0, 8))
        entry = ctk.CTkEntry(parent, textvariable=variable, height=40, corner_radius=10, fg_color=PALETTE["card"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=("Segoe UI", 12))
        entry.grid(row=row + 1, column=0, sticky="ew", padx=22, pady=(0, 14))
        return entry

    def _form_entry(self, parent, label, variable, row, column):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=row, column=column, sticky="w", pady=(0, 8))
        entry = ctk.CTkEntry(parent, textvariable=variable, height=40, corner_radius=10, fg_color=PALETTE["card"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=("Segoe UI", 12))
        entry.grid(row=row + 1, column=column, sticky="ew", padx=(0 if column == 0 else 8, 8 if column == 0 else 0), pady=(0, 14))
        return entry

    def _password_entry(self, parent, label, row, column):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI Semibold", 12), text_color=PALETTE["muted"], anchor="w").grid(row=row, column=column, sticky="w", pady=(0, 8))
        entry = ctk.CTkEntry(parent, height=40, corner_radius=10, fg_color=PALETTE["card"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=("Segoe UI", 12), show="*")
        entry.grid(row=row + 1, column=column, sticky="ew", padx=(0 if column == 0 else 8, 8 if column == 0 else 0), pady=(0, 14))
        return entry

    def _apply_access_rules(self):
        from monitor_app.utils import GlobalState
        if GlobalState.benchmark_active:
            if self.show_identity:
                self.branding_status_var.set("LOCKED (Benchmark)")
                self.account_status_var.set("Settings locked during active benchmark run.")
            if self.show_monitoring:
                self.monitoring_state_var.set("LOCKED (Benchmark)")
            for widget in self.admin_only_widgets:
                try:
                    widget.configure(state="disabled")
                except Exception:
                    pass
            if hasattr(self, "account_description_box"):
                self.account_description_box.configure(state="disabled")
            return

        if self.is_admin:
            return
        if self.show_identity:
            self.branding_status_var.set("View Only")
            self.account_status_var.set("Only admin accounts can create, edit, or disable users.")
        if self.show_monitoring:
            self.monitoring_state_var.set("View Only")
        for widget in self.admin_only_widgets:
            try:
                widget.configure(state="disabled")
            except tk.TclError:
                pass
        if hasattr(self, "account_description_box"):
            self.account_description_box.configure(state="disabled")

    def _update_slider_value(self, label, value):
        if label in self.slider_labels:
            self.slider_labels[label].configure(text=f"{value:.2f}")

    def load_profile(self):
        if not hasattr(self, "logo_preview_label"):
            return
        profile = profile_store.get_app_profile()
        self.company_name_var.set(profile["company_name"])
        self.system_name_var.set(profile["system_name"])
        self._load_logo_preview(profile.get("logo_abspath"))
        self.selected_logo_source = None

    def load_users(self):
        if not hasattr(self, "account_tree"):
            return
        users = profile_store.list_users(include_disabled=True)
        self.account_count_var.set(f"{len(users)} accounts")
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        for user in users:
            status = "Active" if user["is_active"] else "Disabled"
            tag = "ACTIVE" if user["is_active"] else "DISABLED"
            self.account_tree.insert("", tk.END, iid=str(user["user_id"]), values=(user["digital_id"], user["full_name"], user["username"], user["role"].title(), status), tags=(tag,))

    def browse_logo(self):
        path = filedialog.askopenfilename(title="Select logo image", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif")])
        if not path:
            return
        self.selected_logo_source = path
        self._load_logo_preview(path)
        self.branding_status_var.set("Logo queued for save")

    def browse_photo(self):
        path = filedialog.askopenfilename(title="Select profile photo", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif")])
        if not path:
            return
        self.selected_photo_source = path
        self._load_photo_preview(path)
        self.account_photo_caption_var.set(os.path.basename(path))

    def save_branding(self):
        if not self.is_admin:
            return
        try:
            profile_store.update_app_profile(
                self.company_name_var.get(),
                self.system_name_var.get(),
                logo_source_path=self.selected_logo_source,
                actor_username=self.current_user.get("username"),
            )
        except Exception as exc:
            self.branding_status_var.set(str(exc))
            return
        self.load_profile()
        self.branding_status_var.set("Saved")
        if self.on_profile_updated:
            self.on_profile_updated()
        messagebox.showinfo("Branding Saved", "System profile and branding assets were updated.")

    def save_account(self):
        if not self.is_admin:
            return

        full_name = self.account_full_name_var.get().strip()
        username = self.account_username_var.get().strip()
        role = self.account_role_var.get().strip().upper()
        description = self.account_description_box.get("1.0", tk.END).strip()
        password = self.account_password_entry.get()
        confirm = self.account_confirm_entry.get()

        if password or confirm:
            if password != confirm:
                self.account_status_var.set("Password and confirmation do not match.")
                return

        if self.selected_user_id is None:
            if not description:
                self.account_status_var.set("New accounts require a short personnel description.")
                return
            if not self.selected_photo_source:
                self.account_status_var.set("New accounts require a profile photo.")
                return

        try:
            if self.selected_user_id is None:
                if not password:
                    self.account_status_var.set("New accounts require a password.")
                    return
                user = profile_store.create_user(
                    full_name=full_name,
                    username=username,
                    password=password,
                    role=role,
                    description=description,
                    photo_source_path=self.selected_photo_source,
                    actor_username=self.current_user.get("username"),
                )
                self.account_status_var.set(f"Created account for {user['full_name']}.")
            else:
                user = profile_store.update_user(
                    user_id=self.selected_user_id,
                    full_name=full_name,
                    username=username,
                    password=password or None,
                    role=role,
                    description=description,
                    photo_source_path=self.selected_photo_source,
                    actor_username=self.current_user.get("username"),
                )
                self.account_status_var.set(f"Updated account for {user['full_name']}.")
        except Exception as exc:
            self.account_status_var.set(str(exc))
            return

        self.load_users()
        self._select_user_in_tree(user["user_id"])
        self.load_user_into_form(user["user_id"])
        messagebox.showinfo("Account Saved", "Account details were saved successfully.")

    def disable_selected_account(self):
        if not self.is_admin or self.selected_user_id is None:
            return
        if self.current_user.get("user_id") == self.selected_user_id:
            self.account_status_var.set("You cannot disable the account that is currently signed in.")
            return
        user = profile_store.get_user_by_id(self.selected_user_id)
        if user is None:
            self.account_status_var.set("Select a valid account first.")
            return
        if not messagebox.askyesno("Disable Account", f"Disable account '{user['username']}'? The record will remain for audit history."):
            return
        try:
            profile_store.disable_user(self.selected_user_id, actor_username=self.current_user.get("username"))
        except Exception as exc:
            self.account_status_var.set(str(exc))
            return
        self.load_users()
        self.reset_account_form()
        self.account_status_var.set(f"Disabled account '{user['username']}'.")
        messagebox.showinfo("Account Disabled", "The account was disabled and retained for audit history.")

    def reset_account_form(self):
        self.selected_user_id = None
        self.selected_photo_source = None
        self.account_full_name_var.set("")
        self.account_username_var.set("")
        self.account_role_var.set("OPERATOR")
        self.account_digital_id_var.set("Generated on create")
        self.account_action_var.set("Create Account")
        self.account_status_var.set("Create a new account or select one from the directory.")
        self.account_photo_caption_var.set("No profile photo selected")
        self.account_password_entry.delete(0, tk.END)
        self.account_confirm_entry.delete(0, tk.END)
        self.account_description_box.configure(state="normal")
        self.account_description_box.delete("1.0", tk.END)
        self._load_photo_preview(None)
        if not self.is_admin:
            self.account_description_box.configure(state="disabled")

    def on_account_selected(self, _event):
        selection = self.account_tree.selection()
        if selection:
            self.load_user_into_form(int(selection[0]))

    def load_user_into_form(self, user_id):
        user = profile_store.get_user_by_id(user_id)
        if user is None:
            return
        self.selected_user_id = user_id
        self.selected_photo_source = None
        self.account_full_name_var.set(user["full_name"])
        self.account_username_var.set(user["username"])
        self.account_role_var.set(user["role"])
        self.account_digital_id_var.set(user["digital_id"])
        self.account_action_var.set("Update Account")
        self.account_status_var.set(f"Editing {user['username']} ({'Active' if user['is_active'] else 'Disabled'}). Leave password blank to keep the current login.")
        photo_path = user.get("photo_path")
        self.account_photo_caption_var.set(os.path.basename(photo_path) if photo_path else "No profile photo stored")
        self.account_password_entry.delete(0, tk.END)
        self.account_confirm_entry.delete(0, tk.END)
        self.account_description_box.configure(state="normal")
        self.account_description_box.delete("1.0", tk.END)
        self.account_description_box.insert("1.0", user.get("description") or "")
        self._load_photo_preview(user.get("photo_abspath"))
        if not self.is_admin:
            self.account_description_box.configure(state="disabled")

    def _select_user_in_tree(self, user_id):
        iid = str(user_id)
        if iid in self.account_tree.get_children():
            self.account_tree.selection_set(iid)
            self.account_tree.focus(iid)
            self.account_tree.see(iid)

    def _load_logo_preview(self, image_path):
        self.logo_preview_image = self._build_preview_image(image_path, (74, 74))
        if self.logo_preview_image is None:
            self.logo_preview_label.configure(image=None, text="No Logo")
            self.logo_caption_label.configure(text="Default application logo")
            return
        self.logo_preview_label.configure(image=self.logo_preview_image, text="")
        self.logo_caption_label.configure(text=os.path.basename(image_path))

    def _load_photo_preview(self, image_path):
        self.photo_preview_image = self._build_preview_image(image_path, (72, 72))
        if self.photo_preview_image is None:
            self.photo_preview_label.configure(image=None, text="Photo")
            return
        self.photo_preview_label.configure(image=self.photo_preview_image, text="")

    def _build_preview_image(self, image_path, size):
        if not image_path or not isinstance(image_path, str) or not os.path.exists(image_path):
            return None
        try:
            image = Image.open(image_path)
            return ctk.CTkImage(light_image=image, dark_image=image, size=size)
        except Exception:
            return None

    def test_connection(self, camera_index):
        messagebox.showinfo("Test Connection", f"Connection test for Camera {camera_index} is not wired yet in this build.")

    def save_settings(self):
        if not self.is_admin:
            return
            
        profile = self.profile_var.get().lower()
        custom_vals = {}
        for key in self.PARAMS_CFG:
            val = self.sliders[key].get()
            if self.PARAMS_CFG[key][5]: # is_int
                val = int(val)
            custom_vals[key] = val
            
        try:
            profile_store.save_ai_settings(profile, custom_vals, actor_username=self.current_user.get("username") if self.current_user else "system")
            
            # Save developer options
            from monitor_app.config import save_developer_config
            dev_updates = {
                "inference_imgsz": self.dev_imgsz_var.get(),
                "motion_gate_movenet_enabled": self.dev_gate_movenet_var.get(),
                "motion_gate_yolo_enabled": self.dev_gate_yolo_var.get()
            }
            save_developer_config(dev_updates)
            
            # Live-apply to running engine
            try:
                from monitor_app.central_inference import get_inference_manager
                engine = get_inference_manager().engine
                if engine:
                    engine._set_logic_sensitivity(profile, custom_vals)
                    # Note: engine reads developer configs on-the-fly via get_config() so no need to push them
                    print(f"Applied AI settings live to central inference engine: profile={profile}")
            except Exception as e:
                print(f"Failed to live-apply AI settings: {e}")

            self.monitoring_state_var.set("Saved")
            messagebox.showinfo("Monitoring Preferences", "AI thresholds and detection profile saved and applied live.")
        except Exception as exc:
            messagebox.showerror("Database Error", f"Failed to save settings: {exc}")
