import tkinter as tk
from tkinter import ttk
import sys
import os

import customtkinter as ctk

os.environ.pop("TCL_LIBRARY", None)
os.environ.pop("TK_LIBRARY", None)

# Add project root to path to ensure imports work correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- OPTIONAL FIX FOR CUSTOM TKINTER INSTALLATIONS ---
try:
    # We look for Tcl/Tk relative to the executable
    base_python = os.path.dirname(sys.executable)
    
    # 1. Try to find TCL
    tcl_path = None
    possible_tcl = [
        os.path.join(base_python, "tcl", "tcl8.6"),
        os.path.join(base_python, "Lib", "tcl8.6"),
    ]
    for p in possible_tcl:
        if os.path.exists(os.path.join(p, "init.tcl")):
            tcl_path = p
            break
            
    # 2. Try to find TK
    tk_path = None
    possible_tk = [
        os.path.join(base_python, "tcl", "tk8.6"),
        os.path.join(base_python, "Lib", "tk8.6"),
    ]
    for p in possible_tk:
        if os.path.exists(os.path.join(p, "tk.tcl")):
            tk_path = p
            break

    if tcl_path:
        os.environ["TCL_LIBRARY"] = tcl_path
        # print(f"Applied TCL_LIBRARY: {tcl_path}")
    if tk_path:
        os.environ["TK_LIBRARY"] = tk_path
        # print(f"Applied TK_LIBRARY: {tk_path}")

except Exception as e:
    print(f"Warning: Could not auto-fix Tkinter paths: {e}")
# ------------------------------------------------------

from monitor_app import utils, auth, camera_view, incidents, dashboard, settings, reports
from monitor_app import profile_store

