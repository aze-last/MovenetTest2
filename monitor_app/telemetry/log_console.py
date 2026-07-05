import tkinter as tk
import customtkinter as ctk
from typing import Dict, List, Optional

class LogConsole(ctk.CTkFrame):
    """
    Filtered log viewing console component for displaying structured pipeline
    messages during live operations or benchmark playback.
    """
    PALETTE = {
        "bg": "#0f161f",
        "card": "#151f2b",
        "border": "#1e2c3a",
        "text": "#f3f7fb",
        "accent": "#4f84bb",
        "muted": "#8da1b4",
        "severity_info": "#50d186",
        "severity_warning": "#f2c94c",
        "severity_error": "#f25c5c",
    }

    def __init__(self, parent):
        super().__init__(parent, fg_color=self.PALETTE["bg"], border_width=1, border_color=self.PALETTE["border"])
        
        self.all_logs: List[dict] = []
        self.active_filters: List[str] = []
        
        self.setup_ui()

    def setup_ui(self):
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Filter Selection Bar
        filter_bar = ctk.CTkFrame(self, fg_color="transparent", height=40)
        filter_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        
        # Log Category Filters
        categories = ["SYSTEM", "CAMERA", "AI", "BEHAVIOR", "RECORDER", "DATABASE", "WARNING", "ERROR"]
        self.filter_buttons: Dict[str, ctk.CTkButton] = {}
        
        for idx, cat in enumerate(categories):
            btn = ctk.CTkButton(
                filter_bar,
                text=cat,
                width=80,
                height=26,
                corner_radius=6,
                fg_color=self.PALETTE["card"],
                hover_color=self.PALETTE["border"],
                text_color=self.PALETTE["text"],
                font=("Segoe UI Semibold", 10),
                command=lambda c=cat: self.toggle_filter(c)
            )
            btn.pack(side="left", padx=4)
            self.filter_buttons[cat] = btn

        # Clear Button
        btn_clear = ctk.CTkButton(
            filter_bar,
            text="Clear Logs",
            width=80,
            height=26,
            corner_radius=6,
            fg_color="#362226",
            hover_color="#513036",
            text_color=self.PALETTE["text"],
            font=("Segoe UI Semibold", 10),
            command=self.clear_logs
        )
        btn_clear.pack(side="right", padx=4)

        # 2. Text Terminal Box
        self.text_box = ctk.CTkTextbox(
            self,
            fg_color=self.PALETTE["card"],
            text_color=self.PALETTE["text"],
            font=("Consolas", 11),
            border_width=1,
            border_color=self.PALETTE["border"],
            corner_radius=8
        )
        self.text_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.text_box.configure(state="disabled")

    def toggle_filter(self, category: str):
        """Toggles active log categorisation filters."""
        if category in self.active_filters:
            self.active_filters.remove(category)
            self.filter_buttons[category].configure(fg_color=self.PALETTE["card"])
        else:
            self.active_filters.append(category)
            # Match coloring depending on warning/error/standard
            color = self.PALETTE["accent"]
            if category == "WARNING":
                color = self.PALETTE["severity_warning"]
            elif category == "ERROR":
                color = self.PALETTE["severity_error"]
            self.filter_buttons[category].configure(fg_color=color)
            
        self.refresh_console()

    def add_log_entry(self, timestamp: str, severity: str, category: str, module: str, message: str):
        """Appends a new log dictionary and updates the scrollable terminal."""
        entry = {
            "timestamp": timestamp,
            "severity": severity,
            "category": category,
            "module": module,
            "message": message
        }
        self.all_logs.append(entry)
        self.append_to_textbox(entry)

    def append_to_textbox(self, entry: dict):
        # Apply filters
        if self.active_filters:
            # Check category or severity level matches
            has_match = False
            for filt in self.active_filters:
                if filt in [entry["category"], entry["severity"]]:
                    has_match = True
                    break
            if not has_match:
                return

        self.text_box.configure(state="normal")
        
        # Color coding text based on severity
        line = f"[{entry['timestamp']}] {entry['severity']:<7} | {entry['category']:<8} | {entry['module']:<12} | {entry['message']}\n"
        self.text_box.insert("end", line)
        self.text_box.see("end")
        self.text_box.configure(state="disabled")

    def refresh_console(self):
        """Clears view and regenerates it according to current filters."""
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.configure(state="disabled")
        
        for entry in self.all_logs:
            self.append_to_textbox(entry)

    def clear_logs(self):
        self.all_logs.clear()
        self.refresh_console()
