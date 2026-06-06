from datetime import datetime
import os
import sqlite3
import socket
import time
from tkinter import ttk

import customtkinter as ctk
import psutil

import monitor_app.utils as utils

class DashboardScreen(ctk.CTkFrame):
    PALETTE = {
        "page": "#06090c",           # Deep base
        "panel": "#0f161f",          # Main panel background
        "card": "#151f2b",           # Widget card background
        "border": "#1e2c3a",         # Subtle borders
        "accent": "#4f84bb",         # Primary brand color
        "accent_glow": "#3e709e",    # Subdued accent
        "text_main": "#ffffff",
        "text_dim": "#a2b5c7",
        "text_muted": "#637a91",
        "success": "#50d186",
        "warning": "#f2c94c",
        "danger": "#f25c5c",
    }

    def __init__(self, parent):
        super().__init__(parent, fg_color=self.PALETTE["page"])
        self.pack(fill="both", expand=True)

        self.metric_cards = {}
        self.health_widgets = {}
        self.summary_values = {}
        self.lbl_sync_value = None
        self.lbl_header_state = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.main_view = ctk.CTkScrollableFrame(
            self,
            fg_color=self.PALETTE["page"],
            corner_radius=0,
            scrollbar_button_color=self.PALETTE["card"],
            scrollbar_button_hover_color=self.PALETTE["accent"],
        )
        self.main_view.grid(row=0, column=0, sticky="nsew")
        self.main_view.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.create_dashboard_content()
        self.update_system_health()
        self.update_dashboard_metrics()

    def create_dashboard_content(self):
        self._build_header()
        self._build_metric_cards()
        self._build_main_panels()

    def _build_header(self):
        header = ctk.CTkFrame(self.main_view, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", padx=30, pady=(30, 20))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_box,
            text="COMMAND CENTER",
            font=("Segoe UI Bold", 11),
            text_color=self.PALETTE["accent"],
            anchor="w"
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="Operational Status",
            font=("Bahnschrift SemiBold", 32),
            text_color=self.PALETTE["text_main"],
            anchor="w"
        ).pack(anchor="w", pady=(4, 0))

        status_box = ctk.CTkFrame(header, fg_color="transparent")
        status_box.grid(row=0, column=1, sticky="e")

        self.lbl_header_state = ctk.CTkLabel(
            status_box,
            text="SYSTEM READY",
            font=("Segoe UI Bold", 12),
            text_color=self.PALETTE["success"],
            fg_color=self.PALETTE["panel"],
            corner_radius=8,
            padx=16,
            pady=6
        )
        self.lbl_header_state.pack(anchor="e")

        self.lbl_sync_value = ctk.CTkLabel(
            status_box,
            text="Last Probe: --:--:--",
            font=("Segoe UI Semibold", 12),
            text_color=self.PALETTE["text_muted"],
            anchor="e"
        )
        self.lbl_sync_value.pack(anchor="e", pady=(8, 0))

    def _build_metric_cards(self):
        # 4 High-Signal Data Tiles
        cards = [
            ("Active Feeds", "active_cams", self.PALETTE["accent"]),
            ("Incidents", "total_detections", self.PALETTE["warning"]),
            ("Live Alerts", "active_alerts", self.PALETTE["danger"]),
            ("System Uptime", "uptime", self.PALETTE["success"]),
        ]

        for i, (title, key, accent) in enumerate(cards):
            card = ctk.CTkFrame(
                self.main_view,
                fg_color=self.PALETTE["card"],
                corner_radius=16,
                border_width=1,
                border_color=self.PALETTE["border"],
                height=140
            )
            card.grid(row=1, column=i, sticky="nsew", padx=8, pady=(0, 24))
            card.grid_propagate(False)

            # Glow line at bottom
            glow = ctk.CTkFrame(card, fg_color=accent, height=3, corner_radius=10)
            glow.pack(side="bottom", fill="x", padx=15, pady=(0, 12))

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=20, pady=20)

            ctk.CTkLabel(
                inner,
                text=title.upper(),
                font=("Segoe UI Bold", 10),
                text_color=self.PALETTE["text_muted"],
                anchor="w"
            ).pack(anchor="w")

            val_lbl = ctk.CTkLabel(
                inner,
                text="0",
                font=("Bahnschrift SemiBold", 36),
                text_color=self.PALETTE["text_main"],
                anchor="w"
            )
            val_lbl.pack(anchor="w", pady=(8, 0))

            self.metric_cards[title] = {"value": val_lbl, "accent": accent}

    def _build_main_panels(self):
        # 2/3 Grid Layout
        container = ctk.CTkFrame(self.main_view, fg_color="transparent")
        container.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=30, pady=(0, 30))
        container.grid_columnconfigure(0, weight=2) # Health (Left)
        container.grid_columnconfigure(1, weight=1) # Ledger (Right)

        # 1. Health Matrix (Left)
        health_box = ctk.CTkFrame(
            container,
            fg_color=self.PALETTE["panel"],
            corner_radius=20,
            border_width=1,
            border_color=self.PALETTE["border"]
        )
        health_box.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        
        lbl_h = ctk.CTkLabel(
            health_box,
            text="System Vitals",
            font=("Bahnschrift SemiBold", 22),
            text_color=self.PALETTE["text_main"]
        )
        lbl_h.pack(anchor="w", padx=25, pady=(25, 20))

        # 2x2 Grid for metrics
        grid = ctk.CTkFrame(health_box, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=20, pady=(0, 25))
        grid.grid_columnconfigure((0, 1), weight=1)
        grid.grid_rowconfigure((0, 1), weight=1)

        vitals = [
            ("cpu", "Processor", "CPU Load"),
            ("memory", "Memory", "RAM Usage"),
            ("storage", "Disk", "Storage"),
            ("network", "Net", "Latency")
        ]

        for i, (key, title, subtitle) in enumerate(vitals):
            r, c = i // 2, i % 2
            cell = self._create_vitals_tile(grid, title, subtitle)
            cell.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
            self.health_widgets[key] = cell.refs

        # 2. Live Ledger (Right)
        ledger_box = ctk.CTkFrame(
            container,
            fg_color=self.PALETTE["panel"],
            corner_radius=20,
            border_width=1,
            border_color=self.PALETTE["border"]
        )
        ledger_box.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        ctk.CTkLabel(
            ledger_box,
            text="Activity Ledger",
            font=("Bahnschrift SemiBold", 22),
            text_color=self.PALETTE["text_main"]
        ) .pack(anchor="w", padx=25, pady=(25, 10))

        self.ledger_list = ctk.CTkFrame(ledger_box, fg_color="transparent")
        self.ledger_list.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        # Summary Placeholder lines
        for label in ("Network", "Archive", "Queue", "Latest"):
            row = ctk.CTkFrame(self.ledger_list, fg_color="transparent", height=45)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            
            ctk.CTkLabel(row, text=label, font=("Segoe UI", 12), text_color=self.PALETTE["text_muted"]).pack(side="left")
            val = ctk.CTkLabel(row, text="--", font=("Segoe UI Semibold", 12), text_color=self.PALETTE["text_dim"])
            val.pack(side="right")
            self.summary_values[label] = val

    def _create_vitals_tile(self, parent, title, subtitle):
        tile = ctk.CTkFrame(
            parent,
            fg_color=self.PALETTE["card"],
            corner_radius=12,
            border_width=1,
            border_color=self.PALETTE["border"]
        )
        
        inner = ctk.CTkFrame(tile, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)
        
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        
        ctk.CTkLabel(top, text=title, font=("Segoe UI Bold", 13), text_color=self.PALETTE["text_dim"]).pack(side="left")
        val_lbl = ctk.CTkLabel(top, text="--", font=("Segoe UI Bold", 15), text_color=self.PALETTE["accent"])
        val_lbl.pack(side="right")
        
        bar = ctk.CTkProgressBar(
            inner,
            height=6,
            corner_radius=10,
            progress_color=self.PALETTE["accent"],
            fg_color=self.PALETTE["page"]
        )
        bar.pack(fill="x", pady=(12, 10))
        bar.set(0)
        
        state_lbl = ctk.CTkLabel(inner, text="Waiting...", font=("Segoe UI", 10), text_color=self.PALETTE["text_muted"])
        state_lbl.pack(anchor="w")
        
        tile.refs = {"value": val_lbl, "progress": bar, "state": state_lbl}
        return tile

    def update_system_health(self):
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage(self._get_system_root()).percent
            latency = self._measure_latency_ms()

            self._upd_vit("cpu", cpu, f"{cpu:.0f}%", *self._h_state(cpu))
            self._upd_vit("memory", mem, f"{mem:.0f}%", *self._h_state(mem))
            self._upd_vit("storage", disk, f"{disk:.0f}% Used", *self._h_state(disk))
            
            if latency:
                self._upd_vit("network", min(latency/2, 100), f"{latency:.0f}ms", *self._lat_state(latency))
            else:
                self._upd_vit("network", 0, "OFFLINE", "Offline", self.PALETTE["danger"])

            if self.lbl_sync_value:
                self.lbl_sync_value.configure(text=f"Last Probe: {datetime.now().strftime('%H:%M:%S')}")
        except: pass
        self.after(2000, self.update_system_health)

    def _upd_vit(self, key, perc, val_txt, state_txt, color):
        w = self.health_widgets.get(key)
        if w:
            w["value"].configure(text=val_txt, text_color=color)
            w["progress"].configure(progress_color=color)
            w["progress"].set(perc/100)
            w["state"].configure(text=state_txt.upper(), text_color=color)

    def update_dashboard_metrics(self):
        try:
            m = utils.GlobalState.get_metrics()
            s = self._read_snapshot()

            self.metric_cards["Active Feeds"]["value"].configure(text=str(m["active_cams"]))
            self.metric_cards["Incidents"]["value"].configure(text=str(s["total"]))
            self.metric_cards["Live Alerts"]["value"].configure(text=str(m["active_alerts"]))
            
            uptime = int(time.time() - utils.GlobalState.start_time)
            self.metric_cards["System Uptime"]["value"].configure(text=f"{uptime//60}m")

            self.summary_values["Network"].configure(text=f"{m['active_cams']} active")
            self.summary_values["Archive"].configure(text=f"{s['total']} events")
            self.summary_values["Queue"].configure(text=f"{s['pending']} new")
            self.summary_values["Latest"].configure(text=s["latest"])
        except: pass
        self.after(1000, self.update_dashboard_metrics)

    def _read_snapshot(self):
        snap = {"total": 0, "pending": 0, "latest": "None"}
        if not os.path.exists("incidents.db"): return snap
        try:
            with sqlite3.connect("incidents.db") as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM incidents")
                snap["total"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM incidents WHERE review_status='PENDING'")
                snap["pending"] = cur.fetchone()[0]
                cur.execute("SELECT event_type FROM incidents ORDER BY timestamp_start DESC LIMIT 1")
                res = cur.fetchone()
                if res: snap["latest"] = res[0]
        except: pass
        return snap

    def _h_state(self, v):
        if v < 60: return "Nominal", self.PALETTE["success"]
        if v < 85: return "Elevated", self.PALETTE["warning"]
        return "Critical", self.PALETTE["danger"]

    def _lat_state(self, ms):
        if ms < 70: return "Fast", self.PALETTE["success"]
        if ms < 150: return "Stable", self.PALETTE["warning"]
        return "Slow", self.PALETTE["danger"]

    def _get_system_root(self):
        return os.path.splitdrive(os.path.abspath(os.getcwd()))[0] + "\\"

    def _measure_latency_ms(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            start = time.time()
            s.sendto(b"", ("8.8.8.8", 53))
            s.recvfrom(512)
            return (time.time() - start) * 1000
        except: return None
        finally: s.close()
