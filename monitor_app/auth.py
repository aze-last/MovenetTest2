import os
import sys
import customtkinter as ctk
from PIL import Image
from monitor_app import profile_store, utils


def _is_caps_lock_on():
    """Detects Caps Lock status using standard library OS calls."""
    try:
        if sys.platform == "win32":
            import ctypes
            return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    except Exception:
        pass
    return False


class LoginScreen(ctk.CTkFrame):
    # Institutional Dual-Mode Palette (Light Mode, Dark Mode)
    PALETTE = {
        "page_bg": ("#edf2f7", "#06090c"),         # Light slate base vs deep void
        "hero_bg": ("#e2e8f0", "#0a0e13"),         # Elevated slate panel vs dark hero
        "card_bg": ("#ffffff", "#121a24"),         # Crisp white card vs elevated dark card
        "card_border": ("#cbd5e1", "#1e2c3a"),     # 1px perimeter border
        "input_bg": ("#f8fafc", "#182330"),        # Field surface
        "border_subtle": ("#cbd5e1", "#1e2c3a"),   # Subtle divider & field borders
        "border_active": ("#2563eb", "#3e709e"),   # Focus border glow (royal blue / bright steel)
        "accent": ("#1d4ed8", "#4f84bb"),          # Primary action color (navy / institutional blue)
        "accent_hover": ("#1e40af", "#5c9ad6"),    # Hover state for accent
        "btn_secondary": ("#e2e8f0", "#1c2836"),   # Secondary action background (Show/Hide, Theme Toggle)
        "btn_secondary_hover": ("#cbd5e1", "#27384c"),
        "text_main": ("#0f172a", "#ffffff"),       # Primary text
        "text_dim": ("#334155", "#a2b5c7"),        # Secondary / field labels
        "text_muted": ("#64748b", "#7e94a8"),      # Captions, badges, placeholders
        "danger": ("#dc2626", "#f25c5c"),          # Error text & alerts
        "warning": ("#b45309", "#f2c94c"),         # Warning / Caps lock text
        "success": ("#16a34a", "#50d186"),         # Success / progress
    }

    def __init__(self, parent, on_login_success):
        profile_store.ensure_app_state()
        saved_mode = profile_store.get_appearance_mode()
        ctk.set_appearance_mode(saved_mode)

        super().__init__(parent, fg_color=self.PALETTE["page_bg"])
        self.on_login_success = on_login_success
        self.branding = profile_store.get_branding()
        self._password_masked = True
        self.pack(fill="both", expand=True)

        # 50/50 Split Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._create_left_panel()
        self._create_right_panel()

    def _create_left_panel(self):
        # The Hero Panel: Visual branding and system mission
        hero = ctk.CTkFrame(self, fg_color=self.PALETTE["hero_bg"], corner_radius=0)
        hero.grid(row=0, column=0, sticky="nsew")

        # Subtle Vertical Glow Rail
        rail = ctk.CTkFrame(hero, fg_color=self.PALETTE["accent"], width=4, corner_radius=0)
        rail.place(relx=0.0, rely=0.0, relheight=1.0)

        # Content Container with generous padding
        content = ctk.CTkFrame(hero, fg_color="transparent")
        content.place(relx=0.5, rely=0.5, anchor="center")

        # 1. Badge
        badge = ctk.CTkFrame(
            content,
            fg_color=self.PALETTE["input_bg"],
            corner_radius=20,
            border_width=1,
            border_color=self.PALETTE["border_subtle"],
        )
        badge.pack(anchor="w", pady=(0, 24))

        badge_lbl = ctk.CTkLabel(
            badge,
            text="AUTHORIZED SECURITY INTERFACE",
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["text_dim"],
            padx=16,
            pady=6,
        )
        badge_lbl.pack()

        # 2. Brand Block (Logo + Title)
        brand_wrap = ctk.CTkFrame(content, fg_color="transparent")
        brand_wrap.pack(fill="x", anchor="w")

        logo_img = self._load_logo_image()
        if logo_img:
            logo_lbl = ctk.CTkLabel(brand_wrap, image=logo_img, text="")
            logo_lbl.pack(side="left", padx=(0, 20))

        title_stack = ctk.CTkFrame(brand_wrap, fg_color="transparent")
        title_stack.pack(side="left")

        sys_lbl = ctk.CTkLabel(
            title_stack,
            text=self.branding["system_name"].upper(),
            font=("Bahnschrift SemiBold", 38),
            text_color=self.PALETTE["text_main"],
        )
        sys_lbl.pack(anchor="w")

        comp_lbl = ctk.CTkLabel(
            title_stack,
            text=self.branding["company_name"],
            font=("Segoe UI", 15),
            text_color=self.PALETTE["text_muted"],
        )
        comp_lbl.pack(anchor="w", pady=(2, 0))

        # 3. Decorative Divider
        divider = ctk.CTkFrame(content, fg_color=self.PALETTE["accent"], height=2, width=80, corner_radius=10)
        divider.pack(anchor="w", pady=(28, 28))

        # 4. Mission Statement
        mission = ctk.CTkLabel(
            content,
            text=(
                "A high-security behavior monitoring portal designed for institutional "
                "surveillance and real-time contraband detection. Powered by advanced "
                "pose estimation and predictive vision analytics."
            ),
            font=("Segoe UI", 16),
            text_color=self.PALETTE["text_dim"],
            justify="left",
            wraplength=480,
        )
        mission.pack(anchor="w")

        # 5. Technology Tags
        tags = ["MoveNet Engine", "YOLO26s Vision", "Secure Audit Log"]
        tag_row = ctk.CTkFrame(content, fg_color="transparent")
        tag_row.pack(anchor="w", pady=(32, 0))

        for t in tags:
            tag_card = ctk.CTkFrame(
                tag_row,
                fg_color=self.PALETTE["card_bg"],
                corner_radius=12,
                border_width=1,
                border_color=self.PALETTE["border_subtle"],
            )
            tag_card.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                tag_card,
                text=t,
                font=("Segoe UI Semibold", 10),
                text_color=self.PALETTE["text_muted"],
                padx=12,
                pady=5,
            ).pack()

    def _create_right_panel(self):
        # The Login Panel: Centered authentication card with top-right theme switch
        right = ctk.CTkFrame(self, fg_color=self.PALETTE["page_bg"], corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")

        # Institutional Theme Toggle Button (Light/Dark Mode) with Icon
        self.theme_icon = utils.create_theme_icon(size=(16, 16))
        self.btn_theme_toggle = ctk.CTkButton(
            right,
            text=self._get_theme_toggle_text(),
            image=self.theme_icon,
            compound="left",
            width=128,
            height=34,
            corner_radius=17,
            fg_color=self.PALETTE["btn_secondary"],
            hover_color=self.PALETTE["btn_secondary_hover"],
            text_color=self.PALETTE["text_dim"],
            font=("Segoe UI Semibold", 11),
            command=self.toggle_appearance_mode,
        )
        self.btn_theme_toggle.place(relx=1.0, rely=0.0, anchor="ne", x=-28, y=24)


        # Center the card
        card_wrap = ctk.CTkFrame(right, fg_color="transparent")
        card_wrap.place(relx=0.5, rely=0.5, anchor="center")

        login_card = ctk.CTkFrame(
            card_wrap,
            width=430,
            fg_color=self.PALETTE["card_bg"],
            corner_radius=14,
            border_width=1,
            border_color=self.PALETTE["card_border"],
        )
        login_card.pack()

        inner = ctk.CTkFrame(login_card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=42, pady=40)

        # Header
        eyebrow = ctk.CTkLabel(
            inner,
            text="SECURE LOGIN",
            font=("Segoe UI Bold", 11),
            text_color=self.PALETTE["accent"],
        )
        eyebrow.pack(anchor="w")

        heading = ctk.CTkLabel(
            inner,
            text="Operator Access",
            font=("Bahnschrift SemiBold", 28),
            text_color=self.PALETTE["text_main"],
        )
        heading.pack(anchor="w", pady=(6, 4))

        subheading = ctk.CTkLabel(
            inner,
            text="Provide authorized operator credentials.",
            font=("Segoe UI", 13),
            text_color=self.PALETTE["text_muted"],
        )
        subheading.pack(anchor="w", pady=(0, 24))

        # Field 1: Operator ID
        lbl_user = ctk.CTkLabel(
            inner,
            text="Operator ID",
            font=("Segoe UI Semibold", 12),
            text_color=self.PALETTE["text_dim"],
            anchor="w",
        )
        lbl_user.pack(fill="x", pady=(0, 6))

        self.entry_user = ctk.CTkEntry(
            inner,
            height=44,
            corner_radius=8,
            fg_color=self.PALETTE["input_bg"],
            border_width=1,
            border_color=self.PALETTE["border_subtle"],
            text_color=self.PALETTE["text_main"],
            placeholder_text="Enter ID",
            placeholder_text_color=self.PALETTE["text_muted"],
            font=("Segoe UI", 14),
        )
        self.entry_user.pack(fill="x", pady=(0, 18))
        self.entry_user.bind("<FocusIn>", lambda e: self.entry_user.configure(border_color=self.PALETTE["border_active"]))
        self.entry_user.bind("<FocusOut>", lambda e: self.entry_user.configure(border_color=self.PALETTE["border_subtle"]))
        self.entry_user.bind("<Return>", self._on_user_enter)
        self.entry_user.bind("<Key>", self.check_caps_lock)

        # Field 2: Security Key with Visibility Toggle
        lbl_pass = ctk.CTkLabel(
            inner,
            text="Security Key",
            font=("Segoe UI Semibold", 12),
            text_color=self.PALETTE["text_dim"],
            anchor="w",
        )
        lbl_pass.pack(fill="x", pady=(0, 6))

        pass_row = ctk.CTkFrame(inner, fg_color="transparent")
        pass_row.pack(fill="x")

        self.entry_pass = ctk.CTkEntry(
            pass_row,
            height=44,
            corner_radius=8,
            fg_color=self.PALETTE["input_bg"],
            border_width=1,
            border_color=self.PALETTE["border_subtle"],
            text_color=self.PALETTE["text_main"],
            placeholder_text="Enter Key",
            placeholder_text_color=self.PALETTE["text_muted"],
            font=("Segoe UI", 14),
            show="*",
        )
        self.entry_pass.pack(side="left", fill="x", expand=True)
        self.entry_pass.bind("<FocusIn>", self._on_pass_focus_in)
        self.entry_pass.bind("<FocusOut>", self._on_pass_focus_out)
        self.entry_pass.bind("<Return>", self._on_pass_enter)
        self.entry_pass.bind("<Key>", self.check_caps_lock)

        self.btn_show_pass = ctk.CTkButton(
            pass_row,
            width=58,
            height=44,
            corner_radius=8,
            text="Show",
            font=("Segoe UI Semibold", 11),
            fg_color=self.PALETTE["btn_secondary"],
            hover_color=self.PALETTE["btn_secondary_hover"],
            text_color=self.PALETTE["text_dim"],
            command=self.toggle_password_visibility,
        )
        self.btn_show_pass.pack(side="left", padx=(6, 0))

        # Caps Lock Warning Indicator (Zero CLS - pre-allocated subtle slot)
        self.caps_warning = ctk.CTkLabel(
            inner,
            text="",
            font=("Segoe UI Semibold", 11),
            text_color=self.PALETTE["warning"],
            anchor="w",
            height=16,
        )
        self.caps_warning.pack(fill="x", pady=(4, 0))

        # Status Message Container (Zero CLS: fixed height reservation prevents jumping)
        self.status_container = ctk.CTkFrame(inner, height=34, fg_color="transparent")
        self.status_container.pack(fill="x", pady=(4, 14))
        self.status_container.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            self.status_container,
            text="",
            font=("Segoe UI", 12),
            text_color=self.PALETTE["danger"],
            anchor="w",
            justify="left",
            wraplength=330,
        )
        self.status_label.pack(fill="both", expand=True)

        # Sign In Button
        self.btn_login = ctk.CTkButton(
            inner,
            text="SIGN IN TO SYSTEM",
            height=48,
            corner_radius=10,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            text_color=("#ffffff", "#ffffff"),
            font=("Segoe UI Bold", 13),
            command=self.login_event,
        )
        self.btn_login.pack(fill="x")

        footer = ctk.CTkLabel(
            inner,
            text="This session is restricted and audited.",
            font=("Segoe UI", 10),
            text_color=self.PALETTE["text_muted"],
        )
        footer.pack(pady=(18, 0))

        # Direct, true focus on the entry widget after render
        self.after(60, self.entry_user.focus_set)

    def _get_theme_toggle_text(self):
        mode = ctk.get_appearance_mode()
        return " Dark Mode" if mode == "Dark" else " Light Mode"

    def toggle_appearance_mode(self):
        current = ctk.get_appearance_mode()
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        profile_store.set_appearance_mode(new_mode)
        utils.update_ttk_theme(mode=new_mode)
        self.btn_theme_toggle.configure(text=self._get_theme_toggle_text(), image=self.theme_icon)


    def toggle_password_visibility(self):
        self._password_masked = not self._password_masked
        if self._password_masked:
            self.entry_pass.configure(show="*")
            self.btn_show_pass.configure(text="Show")
        else:
            self.entry_pass.configure(show="")
            self.btn_show_pass.configure(text="Hide")

    def check_caps_lock(self, _event=None):
        if _is_caps_lock_on():
            self.caps_warning.configure(text="⚠ CAPS LOCK IS ON")
        else:
            self.caps_warning.configure(text="")

    def _on_pass_focus_in(self, _event):
        self.entry_pass.configure(border_color=self.PALETTE["border_active"])
        self.check_caps_lock()

    def _on_pass_focus_out(self, _event):
        self.entry_pass.configure(border_color=self.PALETTE["border_subtle"])
        self.caps_warning.configure(text="")

    def _load_logo_image(self):
        logo_path = self.branding.get("logo_abspath")
        if not logo_path or not os.path.exists(logo_path):
            return None
        try:
            image = Image.open(logo_path)
            return ctk.CTkImage(light_image=image, dark_image=image, size=(68, 68))
        except Exception:
            return None

    def _set_status(self, message, is_error=True):
        color = self.PALETTE["danger"] if is_error else self.PALETTE["success"]
        self.status_label.configure(text=message, text_color=color)

    def _on_user_enter(self, _event):
        if self.entry_user.get().strip():
            self.entry_pass.focus_set()
        else:
            self.login_event()

    def _on_pass_enter(self, _event):
        self.login_event()

    def login_event(self):
        username = self.entry_user.get().strip()
        password = self.entry_pass.get()

        self._set_status("", is_error=False)

        if not username:
            self._set_status("Operator ID is required.")
            self.entry_user.focus_set()
            return

        if not password:
            self._set_status("Security Key is required.")
            self.entry_pass.focus_set()
            return

        # Tactile busy state to prevent double-clicks
        self.btn_login.configure(state="disabled", text="VERIFYING...")
        self.update_idletasks()

        user, error_message = profile_store.authenticate_user(username, password)
        if user:
            self.btn_login.configure(text="VERIFIED - CONNECTING...")
            self._set_status("Establishing secure link...", is_error=False)
            self.after(400, lambda: self.on_login_success(user))
            return

        self.btn_login.configure(state="normal", text="SIGN IN TO SYSTEM")
        self.entry_pass.delete(0, "end")
        self.entry_pass.focus_set()
        self._set_status(error_message or "Access Denied.")
