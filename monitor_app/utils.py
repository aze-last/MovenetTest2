import os
import sys
import random
import time
import shutil
import tkinter as tk
from tkinter import ttk

# --- PyInstaller Path Helpers ---
def resource_path(relative_path):
    """
    Get the absolute path to a read-only bundled resource.
    Works for dev and for PyInstaller --onefile mode.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # In dev, the base path is the parent of monitor_app
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)

_LEGACY_MIGRATION_DONE = False

def get_user_data_dir() -> str:
    r"""
    Returns the absolute path to the writeable user application data directory.
    In frozen production, returns %LocalAppData%\CellWatchAI.
    In development, returns the project root.
    """
    if getattr(sys, 'frozen', False):
        try:
            import platformdirs
            base_path = platformdirs.user_data_dir("CellWatchAI", appauthor=False)
        except Exception:
            base_path = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CellWatchAI")
        os.makedirs(base_path, exist_ok=True)
        return base_path
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def data_path(relative_path: str) -> str:
    r"""
    Get the absolute path for read-write application data.
    In production (frozen), data is stored in %LocalAppData%\CellWatchAI to ensure
    safe user write access under Program Files and survive application updates.
    In development, data is stored relative to the project root.
    Fast path resolution without synchronous migration overhead.
    """
    base_path = get_user_data_dir()
    return os.path.join(base_path, relative_path)

def migrate_legacy_data(legacy_root: str = None, target_root: str = None) -> list:
    r"""
    Migrate existing databases and runtime directories from legacy locations
    (e.g. next to the frozen executable in Program Files or legacy AppData)
    into the active writeable data directory.

    Safe to call multiple times (guarded by _LEGACY_MIGRATION_DONE).
    Handles both files (app_state.db, incidents.db) and directories
    (recordings, exports, updates).
    """
    global _LEGACY_MIGRATION_DONE
    migrated = []

    if target_root is None:
        target_root = get_user_data_dir()

    candidate_legacy_roots = []
    if legacy_root is not None:
        candidate_legacy_roots.append(legacy_root)
    else:
        if getattr(sys, 'frozen', False):
            # Check next to executable
            exe_dir = os.path.dirname(sys.executable)
            candidate_legacy_roots.append(exe_dir)
            # Also check old %LocalAppData%\CellWatch if different from CellWatchAI
            old_appdata = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CellWatch")
            if os.path.exists(old_appdata) and os.path.normpath(old_appdata) != os.path.normpath(target_root):
                candidate_legacy_roots.append(old_appdata)

    if not candidate_legacy_roots:
        _LEGACY_MIGRATION_DONE = True
        return migrated

    items_to_migrate = [
        "app_state.db",
        "incidents.db",
        "recordings",
        "exports",
        "updates"
    ]

    for cand_root in candidate_legacy_roots:
        if not os.path.exists(cand_root) or os.path.normpath(cand_root) == os.path.normpath(target_root):
            continue

        for item in items_to_migrate:
            src = os.path.join(cand_root, item)
            dst = os.path.join(target_root, item)

            if not os.path.exists(src):
                continue

            try:
                if os.path.isfile(src):
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        migrated.append(item)
                elif os.path.isdir(src):
                    if not os.path.exists(dst):
                        shutil.copytree(src, dst)
                        migrated.append(item)
                    else:
                        for root, _, files in os.walk(src):
                            rel_dir = os.path.relpath(root, src)
                            dest_dir = os.path.join(dst, rel_dir)
                            os.makedirs(dest_dir, exist_ok=True)
                            for f in files:
                                src_f = os.path.join(root, f)
                                dst_f = os.path.join(dest_dir, f)
                                if not os.path.exists(dst_f):
                                    shutil.copy2(src_f, dst_f)
                                    migrated.append(os.path.join(item, rel_dir, f) if rel_dir != "." else os.path.join(item, f))
            except Exception as e:
                print(f"[Warning] Failed to migrate legacy item '{item}' from {src}: {e}")

    _LEGACY_MIGRATION_DONE = True
    return migrated

def normalize_cam_id(cid) -> str:
    """Normalize camera IDs (0, '0', '00', 'cam_0', 'cam01') to a clean canonical string ('0', '1', etc.)."""
    if cid is None:
        return "0"
    s = str(cid).strip()
    digits = "".join(c for c in s if c.isdigit())
    if digits:
        return str(int(digits))
    return s.lower()

# --- Constants & Config ---
APP_TITLE = "CellWatch AI"
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
    Simulates the MoveNet and YOLO26s detection backend.
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
def update_ttk_theme(root=None, mode=None):
    """
    Dynamically configures standard ttk styles to match Light or Dark mode.
    """
    if mode is None:
        try:
            import customtkinter as ctk
            mode = ctk.get_appearance_mode()
        except Exception:
            mode = "Dark"

    style = ttk.Style(root)
    is_light = mode == "Light"

    bg = "#edf2f7" if is_light else COLOR_BG_DARK
    card_bg = "#ffffff" if is_light else COLOR_BG_LIGHT
    fg = "#0f172a" if is_light else COLOR_TEXT_WHITE

    style.configure("TFrame", background=bg)
    style.configure("Card.TFrame", background=card_bg, relief="flat")
    style.configure("TLabel", background=bg, foreground=fg, font=FONT_NORMAL)
    style.configure("Header.TLabel", font=FONT_HEADER, background=bg, foreground=fg)
    style.configure("SubHeader.TLabel", font=FONT_SUBHEADER, background=bg, foreground=fg)
    style.configure("Card.TLabel", background=card_bg, foreground=fg)
    style.configure("Bold.TLabel", font=FONT_BOLD, background=card_bg, foreground=fg)
    style.configure("TEntry", fieldbackground=card_bg, foreground=fg, borderwidth=0)
    return style


def apply_dark_theme(root):
    """
    Configures ttk styles for theme look, adapting to current mode.
    """
    style = ttk.Style(root)
    style.theme_use('clam') # 'clam' is often a good base for custom coloring
    update_ttk_theme(root)
    
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

    return style


def create_theme_icon(size=(20, 20)):
    """
    Creates an antialiased CTkImage for toggling themes.
    - Light Mode displays a crescent moon (action: switch to dark).
    - Dark Mode displays a warm radiant sun (action: switch to light).
    """
    import math
    from PIL import Image, ImageDraw
    import customtkinter as ctk

    scale = 4
    w, h = size[0] * scale, size[1] * scale

    # --- Sun (for Dark mode: luminous warm sun) ---
    sun = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_sun = ImageDraw.Draw(sun)
    cx, cy = w / 2, h / 2
    r_core = w * 0.22
    draw_sun.ellipse([cx - r_core, cy - r_core, cx + r_core, cy + r_core], fill="#f59e0b")
    for i in range(8):
        angle = i * (math.pi / 4)
        x1 = cx + w * 0.31 * math.cos(angle)
        y1 = cy + w * 0.31 * math.sin(angle)
        x2 = cx + w * 0.44 * math.cos(angle)
        y2 = cy + w * 0.44 * math.sin(angle)
        draw_sun.line([x1, y1, x2, y2], fill="#f59e0b", width=int(scale * 1.8))
    sun = sun.resize(size, Image.Resampling.LANCZOS)

    # --- Moon (for Light mode: deep indigo/slate crescent moon) ---
    moon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_moon = ImageDraw.Draw(moon)
    m_r = w * 0.36
    draw_moon.ellipse([cx - m_r, cy - m_r, cx + m_r, cy + m_r], fill="#0284c7")
    cut_x = cx + w * 0.16
    cut_y = cy - w * 0.10
    cut_r = w * 0.32
    draw_moon.ellipse(
        [cut_x - cut_r, cut_y - cut_r, cut_x + cut_r, cut_y + cut_r],
        fill=(0, 0, 0, 0)
    )
    moon = moon.resize(size, Image.Resampling.LANCZOS)

    return ctk.CTkImage(light_image=moon, dark_image=sun, size=size)



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
    start_time = time.time()
    
    # Benchmark Configuration Lock
    benchmark_active = False
    _benchmark_frozen_config = None
    
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
            "total_detections": cls.last_total_detections,
            "benchmark_active": cls.benchmark_active,
        }

    @classmethod
    def lock_benchmark(cls, frozen_config: dict):
        """Freeze configuration during benchmark. Prevents operator changes."""
        cls.benchmark_active = True
        cls._benchmark_frozen_config = frozen_config

    @classmethod
    def unlock_benchmark(cls):
        """Release configuration lock after benchmark ends."""
        cls.benchmark_active = False
        cls._benchmark_frozen_config = None

    @classmethod
    def get_frozen_config(cls):
        """Returns the locked configuration snapshot, or None if unlocked."""
        return cls._benchmark_frozen_config

