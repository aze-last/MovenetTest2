import os
import time
import sys

# Set up environment
os.environ["PYTHONPATH"] = "c:\\Users\\ASUS\\PycharmProjects\\MovenetTutorial"
sys.path.insert(0, os.environ["PYTHONPATH"])
os.environ["PYTHONUNBUFFERED"] = "1"

from monitor_app.main import CellWatchApp

def auto_run_4_cams():
    app = CellWatchApp()
    
    # Give it 3 seconds to start up cameras
    print("App started. Waiting for cameras to initialize...", flush=True)
    
    def go_to_live_monitor():
        print("Bypassing login...", flush=True)
        try:
            # Bypass login and go to Live Monitor
            app.on_login_success({"id": 1, "username": "admin", "role": "admin", "is_active": 1})
            app.switch_screen("Live Monitor")
        except Exception as e:
            print(f"Error during click: {e}", flush=True)
            app.destroy()
        
    app.after(3000, go_to_live_monitor)
    app.mainloop()

if __name__ == "__main__":
    auto_run_4_cams()
