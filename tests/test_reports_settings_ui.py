import pytest
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from monitor_app import utils
from monitor_app.reports import ReportsScreen
from monitor_app.settings import SettingsScreen, PALETTE as SETTINGS_PALETTE


def test_reports_palette_tuples():
    assert isinstance(ReportsScreen.PALETTE["page"], tuple)
    assert isinstance(ReportsScreen.PALETTE["card"], tuple)
    assert isinstance(ReportsScreen.PALETTE["accent"], tuple)
    assert isinstance(ReportsScreen.PALETTE["text"], tuple)
    assert isinstance(ReportsScreen.PALETTE["paper"], tuple)


def test_reports_instantiation_and_theme_toggle(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    screen = ReportsScreen(frame)
    assert screen is not None
    assert hasattr(screen, "apply_appearance_mode")

    ctk.set_appearance_mode("Light")
    screen.apply_appearance_mode()
    screen.update_idletasks()

    ctk.set_appearance_mode("Dark")
    screen.apply_appearance_mode()
    screen.update_idletasks()

    frame.destroy()


def test_settings_palette_tuples():
    assert isinstance(SETTINGS_PALETTE["page"], tuple)
    assert isinstance(SETTINGS_PALETTE["card"], tuple)
    assert isinstance(SETTINGS_PALETTE["accent"], tuple)
    assert isinstance(SETTINGS_PALETTE["text"], tuple)


def test_settings_profile_mode_and_treeview(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    screen = SettingsScreen(frame, mode="profile")
    assert screen is not None
    assert hasattr(screen, "account_tree")
    assert hasattr(screen, "apply_appearance_mode")

    ctk.set_appearance_mode("Light")
    screen.apply_appearance_mode()
    style = ttk.Style()
    assert style.lookup("Accounts.Treeview", "background") == "#ffffff"
    assert style.lookup("Accounts.Treeview", "foreground") == "#0f172a"

    ctk.set_appearance_mode("Dark")
    screen.apply_appearance_mode()
    assert style.lookup("Accounts.Treeview", "background") == "#1b2430"
    assert style.lookup("Accounts.Treeview", "foreground") == "#f3f7fb"

    frame.destroy()


def test_settings_monitoring_mode(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    screen = SettingsScreen(frame, mode="monitoring")
    assert screen is not None
    assert hasattr(screen, "sliders")
    assert "conf_thr" in screen.sliders

    ctk.set_appearance_mode("Light")
    screen.update_idletasks()
    ctk.set_appearance_mode("Dark")
    screen.update_idletasks()

    frame.destroy()


def test_utils_update_ttk_theme():
    style = utils.update_ttk_theme(mode="Light")
    assert style.lookup("TFrame", "background") == "#edf2f7"
    assert style.lookup("TLabel", "foreground") == "#0f172a"

    style = utils.update_ttk_theme(mode="Dark")
    assert style.lookup("TFrame", "background") == utils.COLOR_BG_DARK
    assert style.lookup("TLabel", "foreground") == utils.COLOR_TEXT_WHITE
