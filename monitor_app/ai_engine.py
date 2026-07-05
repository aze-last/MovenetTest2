import cv2
import numpy as np
import os
import time
import threading
from collections import deque
from datetime import datetime
from PIL import Image

from monitor_app.evidence import TrackedPerson
from monitor_app.config import get_config


# ==========================================
# CAPSTONE DEFENSE DEBUGGER
# ==========================================
class CapstoneDebug:
    """Provides clear reasoning logs for engine decisions."""
    ENABLED = True

    @staticmethod
    def log(camera_id, message):
        if CapstoneDebug.ENABLED:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [Monitor-{camera_id}] AI Thinking: {message}")


# ==========================================
# AI AVAILABILITY CHECK
# ==========================================
TF_AVAILABLE = False
HUB_AVAILABLE = False
YOLO_AVAILABLE = False

try:
    import tensorflow as tf

    if hasattr(tf, "__version__"):
        TF_AVAILABLE = True
        import tensorflow_hub as hub

        HUB_AVAILABLE = True
except Exception:
    pass
if not TF_AVAILABLE:
    print("TensorFlow not available; MoveNet disabled.")
elif not HUB_AVAILABLE:
    print("tensorflow_hub not available; will use local MoveNet if present.")

try:
    from ultralytics import YOLO
    import torch

    YOLO_AVAILABLE = True
except Exception:
    pass


