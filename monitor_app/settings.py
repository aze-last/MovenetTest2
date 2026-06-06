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
        group = ctk.CTkFrame(self.main_view, fg_color=PALETTE["panel"], corner_radius=24, border_width=1, border_color=PALETTE["border"])
        group.grid(row=row_index, column=0, sticky="ew", padx=28, pady=(0, 28))
        group.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(group, text="Monitoring Tuning", font=("Bahnschrift SemiBold", 24), text_color=PALETTE["text"], anchor="w").grid(row=0, column=0, sticky="w", padx=22, pady=(22, 6))
        ctk.CTkLabel(group, text="AI thresholds and confidence levels can be tuned here. Camera management is now handled directly via the Live Monitor [+] portal.", font=("Segoe UI", 12), text_color=PALETTE["muted"], justify="left", wraplength=820, anchor="w").grid(row=1, column=0, sticky="w", padx=22, pady=(0, 16))

        self.slider_labels = {}
        for offset, (label, default) in enumerate((("Motion Threshold", 0.70), ("Aggression Confidence", 0.85), ("Contraband Confidence", 0.90)), start=2):
            row = ctk.CTkFrame(group, fg_color="transparent")
            row.grid(row=offset, column=0, sticky="ew", padx=22, pady=(0, 18))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=label, font=("Segoe UI Semibold", 13), text_color=PALETTE["muted"], width=180, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
            value_label = ctk.CTkLabel(row, text=f"{default:.2f}", font=("Segoe UI", 13), text_color=PALETTE["accent"], width=42, anchor="e")
            value_label.grid(row=0, column=2, sticky="e")
            self.slider_labels[label] = value_label
            slider = ctk.CTkSlider(row, from_=0.0, to=1.0, number_of_steps=100, button_color=PALETTE["accent"], button_hover_color=PALETTE["accent_hover"], progress_color=PALETTE["accent"], command=lambda value, name=label: self._update_slider_value(name, value))
            slider.set(default)
            slider.grid(row=0, column=1, sticky="ew", padx=(0, 20))
            self.admin_only_widgets.append(slider)

        footer = ctk.CTkFrame(group, fg_color="transparent")
        footer.grid(row=9, column=0, sticky="ew", padx=22, pady=(0, 22))
        ctk.CTkLabel(footer, text="Threshold persistence is simulated in this build.", font=("Segoe UI", 12), text_color=PALETTE["subtle"], anchor="w").pack(side="left")
        self.monitoring_save_button = ctk.CTkButton(footer, text="Save AI Preferences", font=("Segoe UI Semibold", 13), fg_color=PALETTE["success"], hover_color=PALETTE["success_hover"], text_color=PALETTE["page"], height=44, corner_radius=12, command=self.save_settings)
        self.monitoring_save_button.pack(side="right")
        self.admin_only_widgets.append(self.monitoring_save_button)

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
        self.monitoring_state_var.set("Demo Only")
        messagebox.showinfo("Monitoring Preferences", "Camera and AI tuning persistence is not wired yet in this build. Branding and account management are now functional.")
