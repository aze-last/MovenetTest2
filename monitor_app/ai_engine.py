import cv2
import numpy as np
import os
import time
import threading
from collections import deque
from datetime import datetime
from PIL import Image


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

    def process_frame(self, frame, camera_id="0"):
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
        
        # Concealment feature - separate stable-ID tracking layer (hip-centroid matching)
        # Does NOT touch self.trackers (used by classify_behavior)
        self.concealment_trackers = {}
        self.CONCEALMENT_MAX_MATCH_DIST = 80.0   # px, tune based on your frame resolution
        self.CONCEALMENT_GRACE_FRAMES = 5        # frames a person can vanish before dropped
        
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
            # 1. Load Custom Model (best.pt)
            print("Combined model (knife+cellphone) loaded from best.pt")
            try:
                model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
                if os.path.exists(model_path):
                    self.yolo_custom = YOLO(model_path)
                else:
                    print(f"Custom model not found at {model_path}")
            except Exception as e:
                print(f"Custom YOLO load failed: {e}")

            print("Combined model (knife + cellphone) loaded from best.pt")

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

    def process_frame(self, frame, camera_id="0"):
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

        if not is_moving:
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

        # --- FULL AI MODE ---
        res["frame"] = frame.copy()
        res["processing_mode"] = "AI ACTIVE (RTX GPU Enabled)"
        with self.lock:
            self.stats["ai_runs"] += 1
        CapstoneDebug.log(camera_id, f"Significant motion detected ({score} px). Running AI engines...")

        # 1. Behavior Analysis (MoveNet)
        if self.movenet:
            with self.tf_inference_lock:
                self._run_movenet_logic(res, camera_id)

        # 2. Contraband Analysis (Dual YOLO)
        if self.enable_yolo and self.yolo_custom:
            with self.yolo_inference_lock:
                self._run_yolo_logic(res, camera_id)

        # Draw Global HUD
        cv2.putText(res["frame"], res["processing_mode"], (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return res

    def _match_concealment_ids(self, cam_id, detected_people):
        """
        detected_people: list of dicts, one per detected person this frame:
            [{"p_id": <raw movenet index>, "hip_centroid": (x, y), "kps": person_array}, ...]
        Returns: list of same dicts, each with an added "stable_id" key.
        """
        if cam_id not in self.concealment_trackers:
            self.concealment_trackers[cam_id] = {"next_id": 0, "people": {}}

        cam_tracker = self.concealment_trackers[cam_id]
        existing = cam_tracker["people"]
        matched_stable_ids = set()

        for person in detected_people:
            cx, cy = person["hip_centroid"]
            best_id = None
            best_dist = self.CONCEALMENT_MAX_MATCH_DIST

            for stable_id, data in existing.items():
                if stable_id in matched_stable_ids:
                    continue  # already claimed this frame
                ex, ey = data["hip_centroid"]
                dist = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_id = stable_id

            if best_id is not None:
                # Matched to an existing tracked person
                person["stable_id"] = best_id
                existing[best_id]["hip_centroid"] = (cx, cy)
                existing[best_id]["last_seen_frame"] = self.stats["total"]
                matched_stable_ids.add(best_id)
            else:
                # New person - assign fresh stable_id
                new_id = cam_tracker["next_id"]
                cam_tracker["next_id"] += 1
                existing[new_id] = {
                    "hip_centroid": (cx, cy),
                    "last_seen_frame": self.stats["total"],
                    "left_wrist_missing_since": None,
                    "right_wrist_missing_since": None,
                    "concealment_flagged": False,
                    "cooldown_until_frame": 0,
                }
                person["stable_id"] = new_id
                matched_stable_ids.add(new_id)

        # Drop stale entries (not seen within grace period)
        current_frame = self.stats["total"]
        stale_ids = [
            sid for sid, data in existing.items()
            if current_frame - data["last_seen_frame"] > self.CONCEALMENT_GRACE_FRAMES
        ]
        for sid in stale_ids:
            del existing[sid]

        return detected_people

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
                    self.label_person(res["frame"], person, i, label, score)

                    detected_people.append({
                        "p_id": i,
                        "hip_centroid": hip_centroid,
                        "kps": person,
                        "label": label,
                        "score": score
                    })

                    if label in ("Aggressive / Fighting", "Fast Movement"):
                        res["alert_triggered"] = True
                        res["alerts"].append(f"Person {i + 1}: {label.upper()}")
                        CapstoneDebug.log(cam_id, f"ALERT: Fast/Aggressive motion detected for Person {i + 1}")
                        
            detected_people = self._match_concealment_ids(cam_id, detected_people)
            res.setdefault("detections", {"behavior": [], "contraband": []})
            for dp in detected_people:
                res["detections"]["behavior"].append({
                    "person_index": dp["p_id"],
                    "stable_id": dp["stable_id"],
                    "label": dp["label"],
                    "score": dp["score"]
                })
                CapstoneDebug.log(cam_id, f"Stable ID Test -> p_id: {dp['p_id']} mapped to stable_id: {dp['stable_id']}")
                
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
                    args = IterableSimpleNamespace(
                        track_thresh=0.25,
                        track_buffer=30,
                        match_thresh=0.8,
                        frame_rate=30,
                        track_high_thresh=0.5,
                        track_low_thresh=0.1,
                        new_track_thresh=0.6,
                        fuse_score=False
                    )
                    self.yolo_trackers[cam_id] = BYTETracker(args)

                results = self.yolo_custom(res["frame"], verbose=False, imgsz=640, device=device)
                CLASS_NAMES = {0: "knife", 1: "cellphone"}
                CONF_THRESHOLDS = {
                    0: getattr(self, "yolo_knife_conf", 0.30),
                    1: getattr(self, "yolo_cell_conf", 0.30)
                }
                fallback_thr = getattr(self, "yolo_fallback_conf", 0.50)

                for r in results:
                    # Update ByteTrack with YOLO Boxes
                    tracks = self.yolo_trackers[cam_id].update(r.boxes, res["frame"])
                    
                    # Update active track time in central inference manager for hysteresis gating
                    if len(tracks) > 0:
                        from monitor_app.central_inference import get_inference_manager
                        get_inference_manager().update_active_track_time(cam_id)

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
