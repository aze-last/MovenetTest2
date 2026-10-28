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



def test_reports_data_aggregation_and_presets(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    screen = ReportsScreen(frame)
    assert screen is not None

    # Test quick date presets
    screen._set_date_today()
    assert screen.date_from_var.get() != ""
    assert screen.date_from_var.get() == screen.date_to_var.get()

    screen._set_date_7days()
    assert screen.date_from_var.get() != ""
    assert screen.date_to_var.get() != ""

    screen._set_date_all()
    assert screen.date_from_var.get() == ""
    assert screen.date_to_var.get() == ""

    # Test report query & aggregation
    data = screen._query_report_data()
    assert "rows" in data
    assert "metrics" in data
    m = data["metrics"]
    assert "total" in m
    assert "confirmed" in m
    assert "false_alarms" in m
    assert "false_rate" in m

    # Test AI intelligence summary generation
    summary = screen.generate_ai_summary(m, data["rows"])
    assert "AI INTELLIGENCE EVALUATION" in summary

    # Test document text builder
    doc = screen._build_preview_document()
    assert "EXECUTIVE INTELLIGENCE SUMMARY" in doc
    assert "INSTITUTIONAL CHAIN OF CUSTODY" in doc

    # Reset filters
    screen.reset_filters()
    assert screen.camera_filter_var.get() == "All Cameras"
    assert screen.status_filter_var.get() == "All Statuses"

    frame.destroy()


def test_settings_upper_action_buttons(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    screen = SettingsScreen(frame, mode="monitoring")
    assert hasattr(screen, "monitoring_save_button")
    assert hasattr(screen, "btn_manage_cams")
    assert hasattr(screen, "monitoring_reset_button")
    assert hasattr(screen, "footer_save_btn")

    # Check button text
    assert screen.monitoring_save_button.cget("text") == "Save AI Preferences"
    assert screen.btn_manage_cams.cget("text") == "Manage Camera Network"
    assert screen.monitoring_reset_button.cget("text") == "Reset Custom to Medium"
    assert screen.footer_save_btn.cget("text") == "Save AI Preferences"

    # Reset to medium preset baseline
    screen.reset_custom_to_medium()
    screen.update_idletasks()

    frame.destroy()


def test_camera_management_dialog_lifecycle(tk_root, monkeypatch):
    from monitor_app.camera_view import CameraManagementDialog
    import numpy as np

    refreshed = False
    def on_refresh():
        nonlocal refreshed
        refreshed = True

    dialog = CameraManagementDialog(tk_root, on_refresh=on_refresh)
    assert dialog is not None
    assert hasattr(dialog, "lbl_capacity_badge")
    assert hasattr(dialog, "tree")
    assert hasattr(dialog, "entry_name")
    assert hasattr(dialog, "entry_src")
    assert hasattr(dialog, "btn_test")

    # Test appearance mode styling
    ctk.set_appearance_mode("Light")
    dialog._apply_appearance()
    ctk.set_appearance_mode("Dark")
    dialog._apply_appearance()

    # Test protocol mode switching
    dialog.proto_segmented.set("USB Webcam")
    dialog._on_protocol_change("USB Webcam")
    assert dialog.source_var.get() == "0"

    dialog.proto_segmented.set("RTSP Stream")
    dialog._on_protocol_change("RTSP Stream")

    # Test vendor presets
    dialog._on_preset_selected("TP-Link / Tapo (/stream1)")
    assert dialog.path_var.get() == "/stream1"

    dialog._on_preset_selected("Hikvision (/Streaming/Channels/101)")
    assert dialog.path_var.get() == "/Streaming/Channels/101"

    # Test RTSP URL auto-builder
    dialog.ip_var.set("192.168.1.50")
    dialog.port_var.set("554")
    dialog.user_var.set("admin")
    dialog.pass_var.set("secret123")
    dialog._build_rtsp_url()
    assert "rtsp://admin:secret123@192.168.1.50:554" in dialog.source_var.get()

    # Test password show/hide toggle
    dialog.show_pass_var.set(True)
    dialog._toggle_password_mask()
    assert dialog.entry_pass.cget("show") == ""
    dialog.show_pass_var.set(False)
    dialog._toggle_password_mask()
    assert dialog.entry_pass.cget("show") == "•"

    # Test clear form
    dialog._clear_form()
    assert dialog.name_var.get() == ""
    assert dialog.source_var.get() == ""

    # Test close_and_refresh
    dialog.close_and_refresh()
    assert refreshed is True


def test_camera_id_normalization():
    from monitor_app import profile_store

    profile_store.ensure_app_state()
    # Normalize current state
    profile_store.normalize_camera_ids()
    cams = profile_store.list_cameras()
    assert len(cams) > 0
    # All IDs must be sequential 1..len(cams)
    for idx, c in enumerate(cams, start=1):
        assert c["camera_id"] == idx

    # Test creating a gap and normalizing
    conn = profile_store._connect()
    # Artificially set an ID to 99
    conn.execute("UPDATE cameras SET camera_id = 99 WHERE camera_id = 1")
    conn.commit()
    conn.close()

    # Call normalization
    profile_store.normalize_camera_ids()
    normalized_cams = profile_store.list_cameras()
    for idx, c in enumerate(normalized_cams, start=1):
        assert c["camera_id"] == idx
