import cv2
import os
import numpy as np
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
        self.yolo_hysteresis = {}  # cam_id -> {cls_id: {"conf": float, "box": list, "ttl": int}}
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
            self.CONF_THR = 0.28
            self.AGG_THR = 0.08  # Normalized (8% of frame width/sec)
            self.ACTIVE_THR = 0.04
            self.ALERT_FRAMES = 4
            self.motion_threshold = 4500
            self.motion_ratio = 0.009
            self.yolo_knife_conf = 0.30
            self.yolo_cell_conf = 0.30
            self.yolo_fallback_conf = 0.50
        elif level == "low":
            self.CONF_THR = 0.38
            self.AGG_THR = 0.15
            self.ACTIVE_THR = 0.08
            self.ALERT_FRAMES = 8
            self.motion_threshold = 6000
            self.motion_ratio = 0.012
            self.yolo_knife_conf = 0.40
            self.yolo_cell_conf = 0.40
            self.yolo_fallback_conf = 0.60
        elif level == "custom" and custom_values:
            self.CONF_THR = float(custom_values.get("conf_thr", 0.22))
            self.AGG_THR = float(custom_values.get("agg_thr", 0.10))
            self.ACTIVE_THR = float(custom_values.get("active_thr", 0.05))
            self.ALERT_FRAMES = int(custom_values.get("alert_frames", 3))
            self.motion_threshold = int(custom_values.get("motion_threshold", 5000))
            self.motion_ratio = float(custom_values.get("motion_ratio", 0.010))
            self.yolo_knife_conf = float(custom_values.get("yolo_knife_conf", 0.30))
            self.yolo_cell_conf = float(custom_values.get("yolo_cell_conf", 0.30))
            self.yolo_fallback_conf = float(custom_values.get("yolo_fallback_conf", 0.50))
        else:  # medium (default)
            self.CONF_THR = 0.32
            self.AGG_THR = 0.10
            self.ACTIVE_THR = 0.05
            self.ALERT_FRAMES = 6
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

    def process_frame(self, frame, camera_id="0", frame_uuid=None, motion_pre_detected=None):
        """Main AI pipeline called by the inference queue.
        
        Args:
            motion_pre_detected: If not None, skip redundant motion detection
                                and use this value directly (already computed by LocalMotionGater).
        """
        with self.lock:
            self.stats["total"] += 1

        # Use pre-computed motion if available, otherwise compute
        if motion_pre_detected is not None:
            is_moving = motion_pre_detected
            score = 0  # score not needed when pre-detected
        else:
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
            return res

        # Get active telemetry context
        ctx = None
        if frame_uuid:
            from monitor_app.telemetry import get_telemetry_engine
            ctx = get_telemetry_engine().get_context(frame_uuid)

        # --- FULL AI MODE (no throttle — queue provides natural backpressure) ---
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

        # 2. Contraband Analysis (YOLO)
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

    def run_movenet_only(self, frame, camera_id="0"):
        """Run only MoveNet inference (CPU-bound). Thread-safe.
        Returns partial result dict with behavior detections."""
        res = {
            "frame": frame, "num_people": 0, "alert_triggered": False,
            "alerts": [], "detections": {"behavior": [], "contraband": []},
            "tracked_persons": [],
        }
        if self.movenet:
            with self.tf_inference_lock:
                self._run_movenet_logic(res, camera_id)
        return res

    def run_yolo_only(self, frame, camera_id="0"):
        """Run only YOLO inference (GPU-bound). Thread-safe.
        Returns partial result dict with contraband detections."""
        res = {
            "frame": frame, "num_people": 0, "alert_triggered": False,
            "alerts": [], "detections": {"behavior": [], "contraband": []},
        }
        if self.enable_yolo and self.yolo_custom:
            with self.yolo_inference_lock:
                self._run_yolo_logic(res, camera_id)
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
            
            raw_detected = []
            for i in range(6):  # Max 6 people
                person = kpts[i, :51].reshape(17, 3)
                conf = np.mean(person[:, 2])
                if conf > self.CONF_THR:
                    # Structural validity: require minimum keypoints AND core body visibility
                    valid_kps = [kp for kp in person if kp[2] > 0.25]
                    n_valid = len(valid_kps)
                    has_shoulders = person[5, 2] > 0.25 and person[6, 2] > 0.25
                    has_hips = person[11, 2] > 0.25 and person[12, 2] > 0.25
                    
                    # Ghost filter: need at least 5 valid keypoints AND at least one body pair
                    if n_valid < 5 or (not has_shoulders and not has_hips):
                        continue

                    # Robust centroid calculation to prevent ID swaps due to occluded hips
                    if has_hips:
                        hip_centroid = ((person[11, 1] + person[12, 1]) / 2, (person[11, 0] + person[12, 0]) / 2)
                    elif has_shoulders:
                        hip_centroid = ((person[5, 1] + person[6, 1]) / 2, (person[5, 0] + person[6, 0]) / 2)
                    else:
                        xs = [kp[1] for kp in valid_kps]
                        ys = [kp[0] for kp in valid_kps]
                        hip_centroid = (float(np.mean(xs)), float(np.mean(ys)))

                    raw_detected.append((person, i, hip_centroid, conf))

            # NMS: suppress duplicate detections of the same person (split detections)
            # If two detections have centroids within 15% of frame width, keep the higher-confidence one
            frame_h, frame_w = res["frame"].shape[:2]
            nms_threshold_px = 0.15 * frame_w
            suppressed = set()
            for i_det in range(len(raw_detected)):
                if i_det in suppressed:
                    continue
                for j_det in range(i_det + 1, len(raw_detected)):
                    if j_det in suppressed:
                        continue
                    cx_i, cy_i = raw_detected[i_det][2]
                    cx_j, cy_j = raw_detected[j_det][2]
                    dist_px = (((cx_i - cx_j) * frame_w) ** 2 + ((cy_i - cy_j) * frame_h) ** 2) ** 0.5
                    if dist_px < nms_threshold_px:
                        # Suppress the lower-confidence detection
                        if raw_detected[i_det][3] >= raw_detected[j_det][3]:
                            suppressed.add(j_det)
                        else:
                            suppressed.add(i_det)
                            break  # i_det is suppressed, no need to check further

            raw_detected = [d for idx, d in enumerate(raw_detected) if idx not in suppressed]

            # Resolve stable IDs using the global behavior engine's tracker to stay in sync
            from monitor_app.behaviors import get_behavior_engine
            tracker = get_behavior_engine()._get_tracker(cam_id)
            
            tracked_list = []
            for person, raw_id, hip_centroid, conf in raw_detected:
                tp = TrackedPerson(
                    stable_id=-1,
                    raw_person_id=raw_id,
                    camera_id=cam_id,
                    keypoints=person,
                    bbox=None,
                    hip_centroid=hip_centroid,
                    confidence=float(conf),
                    frame_number=self.stats["total"],
                    timestamp=time.time(),
                )
                tracked_list.append(tp)

            if tracked_list:
                tracker.update(tracked_list, self.stats["total"])

            detected_people = []
            for tp in tracked_list:
                person = tp.keypoints
                stable_id = tp.stable_id
                raw_id = tp.raw_person_id
                
                res["num_people"] += 1
                self.draw_skeleton(res["frame"], person, stable_id)
                label, score = self.classify_behavior(person, stable_id, cam_id, res["frame"].shape)

                detected_people.append({
                    "p_id": raw_id,
                    "stable_id": stable_id,
                    "hip_centroid": tp.hip_centroid,
                    "kps": person,
                    "label": label,
                    "score": score
                })
                
                res.setdefault("tracked_persons", []).append(tp)

                if label in ("Aggressive / Fighting", "Fast Movement"):
                    res["alert_triggered"] = True
                    res["alerts"].append(f"Person {stable_id + 1}: {label.upper()}")
                    CapstoneDebug.log(cam_id, f"ALERT: Fast/Aggressive motion detected for Person {stable_id + 1}")

            res.setdefault("detections", {"behavior": [], "contraband": []})
            for dp in detected_people:
                res["detections"]["behavior"].append({
                    "person_index": dp["p_id"],
                    "stable_id": dp["stable_id"],
                    "label": dp["label"],
                    "score": dp["score"]
                })
                
        except Exception as e:
            CapstoneDebug.log(cam_id, f"MoveNet inference error: {e}")

    def _run_yolo_logic(self, res, cam_id):
        """
        YOLO LOGIC with ByteTrack.
        - Run custom YOLO model with tracking enabled.
        - Extract boxes and tracking IDs directly.
        """
        device = self.yolo_device  # Cached at __init__ via _setup_hardware()
        detections_found = []

        if self.yolo_custom:
            try:
                from monitor_app.config import get_config
                inference_imgsz = get_config("yolo", "inference_imgsz", 960)
                
                try:
                    results = self.yolo_custom.track(res["frame"], persist=True, verbose=False, imgsz=inference_imgsz, device=device)
                except Exception as e:
                    print(f"[YOLO] CRITICAL: tracking failed on active model '{getattr(self, 'active_model_name', 'unknown')}': {e}")
                    import os
                    model_dir = os.path.join(os.path.dirname(__file__), "models")
                    fallback_path = os.path.join(model_dir, get_config("yolo", "model_path_fallback", "best.pt"))
                    if os.path.exists(fallback_path) and not getattr(self, '_yolo_is_reloading', False):
                        self._yolo_is_reloading = True
                        print("[YOLO] Flagging degraded state. Starting background reload to avoid blocking inference...")
                        def _bg_reload():
                            try:
                                print(f"[YOLO-BG] Loading fallback model from {fallback_path}...")
                                new_model = YOLO(fallback_path)
                                self.yolo_custom = new_model
                                self.active_model_name = "best.pt (emergency fallback)"
                                print("[YOLO-BG] Background reload complete. Tracking restored.")
                            except Exception as reload_err:
                                print(f"[YOLO-BG] Background reload failed: {reload_err}")
                            finally:
                                self._yolo_is_reloading = False
                        import threading
                        threading.Thread(target=_bg_reload, daemon=True).start()
                    results = []

                CLASS_NAMES = {0: "knife", 1: "cellphone"}
                CONF_THRESHOLDS = {
                    0: getattr(self, "yolo_knife_conf", 0.30),
                    1: getattr(self, "yolo_cell_conf", 0.30)
                }
                fallback_thr = getattr(self, "yolo_fallback_conf", 0.50)

                for r in results:
                    if r.boxes is None or len(r.boxes) == 0:
                        continue
                        
                    # Update active track time to keep motion gate open if detections exist
                    from monitor_app.central_inference import get_inference_manager
                    mgr = get_inference_manager()
                    if mgr:
                        mgr.update_active_track_time(cam_id)

                    current_det_keys = set()
                    for box in r.boxes:
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        track_id = int(box.id[0]) if box.id is not None else -1

                        if cls_id in CLASS_NAMES and conf > CONF_THRESHOLDS.get(cls_id, fallback_thr):
                            # Generate unique key to prevent overwrite collisions
                            cache_key = track_id if track_id != -1 else f"untracked_{cls_id}_{x1}_{y1}"
                            current_det_keys.add(cache_key)
                            
                            # Update hysteresis cache
                            if cam_id not in self.yolo_hysteresis:
                                self.yolo_hysteresis[cam_id] = {}
                            
                            self.yolo_hysteresis[cam_id][cache_key] = {
                                "conf": conf,
                                "box": [x1, y1, x2, y2],
                                "track_id": track_id,
                                "cls_id": cls_id,
                                "ttl": 5  # Persist for 5 frames
                            }

                            detections_found.append({
                                "name": CLASS_NAMES[cls_id],
                                "conf": conf,
                                "box": [x1, y1, x2, y2],
                                "track_id": track_id,
                                "source": "combined"
                            })
                            
                    # Apply hysteresis for missing detections
                    if cam_id in self.yolo_hysteresis:
                        for key in list(self.yolo_hysteresis[cam_id].keys()):
                            if key not in current_det_keys:
                                data = self.yolo_hysteresis[cam_id][key]
                                data["ttl"] -= 1
                                if data["ttl"] <= 0:
                                    del self.yolo_hysteresis[cam_id][key]
                                else:
                                    detections_found.append({
                                        "name": CLASS_NAMES[data["cls_id"]],
                                        "conf": data["conf"],
                                        "box": data["box"],
                                        "track_id": data["track_id"],
                                        "source": "combined_hysteresis"
                                    })
            except Exception as e:
                CapstoneDebug.log(cam_id, f"Combined YOLO Error: {e}")

        # 3. Consolidate (No Rendering)
        res.setdefault("detections", {"behavior": [], "contraband": []})
        for det in detections_found:
            x1, y1, x2, y2 = map(int, det["box"])
            name = det["name"]
            conf = det["conf"]
            track_id = det["track_id"]

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
        coords = kps[:, :2] * np.array([frame_h, frame_w])
        confs = kps[:, 2]

        if key not in self.trackers:
            self.trackers[key] = {
                'prev_coords': coords,
                'prev_confs': confs,
                'smoothed_coords': coords.copy(),
                'history': [],
                'alert_count': 0,
                'time': time.time()
            }
            return "Normal", 0.0

        tracker = self.trackers[key]
        dt = time.time() - tracker['time']
        if dt < 0.01: return "Normal", 0.0

        # Reset tracker if gap is too large to prevent velocity spikes from tracking gaps/reappearance
        if dt > 0.15:
            tracker['prev_coords'] = coords
            tracker['prev_confs'] = confs
            tracker['smoothed_coords'] = coords.copy()
            tracker['time'] = time.time()
            tracker['alert_count'] = 0
            tracker['history'] = []
            return "Normal", 0.0

        # Apply EMA coordinate smoothing to filter keypoint jitter
        alpha = 0.4
        for idx in range(len(coords)):
            if confs[idx] > 0.25:
                tracker['smoothed_coords'][idx] = (
                    alpha * coords[idx] + (1 - alpha) * tracker['smoothed_coords'][idx]
                )
        coords = tracker['smoothed_coords']

        def _joint_speed(indices):
            speeds = []
            for idx in indices:
                if confs[idx] > 0.25 and tracker['prev_confs'].shape[0] > idx and tracker['prev_confs'][idx] > 0.25:
                    dist = np.linalg.norm(coords[idx] - tracker['prev_coords'][idx])
                    # Deadband (soft threshold) of 0.4% frame width (~7.6px for 1080p) to suppress jitter
                    dist_clean = max(0.0, dist - 0.004 * frame_w)
                    speeds.append(dist_clean / dt)
            return np.mean(speeds) if speeds else None

        # PRIMARY: torso speed (shoulders 5,6 + hips 11,12) = body translation
        torso_speed = _joint_speed([5, 6, 11, 12])
        # SECONDARY: limb speed (elbows 7,8 + wrists 9,10) = arm motion
        limb_speed = _joint_speed([7, 8, 9, 10])

        if torso_speed is not None:
            body_speed = torso_speed / frame_w  # Normalize by frame width
        else:
            body_speed = 0.0

        # Limb excess: how much faster are limbs moving vs body translation?
        if limb_speed is not None and torso_speed is not None and torso_speed > 0:
            limb_excess = (limb_speed - torso_speed) / frame_w
        elif limb_speed is not None:
            limb_excess = limb_speed / frame_w
        else:
            limb_excess = 0.0

        # Combined metric: body speed + weighted limb excess
        aggression_score = body_speed + max(0.0, limb_excess) * 0.5

        tracker['prev_coords'] = coords.copy()
        tracker['prev_confs'] = confs
        tracker['time'] = time.time()

        tracker['history'].append(aggression_score)
        if len(tracker['history']) > 8: tracker['history'].pop(0)
        avg = np.mean(tracker['history'])

        # Consecutive-frame gate: require ALERT_FRAMES sustained readings before escalating
        if avg > self.ACTIVE_THR:
            tracker['alert_count'] = tracker.get('alert_count', 0) + 1
        else:
            tracker['alert_count'] = 0

        if tracker['alert_count'] < self.ALERT_FRAMES:
            return "Normal", avg

        if avg > self.AGG_THR: return "Aggressive / Fighting", avg
        return "Fast Movement", avg

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
