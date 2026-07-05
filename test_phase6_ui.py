import os
import time
import sys

# Set up environment
os.environ["PYTHONPATH"] = "c:\\Users\\ASUS\\PycharmProjects\\MovenetTutorial"
sys.path.insert(0, os.environ["PYTHONPATH"])

from monitor_app.main import CellWatchApp

def auto_run_benchmark():
    app = CellWatchApp()
    
    # Give it 3 seconds to start up cameras
    print("App started. Waiting for cameras to initialize...")
    
    def click_benchmark():
        print("Clicking Start Benchmark in UI...")
        try:
            # Bypass login and go to Live Monitor
            app.on_login_success({"id": 1, "username": "admin", "role": "admin", "is_active": 1})
            app.switch_screen("Live Monitor")
            
            # The current screen should be CameraMonitorScreen
            screen = None
            for child in app.container.winfo_children():
                if hasattr(child, "toggle_benchmark"):
                    screen = child
                    break
                    
            if screen:
                screen.toggle_benchmark()
                print("Benchmark started. Waiting for Quick profile to finish...")
                
                # Poll every second until benchmark is no longer active
                def check_done():
                    from monitor_app.utils import GlobalState
                    if not GlobalState.benchmark_active:
                        print("Benchmark finished. Closing app...")
                        app.destroy()
                    else:
                        app.after(1000, check_done)
                
                # Wait 5 seconds before starting to check (so it has time to set to True)
                app.after(5000, check_done)
            else:
                print("Error: current_screen does not have toggle_benchmark")
                app.destroy()
        except Exception as e:
            print(f"Error during click: {e}")
            app.destroy()
        
    app.after(5000, click_benchmark)
    app.mainloop()

if __name__ == "__main__":
    auto_run_benchmark()
