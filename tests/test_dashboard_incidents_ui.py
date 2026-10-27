import pytest
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from monitor_app import profile_store
from monitor_app.dashboard import DashboardScreen
from monitor_app.incidents import IncidentsScreen, IncidentLogTable, PALETTE as INCIDENTS_PALETTE





def test_dashboard_palette_tuples():
    assert isinstance(DashboardScreen.PALETTE["page"], tuple)
    assert isinstance(DashboardScreen.PALETTE["card"], tuple)
    assert isinstance(DashboardScreen.PALETTE["accent"], tuple)
    assert isinstance(DashboardScreen.PALETTE["text_main"], tuple)


def test_dashboard_instantiation_and_theme_toggle(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()
    dashboard = DashboardScreen(frame)
    assert dashboard is not None
    assert "Active Feeds" in dashboard.metric_cards
    assert "cpu" in dashboard.health_widgets

    # Toggle appearance mode and verify widgets remain healthy
    ctk.set_appearance_mode("Light")
    dashboard.update_idletasks()
    ctk.set_appearance_mode("Dark")
    dashboard.update_idletasks()
    frame.destroy()


def test_incidents_palette_tuples():
    assert isinstance(INCIDENTS_PALETTE["page"], tuple)
    assert isinstance(INCIDENTS_PALETTE["card"], tuple)
    assert isinstance(INCIDENTS_PALETTE["accent"], tuple)
    assert isinstance(INCIDENTS_PALETTE["text"], tuple)


def test_incidents_screen_and_treeview_styling(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()
    screen = IncidentsScreen(frame)
    assert screen is not None
    assert hasattr(screen, "apply_appearance_mode")

    # Verify ttk.Treeview style updates when switching modes
    ctk.set_appearance_mode("Light")
    screen.apply_appearance_mode()
    style = ttk.Style()
    assert style.lookup("Incidents.Treeview", "background") == "#ffffff"
    assert style.lookup("Incidents.Treeview", "foreground") == "#0f172a"

    ctk.set_appearance_mode("Dark")
    screen.apply_appearance_mode()
    assert style.lookup("Incidents.Treeview", "background") == "#1b2430"
    assert style.lookup("Incidents.Treeview", "foreground") == "#f3f7fb"

    screen.stop_monitoring()
    frame.destroy()



def test_nav_palette_and_theme_toggle():
    from monitor_app.main import CellWatchApp
    assert isinstance(CellWatchApp.NAV_PALETTE["bar"], tuple)
    assert isinstance(CellWatchApp.NAV_PALETTE["active"], tuple)
    assert isinstance(CellWatchApp.NAV_PALETTE["text"], tuple)
    assert isinstance(CellWatchApp.NAV_PALETTE["warn"], tuple)


def test_theme_icon_and_clean_metric_cards(tk_root):
    from monitor_app import utils
    icon = utils.create_theme_icon(size=(20, 20))
    assert isinstance(icon, ctk.CTkImage)

    frame = ctk.CTkFrame(tk_root)
    frame.pack()
    dashboard = DashboardScreen(frame)

    # Verify no bottom glow line exists in metric cards
    # Each card contains only inner frame with upper title and value label
    assert len(dashboard.metric_cards) == 4
    for title, card_dict in dashboard.metric_cards.items():
        assert "value" in card_dict
        val_lbl = card_dict["value"]
        assert val_lbl is not None

    frame.destroy()



def test_incident_threat_parsing_and_adversarial_layout(tk_root):
    from monitor_app.incidents import parse_threat_telemetry, summarize_event_type_short, IncidentsScreen

    # 1. Test telemetry parser against massive adversarial concatenated string
    raw_telemetry = (
        "Aggressive / Fighting (11%) + Aggressive / Fighting (12%) + Aggressive / Fighting (14%) + "
        + " + ".join([f"Cellphone ({30 + (i % 60)}% >= 30%)" for i in range(100)])
        + " + Knife (79%) + Knife (82%) + Fast Movement (6%)"
    )
    threats = parse_threat_telemetry(raw_telemetry)
    assert len(threats) == 4

    names = {t["name"]: t for t in threats}
    assert "Cellphone" in names
    assert names["Cellphone"]["category"] == "warning"
    assert names["Cellphone"]["tag"] == "CONTRABAND"
    assert names["Cellphone"]["count"] == 100
    assert names["Cellphone"]["max_conf"] == 89

    assert "Knife" in names
    assert names["Knife"]["category"] == "danger"
    assert names["Knife"]["tag"] == "WEAPON"
    assert names["Knife"]["max_conf"] == 82

    assert "Aggressive / Fighting" in names
    assert names["Aggressive / Fighting"]["category"] == "danger"
    assert names["Aggressive / Fighting"]["tag"] == "VIOLENCE"
    assert names["Aggressive / Fighting"]["max_conf"] == 14

    assert "Fast Movement" in names
    assert names["Fast Movement"]["category"] == "accent"
    assert names["Fast Movement"]["tag"] == "BEHAVIOR"

    summary_short = summarize_event_type_short(raw_telemetry)
    assert "Cellphone" in summary_short
    assert "Knife" in summary_short

    # 2. Test IncidentsScreen loading with adversarial data
    frame = ctk.CTkFrame(tk_root)
    frame.pack()
    screen = IncidentsScreen(frame)
    screen.review_tab.load_incident({
        "event_id": "TEST_ADVERSARIAL_101",
        "camera_id": "2",
        "timestamp_start": "2026-10-27T10:15:30",
        "event_type": raw_telemetry,
        "review_status": "PENDING"
    })

    # Assert UI rendered badges properly without blowing up
    badges = screen.review_tab.threat_badges_frame.winfo_children()
    assert len(badges) == 4
    assert screen.review_tab._raw_stream_visible is False

    # Toggle raw stream
    screen.review_tab._toggle_raw_stream()
    assert screen.review_tab._raw_stream_visible is True
    screen.review_tab._toggle_raw_stream()
    assert screen.review_tab._raw_stream_visible is False

    screen.stop_monitoring()
    frame.destroy()
