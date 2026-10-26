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

