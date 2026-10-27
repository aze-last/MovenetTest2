import os
import sys
import time
from PIL import ImageGrab

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_app.main import CellWatchApp

def capture():
    app = CellWatchApp()
    app.geometry("1400x900")
    app.update()
    
    # Authenticate / set user dict
    app.current_user = {"username": "admin", "full_name": "Duty Officer"}
    app.create_navigation()
    
    # Switch to Incidents screen
    app.switch_screen("Incidents")
    app.update()
    time.sleep(0.5)
    app.update()

    inc_frame = app.current_screen
    if inc_frame and hasattr(inc_frame, "db_path"):
        import sqlite3
        conn = sqlite3.connect(inc_frame.db_path)
        cur = conn.cursor()
        cur.execute("SELECT event_id FROM incidents ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            print("Loading incident:", row[0])
            inc_frame.select_incident_by_id(row[0])
            app.update()
            time.sleep(0.5)
            app.update()

    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()

    bbox = (x, y, x + w, y + h)
    os.makedirs("scratch", exist_ok=True)
    shot = ImageGrab.grab(bbox=bbox)
    shot.save("scratch/incident_page_actual.png")
    print(f"Captured screenshot to scratch/incident_page_actual.png, size: {w}x{h}")

    app.destroy()

if __name__ == "__main__":
    capture()

