import os
import customtkinter as ctk
from PIL import Image
from monitor_app import profile_store

ctk.set_appearance_mode("Dark")

class LoginScreen(ctk.CTkFrame):
    # Enhanced Institutional Dark Palette
    PALETTE = {
        "page_bg": "#06090c",         # Purest dark base
        "hero_bg": "#0a0e13",         # Left side hero panel
        "card_bg": "#121a24",         # Right side login card
        "input_bg": "#182330",        # Input field background
        "border_subtle": "#1e2c3a",   # Default border color
        "border_active": "#3e709e",   # Focus border glow color
        "accent": "#4f84bb",          # Primary action color
        "accent_hover": "#5c9ad6",    # Hover state for accent
        "text_main": "#ffffff",
        "text_dim": "#a2b5c7",
        "text_muted": "#637a91",
        "danger": "#f25c5c",
        "success": "#50d186",
    }

    def __init__(self, parent, on_login_success):
        super().__init__(parent, fg_color=self.PALETTE["page_bg"])
        self.on_login_success = on_login_success
        
        profile_store.ensure_app_state()
        self.branding = profile_store.get_branding()
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
            border_color=self.PALETTE["border_subtle"]
        )
        badge.pack(anchor="w", pady=(0, 24))
        
        badge_lbl = ctk.CTkLabel(
            badge, 
            text="AUTHORIZED SECURITY INTERFACE", 
            font=("Segoe UI Semibold", 11), 
            text_color=self.PALETTE["text_dim"], 
            padx=16, 
            pady=6
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
            text_color=self.PALETTE["text_main"]
        )
        sys_lbl.pack(anchor="w")
        
        comp_lbl = ctk.CTkLabel(
            title_stack, 
            text=self.branding["company_name"], 
            font=("Segoe UI", 15), 
            text_color=self.PALETTE["text_muted"]
        )
        comp_lbl.pack(anchor="w", pady=(2, 0))

        # 3. Decorative Divider
        divider = ctk.CTkFrame(content, fg_color=self.PALETTE["accent"], height=2, width=80, corner_radius=10)
        divider.pack(anchor="w", pady=(30, 30))

        # 4. Mission Statement
        mission = ctk.CTkLabel(
            content,
            text=(
                "A high-security behavior monitoring portal designed for institutional "
                "surveillance and real-time contraband detection. Powered by advanced "
                "pose estimation and predictive vision analytics."
            ),
            font=("Segoe UI", 18),
            text_color=self.PALETTE["text_dim"],
            justify="left",
            wraplength=480
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
                border_color=self.PALETTE["border_subtle"]
            )
            tag_card.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                tag_card, 
                text=t, 
                font=("Segoe UI Semibold", 10), 
                text_color=self.PALETTE["text_muted"], 
                padx=12, 
                pady=5
            ).pack()

    def _create_right_panel(self):
        # The Login Panel: Centered authentication card
        right = ctk.CTkFrame(self, fg_color=self.PALETTE["page_bg"], corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        # Center the card
        card_wrap = ctk.CTkFrame(right, fg_color="transparent")
        card_wrap.place(relx=0.5, rely=0.5, anchor="center")
        
        login_card = ctk.CTkFrame(
            card_wrap, 
            width=420, 
            fg_color=self.PALETTE["card_bg"], 
            corner_radius=24, 
            border_width=1, 
            border_color=self.PALETTE["border_subtle"]
        )
        login_card.pack()
        
        inner = ctk.CTkFrame(login_card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=44, pady=44)
        
        # Header
        eyebrow = ctk.CTkLabel(
            inner, 
            text="SECURE LOGIN", 
            font=("Segoe UI Bold", 11), 
            text_color=self.PALETTE["accent"]
        )
        eyebrow.pack(anchor="w")
        
        heading = ctk.CTkLabel(
            inner, 
            text="Operator Access", 
            font=("Bahnschrift SemiBold", 28), 
            text_color=self.PALETTE["text_main"]
        )
        heading.pack(anchor="w", pady=(8, 4))
        
        subheading = ctk.CTkLabel(
            inner, 
            text="Provide authorized operator credentials.", 
            font=("Segoe UI", 13), 
            text_color=self.PALETTE["text_muted"]
        )
        subheading.pack(anchor="w", pady=(0, 28))

        # Fields
        self.entry_user = self._create_input_field(inner, "Operator ID", "Enter ID")
        self.entry_user.pack(fill="x", pady=(0, 20))
        
        self.entry_pass = self._create_input_field(inner, "Security Key", "Enter Key", is_password=True)
        self.entry_pass.pack(fill="x", pady=(0, 10))

        # Status Message
        self.status_label = ctk.CTkLabel(
            inner, 
            text="", 
            font=("Segoe UI", 12), 
            text_color=self.PALETTE["danger"], 
            anchor="w", 
            justify="left", 
            wraplength=330
        )
        self.status_label.pack(fill="x", pady=(0, 20))

        # Sign In Button
        self.btn_login = ctk.CTkButton(
            inner,
            text="SIGN IN TO SYSTEM",
            height=48,
            corner_radius=12,
            fg_color=self.PALETTE["accent"],
            hover_color=self.PALETTE["accent_hover"],
            text_color=self.PALETTE["text_main"],
            font=("Segoe UI Bold", 14),
            command=self.login_event
        )
        self.btn_login.pack(fill="x")
        
        footer = ctk.CTkLabel(
            inner, 
            text="This session is restricted and audited.", 
            font=("Segoe UI", 10), 
            text_color=self.PALETTE["text_muted"]
        )
        footer.pack(pady=(20, 0))

        self.entry_user.focus_set()

    def _create_input_field(self, parent, label_text, placeholder, is_password=False):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        
        lbl = ctk.CTkLabel(
            f, 
            text=label_text, 
            font=("Segoe UI Semibold", 12), 
            text_color=self.PALETTE["text_dim"], 
            anchor="w"
        )
        lbl.pack(fill="x", pady=(0, 6))
        
        entry = ctk.CTkEntry(
            f,
            height=44,
            corner_radius=10,
            fg_color=self.PALETTE["input_bg"],
            border_width=1,
            border_color=self.PALETTE["border_subtle"],
            text_color=self.PALETTE["text_main"],
            placeholder_text=placeholder,
            placeholder_text_color=self.PALETTE["text_muted"],
            font=("Segoe UI", 15),
            show="*" if is_password else ""
        )
        entry.pack(fill="x")
        
        # Interactive Glow
        entry.bind("<FocusIn>", lambda e: entry.configure(border_color=self.PALETTE["border_active"]))
        entry.bind("<FocusOut>", lambda e: entry.configure(border_color=self.PALETTE["border_subtle"]))
        entry.bind("<Return>", self._on_enter_key)
        
        return f

    def _load_logo_image(self):
        logo_path = self.branding.get("logo_abspath")
        if not logo_path or not os.path.exists(logo_path):
            return None
        try:
            image = Image.open(logo_path)
            return ctk.CTkImage(light_image=image, dark_image=image, size=(56, 56))
        except Exception:
            return None

    def _set_status(self, message, is_error=True):
        color = self.PALETTE["danger"] if is_error else self.PALETTE["success"]
        self.status_label.configure(text=message, text_color=color)

    def _on_enter_key(self, _event):
        self.login_event()

    def login_event(self):
        username = self.entry_user.winfo_children()[1].get().strip() # child 0 is label, 1 is entry
        password = self.entry_pass.winfo_children()[1].get()

        self._set_status("", is_error=False)

        user, error_message = profile_store.authenticate_user(username, password)
        if user:
            self._set_status("Establishing secure link...", is_error=False)
            self.after(400, lambda: self.on_login_success(user))
            return

        self.entry_pass.winfo_children()[1].delete(0, "end")
        self.entry_pass.winfo_children()[1].focus_set()
        self._set_status(error_message or "Access Denied.")
