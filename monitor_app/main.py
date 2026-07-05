import tkinter as tk
from tkinter import ttk
import sys
import os

# Add project root to path to ensure imports work correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

if not getattr(sys, 'frozen', False):
    os.environ.pop("TCL_LIBRARY", None)
    os.environ.pop("TK_LIBRARY", None)

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

        # Initialize Alert Manager to subscribe to Decision events
        from monitor_app.alert_manager import get_alert_manager
        get_alert_manager()

        self.title(self.app_profile["system_name"])
        self.geometry(utils.WINDOW_SIZE)
        self.configure(bg=self.NAV_PALETTE["bar"])
        self.attributes("-alpha", 1.0) # Ensure window is 100% opaque
        
        # Apply theme
        self.style = utils.apply_dark_theme(self)
        
        # Start Telemetry Engine
        from monitor_app.telemetry import get_telemetry_engine
        get_telemetry_engine().start()
        
        # Start periodic telemetry event ticks
        self._schedule_telemetry_ticks()
        
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

        # ── Tools Dropdown ──
        self._tools_menu_open = False
        self._tools_popup = None

        tools_btn = ctk.CTkButton(
            btn_frame,
            text="Tools ▾",
            width=96,
            height=40,
            corner_radius=12,
            fg_color=self.NAV_PALETTE["button"],
            hover_color=self.NAV_PALETTE["button_hover"],
            text_color=self.NAV_PALETTE["text"],
            font=("Segoe UI Semibold", 12),
            command=self._toggle_tools_menu,
        )
        tools_btn.pack(side="left", padx=(0, 10))
        self._tools_btn = tools_btn

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

    # ── Tools Dropdown ──────────────────────────────────────────────────────
    def _toggle_tools_menu(self):
        if self._tools_popup and self._tools_popup.winfo_exists():
            self._tools_popup.destroy()
            self._tools_popup = None
            return

        # Use a borderless Toplevel so it floats above all widgets
        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.configure(fg_color="#15202c")
        popup.attributes("-topmost", True)

        # Position below the tools button
        btn = self._tools_btn
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height() + 4

        popup.geometry(f"+{x}+{y}")
        self._tools_popup = popup

        container = ctk.CTkFrame(popup, fg_color="#15202c", corner_radius=12,
                                  border_width=1, border_color="#2a3d52")
        container.pack(fill="both", expand=True, padx=1, pady=1)

        tools = [
            ("📊  Benchmark Center", self._launch_benchmark),
            ("🔍  Offline Analysis Center", self._launch_offline_analysis),
            ("🎬  Dataset Recorder", self._launch_dataset_recorder),
        ]
        for label, cmd in tools:
            ctk.CTkButton(
                container, text=label, anchor="w",
                font=("Segoe UI Semibold", 12),
                fg_color="transparent", hover_color="#1e3048",
                text_color="#f3f7fb", height=36, width=220, corner_radius=8,
                command=lambda c=cmd: self._run_tool(c),
            ).pack(fill="x", padx=6, pady=2)

        # Close when focus leaves the popup
        popup.bind("<FocusOut>", self._close_tools_menu_on_focus)
        popup.after(100, popup.focus_set)

    def _close_tools_menu_on_focus(self, event):
        if self._tools_popup and self._tools_popup.winfo_exists():
            # Small delay to allow button clicks to register first
            self._tools_popup.after(150, self._maybe_close_tools)

    def _maybe_close_tools(self):
        if self._tools_popup and self._tools_popup.winfo_exists():
            try:
                focused = self._tools_popup.focus_get()
                if focused is None or not str(focused).startswith(str(self._tools_popup)):
                    self._tools_popup.destroy()
                    self._tools_popup = None
            except Exception:
                self._tools_popup.destroy()
                self._tools_popup = None


    def _run_tool(self, launcher):
        if self._tools_popup and self._tools_popup.winfo_exists():
            self._tools_popup.destroy()
            self._tools_popup = None
        launcher()

    def _launch_dataset_recorder(self):
        from monitor_app.dataset_recorder import DatasetRecorderDialog
        DatasetRecorderDialog(self)

    def _launch_offline_analysis(self):
        try:
            from monitor_app.offline_ui import OfflineAnalysisCenterDialog
            OfflineAnalysisCenterDialog(self)
        except Exception as e:
            print(f"Could not launch Offline Analysis: {e}")

    def _launch_benchmark(self):
        try:
            from monitor_app.benchmark.benchmark_ui import BenchmarkDialog
            BenchmarkDialog(self)
        except Exception as e:
            print(f"Could not launch Benchmark: {e}")

    def _schedule_telemetry_ticks(self):
        """Periodically emits telemetry ticks on the event bus while the app is running."""
        try:
            from monitor_app.events import get_event_bus, TELEM_SYSTEM_TICK, TELEM_QUEUE_TICK
            from monitor_app.central_inference import get_inference_manager
            
            bus = get_event_bus()
            bus.publish(TELEM_SYSTEM_TICK, TELEM_SYSTEM_TICK, {})
            bus.publish(TELEM_QUEUE_TICK, TELEM_QUEUE_TICK, {
                "queue_size": get_inference_manager().task_queue.qsize()
            })
        except Exception:
            pass
            
        # Schedule next tick in 1000ms
        self.after(1000, self._schedule_telemetry_ticks)

    def destroy(self):
        try:
            from monitor_app.health import get_health_monitor
            get_health_monitor().stop()
        except:
            pass
        try:
            from monitor_app.telemetry import get_telemetry_engine
            get_telemetry_engine().stop()
        except:
            pass
        super().destroy()

if __name__ == "__main__":
    app = CellWatchApp()
    app.mainloop()
