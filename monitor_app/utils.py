import random
import time
import tkinter as tk
from tkinter import ttk

# --- Constants & Config ---
# Workflow Test: Summer 2026 Session
APP_TITLE = "CellWatch AI v1.1"
WINDOW_SIZE = "1280x800"

# Colors (Dark Theme)
COLOR_BG_DARK = "#1e1e1e"
COLOR_BG_LIGHT = "#2d2d2d"
COLOR_TEXT_WHITE = "#ffffff"
COLOR_TEXT_GRAY = "#aaaaaa"
COLOR_ACCENT = "#3498db"  # Blue
COLOR_SUCCESS = "#2ecc71" # Green
COLOR_WARNING = "#f1c40f" # Yellow
COLOR_ALERT = "#e74c3c"   # Red

# Fonts
FONT_HEADER = ("Helvetica", 16, "bold")
FONT_SUBHEADER = ("Helvetica", 12, "bold")
FONT_NORMAL = ("Helvetica", 10)
FONT_BOLD = ("Helvetica", 10, "bold")

# --- Mock AI Engine ---
class MockAI:
    """
    Simulates the MoveNet and YOLOv8 detection backend.
    In a real implementation, this would interact with the loaded models.
    """
    
    BEHAVIORS = ["Normal", "Standing", "Walking", "Sitting", "Aggressive", "Falling"]
    CONTRABAND = ["None", "None", "None", "Smartphone", "Weapon"]
    
    @staticmethod
    def detect_behavior_frame(camera_id):
        """
        Simulates analyzing a single frame.
        Returns: (behavior_label, is_alert, confidence)
        """
        # Randomly trigger alerts for demonstration
        # camera_id can be used to bias certain cameras to be more active if needed
        
        # 95% chance of normal behavior
        if random.random() > 0.05:
            return "Normal", False, random.uniform(0.8, 0.99)
        
        # Rare events
        behavior = random.choice(MockAI.BEHAVIORS[4:]) # Aggressive or Falling
        return behavior, True, random.uniform(0.7, 0.95)

    @staticmethod
    def detect_contraband_frame(camera_id):
        """
        Simulates detecting contraband.
        Returns: (item_label, is_alert)
        """
        if random.random() > 0.99: # Very rare
            item = random.choice(MockAI.CONTRABAND[3:])
            return item, True
        return "None", False

# --- UI Helpers ---
def apply_dark_theme(root):
    """
    Configures ttk styles for a dark theme look.
    """
    style = ttk.Style(root)
    style.theme_use('clam') # 'clam' is often a good base for custom coloring
    
    # Frames
    style.configure("TFrame", background=COLOR_BG_DARK)
    style.configure("Card.TFrame", background=COLOR_BG_LIGHT, relief="flat")
    
    # Labels
    style.configure("TLabel", background=COLOR_BG_DARK, foreground=COLOR_TEXT_WHITE, font=FONT_NORMAL)
    style.configure("Header.TLabel", font=FONT_HEADER, background=COLOR_BG_DARK, foreground=COLOR_TEXT_WHITE)
    style.configure("SubHeader.TLabel", font=FONT_SUBHEADER, background=COLOR_BG_DARK, foreground=COLOR_TEXT_WHITE)
    style.configure("Card.TLabel", background=COLOR_BG_LIGHT, foreground=COLOR_TEXT_WHITE)
    
    # Buttons
    style.configure("TButton", 
                    background=COLOR_ACCENT, 
                    foreground=COLOR_TEXT_WHITE, 
                    font=FONT_BOLD, 
                    borderwidth=0, 
                    focuscolor=COLOR_ACCENT)
    style.map("TButton", background=[('active', '#2980b9')])
    
    style.configure("Success.TButton", background=COLOR_SUCCESS)
    style.map("Success.TButton", background=[('active', '#27ae60')])
    
    style.configure("Danger.TButton", background=COLOR_ALERT)
    style.map("Danger.TButton", background=[('active', '#c0392b')])

    # Entry
    style.configure("TEntry", fieldbackground=COLOR_BG_LIGHT, foreground=COLOR_TEXT_WHITE, borderwidth=0)
    
    style.configure("Bold.TLabel", font=FONT_BOLD, background=COLOR_BG_LIGHT, foreground=COLOR_TEXT_WHITE)

    return style

def create_placeholder_image(width, height, text="No Signal", color=COLOR_BG_LIGHT):
    """
    Returns a tk.PhotoImage (via PIL) with a placeholder rectangle.
    Useful so we don't need external assets immediately.
    """
    from PIL import Image, ImageDraw
    
    img = Image.new('RGB', (width, height), color)
    d = ImageDraw.Draw(img)
    # Draw an X
    d.line([(0,0), (width, height)], fill=COLOR_BG_DARK, width=2)
    d.line([(0, height), (width, 0)], fill=COLOR_BG_DARK, width=2)
    
    # This function would return a PIL image. 
    # The caller needs to convert to ImageTk.PhotoImage within the main loop to prevent garbage collection.
    return img

class GlobalState:
    """
    Singleton-like class to track real-time system metrics across screens.
    """
    active_cameras = set()
    active_alerts = set() # Set of camera IDs with active alerts
    last_total_detections = 0
    system_status = "ONLINE"
    
    @classmethod
    def register_camera(cls, cam_id):
        cls.active_cameras.add(cam_id)
        
    @classmethod
    def unregister_camera(cls, cam_id):
        if cam_id in cls.active_cameras:
            cls.active_cameras.remove(cam_id)
        if cam_id in cls.active_alerts:
            cls.active_alerts.remove(cam_id)
            
    @classmethod
    def set_alert(cls, cam_id, active):
        if active:
            cls.active_alerts.add(cam_id)
        else:
            if cam_id in cls.active_alerts:
                cls.active_alerts.remove(cam_id)

    @classmethod
    def get_metrics(cls):
        return {
            "active_cams": len(cls.active_cameras),
            "active_alerts": len(cls.active_alerts),
            "status": cls.system_status,
            "total_detections": cls.last_total_detections
        }