# ==========================================
# BASIC MOTION ENGINE (Fallback)
# ==========================================
class BasicMotionEngine:
    """Fallback when no AI models are loaded."""

    def __init__(self, sensitivity="medium"):
        self.trackers = {}
        self.threshold = 3.0 if sensitivity == "medium" else 1.5

    def process_frame(self, frame, camera_id="0", frame_uuid=None):
        if camera_id not in self.trackers:
            self.trackers[camera_id] = None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        status = "Normal"
        if self.trackers[camera_id] is not None:
            diff = cv2.absdiff(self.trackers[camera_id], gray)
            score = np.mean(diff)
            if score > self.threshold:
                status = "Movement"

        self.trackers[camera_id] = gray
        cv2.putText(frame, f"Mode: Basic Motion ({status})", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        return {
            "frame": frame.copy(), "num_people": 0, "alert_triggered": False,
            "alerts": [], "detections": {"behavior": [], "contraband": []},
            "processing_mode": "basic_motion"
        }


# ==========================================
# MOTION-OPTIMIZED AI ENGINE (Primary)
# ==========================================
class MotionOptimizedEngine:
    """
    Capstone Grade AI Engine.
    Combines: MoveNet (Logic) + YOLOv8 (Objects/Pose Fallback)
    Optimization: Only runs heavy AI when Stage 1 Motion is detected.
    """

    def __init__(self, debug=False, sensitivity="medium", enable_yolo=True, custom_values=None, **kwargs):
        print("--- CAPSTONE AI ENGINE INITIALIZING ---")
        self.debug = debug
        self.enable_yolo = enable_yolo and YOLO_AVAILABLE
        self.gpu_enabled = False

        # Motion Gating (The "Energy Saver")
        self.motion_threshold = 5000
        self.motion_ratio = 0.008
        self.bg_subtractors = {}
        self.last_gray = {}

        # AI Models
        self.movenet = None
        self.yolo_custom = None  # best.pt (Knife + Cellphone combined model)

        # Performance/Audit
        self.lock = threading.Lock()
        self.tf_inference_lock = threading.Lock()
        self.yolo_inference_lock = threading.Lock()
        self.stats = {"total": 0, "ai_runs": 0, "skipped": 0}
        self.trackers = {}
        self.yolo_trackers = {}
        self.last_run = {}  # For throttling

        custom_vals = kwargs.get("custom_values")
        self._set_logic_sensitivity(sensitivity, custom_vals)
        self._setup_hardware()
        self._load_models()

        # Skeletal Edges (MoveNet standard)
        self.EDGES = [(0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11),
                      (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]

    def _set_logic_sensitivity(self, level, custom_values=None):
        if level == "high":
            self.CONF_THR = 0.25
            self.AGG_THR = 450.0  # pixels/sec
            self.ACTIVE_THR = 140.0
            self.ALERT_FRAMES = 2
            self.motion_threshold = 4500
            self.motion_ratio = 0.009
            self.yolo_knife_conf = 0.30
            self.yolo_cell_conf = 0.30
            self.yolo_fallback_conf = 0.50
        elif level == "low":
            self.CONF_THR = 0.18
            self.AGG_THR = 700.0
            self.ACTIVE_THR = 250.0
            self.ALERT_FRAMES = 5
            self.motion_threshold = 6000
            self.motion_ratio = 0.012
            self.yolo_knife_conf = 0.40
            self.yolo_cell_conf = 0.40
            self.yolo_fallback_conf = 0.60
        elif level == "custom" and custom_values:
            self.CONF_THR = float(custom_values.get("conf_thr", 0.22))
            self.AGG_THR = float(custom_values.get("agg_thr", 180.0))
            self.ACTIVE_THR = float(custom_values.get("active_thr", 90.0))
            self.ALERT_FRAMES = int(custom_values.get("alert_frames", 3))
            self.motion_threshold = int(custom_values.get("motion_threshold", 5000))
            self.motion_ratio = float(custom_values.get("motion_ratio", 0.010))
            self.yolo_knife_conf = float(custom_values.get("yolo_knife_conf", 0.30))
            self.yolo_cell_conf = float(custom_values.get("yolo_cell_conf", 0.30))
            self.yolo_fallback_conf = float(custom_values.get("yolo_fallback_conf", 0.50))
        else:  # medium (default)
            self.CONF_THR = 0.22
            self.AGG_THR = 180.0
            self.ACTIVE_THR = 90.0
            self.ALERT_FRAMES = 3
            self.motion_threshold = 5000
            self.motion_ratio = 0.010
            self.yolo_knife_conf = 0.30
            self.yolo_cell_conf = 0.30
            self.yolo_fallback_conf = 0.50

    def apply_profile(self, level, custom_values=None):
        """Hot-reload thresholds on a running engine without reinit."""
        with self.lock:
            self._set_logic_sensitivity(level, custom_values)
            print(f"--- AI ENGINE: Profile switched to '{level}' ---")

    def _setup_hardware(self):
        """Enable GPU for YOLOv8 and force CPU for TensorFlow/MoveNet to conserve VRAM."""
        # --- MoveNet / TensorFlow (Forced CPU) ---
        if TF_AVAILABLE:
            try:
                tf.config.set_visible_devices([], 'GPU')
                self.gpu_enabled = False
                print("MoveNet: Forced CPU execution (GPU hidden to conserve VRAM)")
                CapstoneDebug.log("All", "MoveNet running on CPU (visible GPUs: [])")
            except Exception as e:
                print(f"MoveNet forced CPU setup error: {e}")
        else:
            print("MoveNet: TensorFlow unavailable — skipped")

        # --- YOLOv8 / PyTorch ---
        if YOLO_AVAILABLE:
            if torch.cuda.is_available():
                self.yolo_device = 0  # GPU index
                print(f" YOLOv8: GPU Accelerated — {torch.cuda.get_device_name(0)}")
            else:
                self.yolo_device = 'cpu'
                print("YOLOv8: No CUDA GPU detected — running on CPU")
        else:
            self.yolo_device = 'cpu'
            print("YOLOv8: Ultralytics/PyTorch unavailable — skipped")

    def _load_models(self):
        """Clean modular loading for explanation."""
        if TF_AVAILABLE:
            print("Loading MoveNet MultiPose (behavior engine)...")
            try:
                # Try local first
                p = os.path.join(os.path.dirname(__file__), "models", "movenet_multipose")
                local_model_path = None
                if os.path.exists(p):
                    if os.path.exists(os.path.join(p, "saved_model.pb")):
                        local_model_path = p
                    else:
                        for root, _dirs, files in os.walk(p):
                            if "saved_model.pb" in files:
                                local_model_path = root
                                break
                if local_model_path:
                    self.movenet = tf.saved_model.load(local_model_path).signatures["serving_default"]
                    print(f"MoveNet loaded from local path: {local_model_path}")
                elif HUB_AVAILABLE:
                    self.movenet = hub.load("https://tfhub.dev/google/movenet/multipose/lightning/1").signatures[
                        "serving_default"]
                    print("MoveNet loaded from TFHub.")
                else:
                    print("MoveNet skipped: tensorflow_hub unavailable and local model missing.")
            except Exception as e:
                print(f"MoveNet load failed: {e}")
        else:
            print("MoveNet skipped: TensorFlow unavailable.")

        if self.enable_yolo:
            from monitor_app.config import get_config

            model_dir = os.path.join(os.path.dirname(__file__), "models")
            primary_name = get_config("yolo", "model_path", "best.engine")
            fallback_name = get_config("yolo", "model_path_fallback", "best.pt")

            self.yolo_custom = None
            self.active_model_name = None
            active_model_name = None

            for candidate in [primary_name, fallback_name]:
                candidate_path = os.path.join(model_dir, candidate)
                if not os.path.exists(candidate_path):
                    print(f"[YOLO] {candidate} not found at {candidate_path}, trying next option")
                    continue
                try:
                    self.yolo_custom = YOLO(candidate_path)
                    active_model_name = candidate
                    print(f"[YOLO] Loaded {candidate} successfully")
                    break
                except Exception as e:
                    print(f"[YOLO] Failed to load {candidate}: {e}")

            if self.yolo_custom is None:
                print("[YOLO] CRITICAL: No usable model loaded (tried engine + pt fallback). Contraband detection is DISABLED.")
            else:
                self.active_model_name = active_model_name  # expose for UI/logs so it's visible which one is running

        if self.movenet is None:
            print("MoveNet not loaded; behavior detection disabled.")

    def detect_motion(self, frame, camera_id):
        """Stage 1: Lightweight Motion Check"""
        if camera_id not in self.bg_subtractors:
            self.bg_subtractors[camera_id] = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30,
                                                                                detectShadows=False)
            self.last_gray[camera_id] = None

        frame_h, frame_w = frame.shape[:2]
        adaptive_threshold = max(self.motion_threshold, int(frame_h * frame_w * self.motion_ratio))
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (15, 15), 0)
        mask = self.bg_subtractors[camera_id].apply(gray)
        score = cv2.countNonZero(mask)

        # Frame diff fallback
        if self.last_gray[camera_id] is not None:
            diff = cv2.absdiff(self.last_gray[camera_id], gray)
            _, t = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            score = max(score, cv2.countNonZero(t))

        self.last_gray[camera_id] = gray
        return score > adaptive_threshold, score

    def process_frame(self, frame, camera_id="0", frame_uuid=None):
        """Main AI pipeline called by the UI."""
        with self.lock:
            self.stats["total"] += 1

        is_moving, score = self.detect_motion(frame, camera_id)

        res = {
            "frame": frame, "motion_detected": is_moving, "motion_score": score,
            "num_people": 0, "alert_triggered": False, "alerts": [],
            "detections": {"behavior": [], "contraband": []},
            "processing_mode": "Power Saving (No Motion)"
        }

        gate_cfg = get_config("motion_gate")
        movenet_gated = gate_cfg.get("motion_gate_movenet_enabled", True)
        yolo_gated = gate_cfg.get("motion_gate_yolo_enabled", True)

        run_movenet = is_moving or not movenet_gated
        run_yolo = is_moving or not yolo_gated

        if not run_movenet and not run_yolo:
            with self.lock:
                self.stats["skipped"] += 1
            # Return original frame to save memory
            return res

        # Throttling to save laptop heat (max 18 FPS AI)
        now = time.time()
        if now - self.last_run.get(camera_id, 0) < 0.05:
            res["processing_mode"] = "AI Running (Throttled)"
            return res
        self.last_run[camera_id] = now

        # Get active telemetry context
        ctx = None
        if frame_uuid:
            from monitor_app.telemetry import get_telemetry_engine
            ctx = get_telemetry_engine().get_context(frame_uuid)

        # --- FULL AI MODE ---
        res["frame"] = frame.copy()
        mode_str = "AI ACTIVE (RTX GPU Enabled)"
        if not is_moving:
            mode_str = "AI ACTIVE (Ungated Override)"
        res["processing_mode"] = mode_str
        
        with self.lock:
            self.stats["ai_runs"] += 1
            
        if is_moving:
            CapstoneDebug.log(camera_id, f"Significant motion detected ({score} px). Running AI engines...")
        else:
            CapstoneDebug.log(camera_id, f"No motion, but ungated processing active.")

        # 1. Behavior Analysis (MoveNet)
        if self.movenet and run_movenet:
            if ctx:
                ctx.mark("movenet_start")
            with self.tf_inference_lock:
                self._run_movenet_logic(res, camera_id)
            if ctx:
                ctx.mark("movenet_end")

        # 2. Contraband Analysis (Dual YOLO)
        if self.enable_yolo and self.yolo_custom and run_yolo:
            if ctx:
                ctx.mark("yolo_start")
            with self.yolo_inference_lock:
                self._run_yolo_logic(res, camera_id)
            if ctx:
                ctx.mark("yolo_end")

        # Draw Global HUD
        cv2.putText(res["frame"], res["processing_mode"], (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return res



    @staticmethod
    def compute_bbox_from_keypoints(kps, frame_shape):
        """
        Computes the bounding box of a person based on their keypoints.
        kps: (17, 3) where columns are y, x, conf (normalized 0-1)
        frame_shape: (height, width, channels)
        Returns: (x1, y1, x2, y2)
        """
        h, w = frame_shape[:2]
        
        # Filter keypoints by confidence (e.g. > 0.1)
        valid_kps = [kp for kp in kps if kp[2] > 0.1]
        
        if not valid_kps:
            return None

        ys = [kp[0] * h for kp in valid_kps]
        xs = [kp[1] * w for kp in valid_kps]
        
        # Add a bit of padding
        padding_y = h * 0.05
        padding_x = w * 0.05
        
        x1 = max(0, int(min(xs) - padding_x))
        y1 = max(0, int(min(ys) - padding_y))
        x2 = min(w, int(max(xs) + padding_x))
        y2 = min(h, int(max(ys) + padding_y))
        
        return (x1, y1, x2, y2)

    def _run_movenet_logic(self, res, cam_id):
        img_input = cv2.cvtColor(res["frame"], cv2.COLOR_BGR2RGB)
        img_input = cv2.resize(img_input, (256, 256))
        tensor = tf.cast(img_input, dtype=tf.int32)[tf.newaxis, ...]

        try:
            outputs = self.movenet(tensor)
            kpts = outputs["output_0"].numpy()[0]
            
            detected_people = []

            for i in range(6):  # Max 6 people
                person = kpts[i, :51].reshape(17, 3)
                conf = np.mean(person[:, 2])
                if conf > 0.2:
                    hip_l, hip_r = person[11], person[12]
                    hip_centroid = ((hip_l[1] + hip_r[1]) / 2, (hip_l[0] + hip_r[0]) / 2)
                    
                    res["num_people"] += 1
                    self.draw_skeleton(res["frame"], person, i)
                    label, score = self.classify_behavior(person, i, cam_id, res["frame"].shape)

                    detected_people.append({
                        "p_id": i,
                        "hip_centroid": hip_centroid,
                        "kps": person,
                        "label": label,
                        "score": score
                    })

                    tracked_person = TrackedPerson(
                        stable_id=-1,
                        raw_person_id=i,
                        camera_id=cam_id,
                        keypoints=person,
                        bbox=None,
                        hip_centroid=hip_centroid,
                        confidence=float(conf),
                        frame_number=self.stats["total"],
                        timestamp=time.time(),
                    )
                    res.setdefault("tracked_persons", []).append(tracked_person)

                    if label in ("Aggressive / Fighting", "Fast Movement"):
                        res["alert_triggered"] = True
                        res["alerts"].append(f"Person {i + 1}: {label.upper()}")
                        CapstoneDebug.log(cam_id, f"ALERT: Fast/Aggressive motion detected for Person {i + 1}")
            res.setdefault("detections", {"behavior": [], "contraband": []})
            for dp in detected_people:
                res["detections"]["behavior"].append({
                    "person_index": dp["p_id"],
                    "stable_id": -1,
                    "label": dp["label"],
                    "score": dp["score"]
                })
                
        except Exception as e:
            CapstoneDebug.log(cam_id, f"MoveNet inference error: {e}")

    def _run_yolo_logic(self, res, cam_id):
        """
        REFACTORED YOLO LOGIC with Official ByteTrack integration.
        - Run custom YOLO model.
        - Feed detections into camera-specific BYTETracker.
        - Draw bounding boxes with stable Track IDs.
        """
        device = self.yolo_device  # Cached at __init__ via _setup_hardware()
        detections_found = []

        if self.yolo_custom:
            try:
                # Initialize tracker for camera if not present
                if cam_id not in self.yolo_trackers:
                    from ultralytics.utils import IterableSimpleNamespace
                    from ultralytics.trackers.byte_tracker import BYTETracker
                    from monitor_app.tracker_config import TRACKER_CFG
                    args = IterableSimpleNamespace(
                        track_thresh=TRACKER_CFG.get("track_thresh", 0.5),
                        track_buffer=TRACKER_CFG.get("track_buffer", 30),
                        match_thresh=TRACKER_CFG.get("match_thresh", 0.8),
                        frame_rate=TRACKER_CFG.get("frame_rate", 15),
                        track_high_thresh=TRACKER_CFG.get("track_thresh", 0.5),
                        track_low_thresh=0.1,
                        new_track_thresh=TRACKER_CFG.get("track_thresh", 0.5) + 0.1,
                        fuse_score=False
                    )
                    self.yolo_trackers[cam_id] = BYTETracker(args)

                from monitor_app.config import get_config
                inference_imgsz = get_config("yolo", "inference_imgsz", 960)
                
                try:
                    results = self.yolo_custom(res["frame"], verbose=False, imgsz=inference_imgsz, device=device)
                except Exception as e:
                    print(f"[YOLO] CRITICAL: inference failed on active model '{getattr(self, 'active_model_name', 'unknown')}': {e}")
                    print("[YOLO] Attempting emergency fallback to best.pt for this session...")
                    import os
                    model_dir = os.path.join(os.path.dirname(__file__), "models")
                    fallback_path = os.path.join(model_dir, get_config("yolo", "model_path_fallback", "best.pt"))
                    if os.path.exists(fallback_path):
                        self.yolo_custom = YOLO(fallback_path)
                        self.active_model_name = "best.pt (emergency fallback)"
                        results = self.yolo_custom(res["frame"], verbose=False, imgsz=inference_imgsz, device=device)
                    else:
                        results = []

                CLASS_NAMES = {0: "knife", 1: "cellphone"}
                CONF_THRESHOLDS = {
                    0: getattr(self, "yolo_knife_conf", 0.30),
                    1: getattr(self, "yolo_cell_conf", 0.30)
                }
                fallback_thr = getattr(self, "yolo_fallback_conf", 0.50)

                for r in results:
                    if r.boxes is not None and len(r.boxes) > 0:
                        print(f"[YOLO raw] confs: {r.boxes.conf.tolist()}, classes: {r.boxes.cls.tolist()}")
                    
                    # Update ByteTrack with YOLO Boxes
                    tracks = self.yolo_trackers[cam_id].update(r.boxes.cpu(), res["frame"])
                    if len(tracks) > 0:
                        print(f"[BYTETrack Cam {cam_id}] Updated with {len(tracks)} active tracks.")
                    
                    if len(tracks) > 0:
                        from monitor_app.central_inference import get_inference_manager
                        mgr = get_inference_manager()
                        if mgr:
                            mgr.update_active_track_time(cam_id)

                    for track in tracks:
                        x1, y1, x2, y2, track_id, conf, cls_id, idx = track
                        cls_id = int(cls_id)
                        conf = float(conf)
                        track_id = int(track_id)

                        if cls_id in CLASS_NAMES and conf > CONF_THRESHOLDS.get(cls_id, fallback_thr):
                            detections_found.append({
                                "name": CLASS_NAMES[cls_id],
                                "conf": conf,
                                "box": [x1, y1, x2, y2],
                                "track_id": track_id,
                                "source": "combined"
                            })
            except Exception as e:
                CapstoneDebug.log(cam_id, f"Combined YOLO Tracker Error: {e}")

        # 3. Consolidate and Render
        res.setdefault("detections", {"behavior": [], "contraband": []})
        for det in detections_found:
            x1, y1, x2, y2 = map(int, det["box"])
            name = det["name"]
            conf = det["conf"]
            track_id = det["track_id"]

            # Label everything as ALERT with track ID for high urgency
            label_text = f"ALERT: {name.upper()} (ID: {track_id})"
            cv2.rectangle(res["frame"], (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.putText(res["frame"], label_text, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            res["alert_triggered"] = True
            res["alerts"].append(f"CONTRABAND: {name} (ID: {track_id})")
            res["detections"]["contraband"].append({
                "name": name,
                "confidence": conf,
                "box": [x1, y1, x2, y2],
                "track_id": track_id
            })
            CapstoneDebug.log(cam_id, f"CONTRABAND FOUND: {name} ({conf:.2f}) [ID: {track_id}]")

    def classify_behavior(self, kps, p_id, cam_id, frame_shape):
        frame_h, frame_w = frame_shape[:2]
        key = f"{cam_id}_{p_id}"
        scaled = kps[:, :2] * np.array([frame_h, frame_w])
        if key not in self.trackers:
            self.trackers[key] = {'prev': scaled, 'history': [], 'time': time.time()}
            return "Normal", 0.0

        tracker = self.trackers[key]
        dt = time.time() - tracker['time']
        if dt < 0.01: return "Normal", 0.0

        speed = np.linalg.norm(scaled[[7, 8, 9, 10]] - tracker['prev'][[7, 8, 9, 10]], axis=1).mean() / dt
        tracker['prev'] = scaled
        tracker['time'] = time.time()

        tracker['history'].append(speed)
        if len(tracker['history']) > 5: tracker['history'].pop(0)
        avg = np.mean(tracker['history'])

        if avg > self.AGG_THR: return "Aggressive / Fighting", avg
        if avg > self.ACTIVE_THR: return "Fast Movement", avg
        return "Normal", avg

    def draw_skeleton(self, frame, kps, p_id):
        h, w = frame.shape[:2]
        color = [(0, 255, 0), (255, 0, 0), (0, 255, 255)][p_id % 3]
        for y, x, c in kps:
            if c > 0.3: cv2.circle(frame, (int(x * w), int(y * h)), 4, color, -1)
        for p1, p2 in self.EDGES:
            if kps[p1, 2] > 0.3 and kps[p2, 2] > 0.3:
                cv2.line(frame, (int(kps[p1, 1] * w), int(kps[p1, 0] * h)), (int(kps[p2, 1] * w), int(kps[p2, 0] * h)),
                         color, 2)

    def label_person(self, frame, kps, p_id, label, score):
        h, w = frame.shape[:2]
        x, y = int(kps[0, 1] * w), int(kps[0, 0] * h)
        color = (0, 0, 255) if "Aggressive" in label else (255, 255, 255)
        cv2.putText(frame, f"P{p_id + 1}: {label}", (x, y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    def get_stats(self):
        return self.stats

    def reset_tracker(self, cam_id=None):
        self.trackers = {}
        if cam_id is not None:
            if cam_id in self.yolo_trackers:
                del self.yolo_trackers[cam_id]
        else:
            self.yolo_trackers = {}
        CapstoneDebug.log(cam_id or "All", "Trackers reset to baseline.")
