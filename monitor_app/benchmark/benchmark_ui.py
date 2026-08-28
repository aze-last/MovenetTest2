import customtkinter as ctk
from monitor_app.telemetry.benchmark_center import ValidationCenterScreen


class BenchmarkDialog(ctk.CTkToplevel):
    """
    Toplevel dialog wrapper for the Validation & Benchmark Center.
    Launched from the CellWatch Tools dropdown or live monitor validation button.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title("Validation & Benchmark Center")
        self.geometry("1100x750")

        self.screen = ValidationCenterScreen(self)
        self.screen.pack(fill="both", expand=True)

        self.grab_set()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
