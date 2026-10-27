import sys
import os
sys.path.insert(0, os.path.abspath("."))

import sqlite3
import tkinter as tk
import customtkinter as ctk

from monitor_app.incidents import IncidentsScreen, PALETTE

def test_ui():
    root = ctk.CTk()
    root.geometry("1400x850")
    root.withdraw()

    screen = IncidentsScreen(root)
    
    conn = sqlite3.connect("incidents.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM incidents WHERE event_id = 'INC_20260828_150920_1'")
    row = c.fetchone()
    conn.close()

    assert row is not None
    data = dict(row)
    screen.review_tab.load_incident(data)
    
    # Check threat badges
    badge_children = screen.review_tab.threat_badges_frame.winfo_children()
    print("Threat badges created:", len(badge_children))
    assert len(badge_children) == 4, f"Expected 4 threat badges, got {len(badge_children)}"
    
    # Check count chip
    chip_text = screen.review_tab.threat_count_chip.cget("text")
    print("Threat count chip:", chip_text)
    assert "4 types" in chip_text
    
    # Check raw stream toggle
    print("Raw stream visible initial:", screen.review_tab._raw_stream_visible)
    screen.review_tab._toggle_raw_stream()
    print("Raw stream visible after toggle:", screen.review_tab._raw_stream_visible)
    assert screen.review_tab._raw_stream_visible is True
    screen.review_tab._toggle_raw_stream()
    assert screen.review_tab._raw_stream_visible is False

    # Check comment box
    print("Comment box present:", screen.review_tab.comment_box is not None)

    # Check status chip
    print("Status chip text:", screen.review_tab.status_chip.cget("text"))

    # Test Light and Dark appearance modes
    ctk.set_appearance_mode("Light")
    root.update()
    ctk.set_appearance_mode("Dark")
    root.update()
    
    # Test loading an empty/minimal incident
    screen.review_tab.load_incident({
        "event_id": "TEST_EMPTY",
        "camera_id": "1",
        "timestamp_start": "2026-10-27T10:00:00",
        "event_type": "",
        "review_status": "PENDING"
    })
    empty_badges = screen.review_tab.threat_badges_frame.winfo_children()
    print("Empty badges created:", len(empty_badges))
    assert len(empty_badges) == 1 # 1 placeholder label
    assert "0 items" in screen.review_tab.threat_count_chip.cget("text")

    screen.stop_monitoring()
    root.destroy()
    print("VERIFICATION COMPLETE: ALL ASSERTIONS PASSED!")

if __name__ == "__main__":
    test_ui()

