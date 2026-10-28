import time
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import tkinter as tk
import customtkinter as ctk

def test():
    from monitor_app.main import CellWatchApp
    app = CellWatchApp()
    app.withdraw()

    for cycle in range(1, 4):
        print(f"\n================ CYCLE {cycle} ================")
        print(f"Switching to Live Monitor (Cycle {cycle})...")
        app.switch_screen("Live Monitor")
        
        # Run event loop for 3 seconds
        t_end = time.time() + 3.0
        while time.time() < t_end:
            app.update()
            time.sleep(0.02)

        screen = [w for w in app.container.winfo_children() if hasattr(w, "cameras")][0]
        print(f"Cycle {cycle}: {len(screen.cameras)} cameras present")
        for i, cam in enumerate(screen.cameras):
            print(f"  Cam {cam.camera_id}: running={cam.running}, is_offline={getattr(cam, 'is_offline', False)}, res_q_size={cam.result_queue.qsize()}")

        print(f"Switching to Dashboard (leaving Cycle {cycle})...")
        app.switch_screen("Dashboard")
        t_end = time.time() + 1.0
        while time.time() < t_end:
            app.update()
            time.sleep(0.02)

    app.destroy()
    print("\nALL 3 CYCLES COMPLETED CLEANLY!")

if __name__ == "__main__":
    test()
