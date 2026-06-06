import tkinter as tk
from tkinter import ttk
import monitor_app.utils as utils
import datetime

class AlertPanel(tk.Toplevel):
    """
    A popup or sidebar window for alerts.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Active Alerts")
        self.geometry("300x500")
        self.configure(bg=utils.COLOR_BG_DARK)
        
        # Set list of alerts
        self.alerts = []
        
        ttk.Label(self, text="Recent Alerts", style="Header.TLabel").pack(pady=10)
        
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Add some dummy alerts
        self.add_alert("Camera 1", "Aggressive", "High")
        self.add_alert("Camera 3", "Contraband", "Critical")

    def add_alert(self, source, type_, severity):
        frame = ttk.Frame(self.list_frame, style="Card.TFrame")
        frame.pack(fill="x", pady=2)
        
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        header = ttk.Frame(frame, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=f"[{severity.upper()}] {time_str}", foreground=utils.COLOR_ALERT if severity == "Critical" else utils.COLOR_WARNING, style="Card.TLabel").pack(side="left")
        
        ttk.Label(frame, text=f"{source}: {type_}", style="Card.TLabel").pack(anchor="w")
