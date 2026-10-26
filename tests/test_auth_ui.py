import sys
import pytest
import customtkinter as ctk

from monitor_app import profile_store
from monitor_app.auth import LoginScreen, _is_caps_lock_on


def test_profile_store_appearance_mode():
    profile_store.ensure_app_state()
    original_mode = profile_store.get_appearance_mode()
    try:
        profile_store.set_appearance_mode("Light")
        assert profile_store.get_appearance_mode() == "Light"

        profile_store.set_appearance_mode("Dark")
        assert profile_store.get_appearance_mode() == "Dark"
    finally:
        profile_store.set_appearance_mode(original_mode)





def test_caps_lock_detector():
    state = _is_caps_lock_on()
    assert isinstance(state, bool)


def test_login_screen_creation_and_ergonomics(tk_root):
    frame = ctk.CTkFrame(tk_root)
    frame.pack()

    login_success_called = []

    def on_success(user):
        login_success_called.append(user)

    screen = LoginScreen(frame, on_login_success=on_success)
    assert screen is not None


    # Verify Dual-Mode Palette is configured with tuples
    assert isinstance(screen.PALETTE["page_bg"], tuple)
    assert isinstance(screen.PALETTE["card_bg"], tuple)
    assert isinstance(screen.PALETTE["accent"], tuple)

    # Verify Theme Toggle Button exists
    assert hasattr(screen, "btn_theme_toggle")
    assert screen.btn_theme_toggle is not None

    # Test toggling appearance mode
    initial_mode = ctk.get_appearance_mode()
    screen.toggle_appearance_mode()
    new_mode = ctk.get_appearance_mode()
    assert new_mode != initial_mode
    assert profile_store.get_appearance_mode() == new_mode

    # Toggle back to clean state
    screen.toggle_appearance_mode()
    assert ctk.get_appearance_mode() == initial_mode

    # Verify Password Visibility Toggle
    assert screen._password_masked is True
    assert screen.btn_show_pass.cget("text") == "Show"

    # With password text inserted, mask is active
    screen.entry_pass.insert(0, "testkey")
    assert screen.entry_pass.cget("show") == "*"

    screen.toggle_password_visibility()
    assert screen._password_masked is False
    assert screen.entry_pass.cget("show") == ""
    assert screen.btn_show_pass.cget("text") == "Hide"

    screen.toggle_password_visibility()
    assert screen._password_masked is True
    assert screen.entry_pass.cget("show") == "*"
    assert screen.btn_show_pass.cget("text") == "Show"

    # Verify Zero CLS container
    assert hasattr(screen, "status_container")
    assert screen.status_container.cget("height") == 34

    # Verify Caps lock indicator label exists
    assert hasattr(screen, "caps_warning")

    frame.destroy()