class CellWatchApp(ctk.CTk):
    NAV_PALETTE = {
        "bar": "#111821",
        "bar_border": "#243648",
        "button": "#18212b",
        "button_hover": "#213244",
        "active": "#4f84bb",
        "active_hover": "#426f9b",
        "text": "#f3f7fb",
        "muted": "#8da1b4",
        "warn": "#8e5a5a",
        "warn_hover": "#a46363",
    }

    def __init__(self):
        super().__init__()
        profile_store.ensure_app_state()
        self.app_profile = profile_store.get_app_profile()
        
        # Start Health Monitor watchdog
        from monitor_app.health import get_health_monitor
        get_health_monitor().start()

        self.title(self.app_profile["system_name"])
        self.geometry(utils.WINDOW_SIZE)
        self.configure(bg=self.NAV_PALETTE["bar"])
        self.attributes("-alpha", 1.0) # Ensure window is 100% opaque
        
        # Apply theme
        self.style = utils.apply_dark_theme(self)
        
        # Placeholder for current user
        self.current_user = None
        self.current_screen = None
        self.nav_buttons = {}
        
        # Main container for all screens
        self.container = tk.Frame(self, bg=utils.COLOR_BG_DARK)
        self.container.pack(fill="both", expand=True)
        
        # Navigation bar (initially hidden, shown after login)
        self.nav_bar = None
        
        # Initialize
        self.show_login()

    def show_login(self):
        # Clear container
        for widget in self.container.winfo_children():
            widget.destroy()
            
        if self.nav_bar:
            self.nav_bar.destroy()
            self.nav_bar = None
            
        self.refresh_branding(rebuild_nav=False)
        login_screen = auth.LoginScreen(self.container, on_login_success=self.on_login_success)
        login_screen.pack(fill="both", expand=True)

    def on_login_success(self, user):
        self.current_user = user
        self.refresh_branding(rebuild_nav=False)
        self.create_navigation()
        self.show_dashboard_placeholder() # Temporarily show a placeholder until dashboard is built

    def create_navigation(self):
        self.refresh_branding(rebuild_nav=False)
        self.nav_buttons = {}
        self.nav_bar = ctk.CTkFrame(
            self,
            fg_color=self.NAV_PALETTE["bar"],
            corner_radius=0,
            height=84,
            border_width=0,
        )
        self.nav_bar.pack(side="top", fill="x", before=self.container)
        self.nav_bar.pack_propagate(False)
        
        brand = ctk.CTkFrame(self.nav_bar, fg_color="transparent")
        brand.pack(side="left", padx=20, pady=14)

        from PIL import Image
        try:
            logo_path = self.app_profile.get("logo_abspath")
            if logo_path and os.path.exists(logo_path):
                logo_img = Image.open(logo_path)
                self.logo_photo = ctk.CTkImage(light_image=logo_img, dark_image=logo_img, size=(34, 34))
                lbl_logo = ctk.CTkLabel(brand, image=self.logo_photo, text="")
                lbl_logo.pack(side="left", padx=(0, 12))
        except Exception as e:
            print(f"Could not load nav logo: {e}")

        title_wrap = ctk.CTkFrame(brand, fg_color="transparent")
        title_wrap.pack(side="left")

        lbl_title = ctk.CTkLabel(
            title_wrap,
            text=self.app_profile["system_name"].upper(),
            font=("Bahnschrift SemiBold", 22),
            text_color=self.NAV_PALETTE["text"],
            anchor="w",
        )
        lbl_title.pack(anchor="w")

        lbl_subtitle = ctk.CTkLabel(
            title_wrap,
            text=self.app_profile["company_name"],
            font=("Segoe UI", 11),
            text_color=self.NAV_PALETTE["muted"],
            anchor="w",
        )
        lbl_subtitle.pack(anchor="w", pady=(2, 0))

        btn_frame = ctk.CTkFrame(self.nav_bar, fg_color="transparent")
        btn_frame.pack(side="right", padx=18, pady=18)

        primary_buttons = [
            ("Dashboard", "Dashboard", 122),
            ("Live Monitor", "Live Monitor", 122),
            ("Incidents", "Incidents", 122),
            ("Reports", "Reports", 122),
            ("Settings", "Settings", 122),
            ("Profile Settings", "Profile Settings", 146),
        ]

        for text, screen_name, width in primary_buttons:
            btn = ctk.CTkButton(
                btn_frame,
                text=text,
                width=width,
                height=40,
                corner_radius=12,
                fg_color=self.NAV_PALETTE["button"],
                hover_color=self.NAV_PALETTE["button_hover"],
                text_color=self.NAV_PALETTE["text"],
                font=("Segoe UI Semibold", 12),
                command=lambda name=screen_name: self.switch_screen(name),
            )
            btn.pack(side="left", padx=(0, 10))
            self.nav_buttons[screen_name] = btn

        logout_btn = ctk.CTkButton(
            btn_frame,
            text="Logout",
            width=96,
            height=40,
            corner_radius=12,
            fg_color="#2a1b1f",
            hover_color=self.NAV_PALETTE["warn_hover"],
            text_color=self.NAV_PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self.logout,
        )
        logout_btn.pack(side="left")

        divider = ctk.CTkFrame(
            self.nav_bar,
            fg_color=self.NAV_PALETTE["bar_border"],
            height=1,
            corner_radius=0,
        )
        divider.pack(side="bottom", fill="x")

    def _set_active_nav(self, screen_name):
        for name, button in self.nav_buttons.items():
            if name == screen_name:
                button.configure(
                    fg_color=self.NAV_PALETTE["active"],
                    hover_color=self.NAV_PALETTE["active_hover"],
                    text_color=self.NAV_PALETTE["text"],
                )
            else:
                button.configure(
                    fg_color=self.NAV_PALETTE["button"],
                    hover_color=self.NAV_PALETTE["button_hover"],
                    text_color=self.NAV_PALETTE["text"],
                )

    def switch_screen(self, screen_name):
        # Clear current screen
        for widget in self.container.winfo_children():
            # If it has a 'stop_monitoring' method, call it (for camera view)
            if hasattr(widget, 'stop_monitoring'):
                widget.stop_monitoring()
            widget.destroy()
            
        # Initialize new screen
        if screen_name == "Live Monitor":
            screen = camera_view.CameraMonitorScreen(self.container)
            screen.start_monitoring()
        elif screen_name == "Incidents":
            screen = incidents.IncidentsScreen(
                self.container,
                current_user=profile_store.get_display_name(self.current_user),
            )
        elif screen_name == "Dashboard":
            screen = dashboard.DashboardScreen(self.container)
        elif screen_name == "Settings":
            screen = settings.SettingsScreen(
                self.container,
                current_user=self.current_user,
                on_profile_updated=self.refresh_branding,
                mode="monitoring",
            )
        elif screen_name == "Profile Settings":
            screen = settings.SettingsScreen(
                self.container,
                current_user=self.current_user,
                on_profile_updated=self.refresh_branding,
                mode="profile",
            )
        elif screen_name == "Reports":
            # Reports not yet implemented, create placeholder module/class or use fallback
            if 'monitor_app.reports' in sys.modules:
               screen = reports.ReportsScreen(self.container)
            else:
               # Placeholder logic handled by 'else' block below if reports.py doesn't exist
               # check if we can import it
               try:
                   import monitor_app.reports as rpt
                   screen = rpt.ReportsScreen(self.container)
               except:
                   lbl = ttk.Label(self.container, text=f"{screen_name} Screen (Under Construction)", style="Header.TLabel")
                   lbl.place(relx=0.5, rely=0.5, anchor="center")
                   return

        self.current_screen = screen_name
        self._set_active_nav(screen_name)

    def refresh_branding(self, rebuild_nav=True):
        self.app_profile = profile_store.get_app_profile()
        self.title(self.app_profile["system_name"])

        if rebuild_nav and self.nav_bar:
            self.nav_bar.destroy()
            self.nav_bar = None
            self.create_navigation()
            if self.current_screen:
                self._set_active_nav(self.current_screen)

    def show_dashboard_placeholder(self):
        self.switch_screen("Dashboard")

    def logout(self):
        self.current_user = None
        self.show_login()

    def destroy(self):
        try:
            from monitor_app.health import get_health_monitor
            get_health_monitor().stop()
        except:
            pass
        super().destroy()

if __name__ == "__main__":
    app = CellWatchApp()
    app.mainloop()
