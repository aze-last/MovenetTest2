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
from monitor_app.utils import resource_path


def get_models_dir():
    """
    Returns absolute path to models directory.
    Checks resource_path (for PyInstaller bundle / dev root) first,
    falling back to module-local models directory.
    """
    candidate = resource_path(os.path.join("monitor_app", "models"))
    if os.path.exists(candidate):
        return candidate
    local_candidate = os.path.join(os.path.dirname(__file__), "models")
    return local_candidate


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
ONNX_AVAILABLE = False
YOLO_AVAILABLE = False

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except Exception as e:
    import traceback
    traceback.print_exc()

if not ONNX_AVAILABLE:
    print("onnxruntime not available; MoveNet disabled.")

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

class DynamicContrabandTracker:
    """
    Per-camera dynamic contraband tracker with IoU and spatial proximity association.
    Assigns a stable, monotonic track ID to sustained contraband detections.
    When an object leaves the field of view and another object appears,
    a NEW unique track ID is allocated (e.g. 1001, 1002, 1003...).
    This prevents operator dismissals of one object (e.g. vape/glare) from colliding
    with subsequent real objects (e.g. phone) presented in the same field of view.
    """
    def __init__(self, iou_thresh: float = 0.25, max_lost_frames: int = 15):
        import threading
        self.iou_thresh = iou_thresh
        self.max_lost_frames = max_lost_frames
        self.lock = threading.Lock()
        self._next_track_id = 1001
        # cam_id -> {track_id: {"box": list, "score": float, "cls_id": int, "lost_count": int}}
        self.camera_tracks = {}

    @staticmethod
    def _calc_iou(box_a, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def update(self, camera_id, boxes, scores, class_ids):
        cam_str = str(camera_id)
        with self.lock:
            if cam_str not in self.camera_tracks:
                self.camera_tracks[cam_str] = {}
            active_tracks = self.camera_tracks[cam_str]

            matched_track_ids = set()
            results = []

            for box, score, cls_id in zip(boxes, scores, class_ids):
                best_match_id = None
                best_iou = self.iou_thresh

                for tid, trk in active_tracks.items():
                    if tid in matched_track_ids or trk["cls_id"] != cls_id:
                        continue
                    iou = self._calc_iou(box, trk["box"])
                    if iou > best_iou:
                        best_iou = iou
                        best_match_id = tid

                # Centroid proximity fallback if box shifted rapidly (within 60 px)
                # CRITICAL: Only allow centroid fallback if the candidate track was seen
                # recently (lost_count == 0). Do NOT allow a newly appeared object to
                # hijack a dead, lost, or dismissed track!
                if best_match_id is None:
                    bx_c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                    best_dist = 60.0
                    for tid, trk in active_tracks.items():
                        if tid in matched_track_ids or trk["cls_id"] != cls_id:
                            continue
                        if trk.get("lost_count", 0) > 0:
                            continue  # Do not resurrect lost/dismissed tracks via distance
                        tx_c = ((trk["box"][0] + trk["box"][2]) / 2, (trk["box"][1] + trk["box"][3]) / 2)
                        dist = ((bx_c[0] - tx_c[0])**2 + (bx_c[1] - tx_c[1])**2)**0.5
                        if dist < best_dist:
                            best_dist = dist
                            best_match_id = tid

                if best_match_id is not None:
                    active_tracks[best_match_id]["box"] = box
                    active_tracks[best_match_id]["score"] = score
                    active_tracks[best_match_id]["lost_count"] = 0
                    matched_track_ids.add(best_match_id)
                    assigned_id = best_match_id
                else:
                    assigned_id = self._next_track_id
                    self._next_track_id += 1
                    active_tracks[assigned_id] = {
                        "box": box,
                        "score": score,
                        "cls_id": cls_id,
                        "lost_count": 0
                    }
                    matched_track_ids.add(assigned_id)

                results.append({
                    "track_id": assigned_id,
                    "box": box,
                    "score": score,
                    "conf": score,
                    "confidence": score,
                    "cls_id": cls_id
                })

            # Age unmatched tracks
            dead_tids = []
            for tid, trk in active_tracks.items():
                if tid not in matched_track_ids:
                    trk["lost_count"] += 1
                    if trk["lost_count"] >= self.max_lost_frames:
                        dead_tids.append(tid)

            for tid in dead_tids:
                del active_tracks[tid]

            return results


class MotionOptimizedEngine:
    """
    Capstone Grade AI Engine.
    Combines: MoveNet (Logic) + YOLO26s (Objects/Pose Fallback)
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
        self.active_model_path = None  # absolute path of the loaded contraband model (for per-camera clones)
        # Phase B1: per-camera YOLO instances for isolated ByteTrack state (cam_id -> YOLO)
        self.yolo_per_cam = {}
        self._tracker_yaml_path = None  # generated bytetrack YAML (Phase B3), lazily built once

        # Performance/Audit
        self.lock = threading.Lock()
        self.tf_inference_lock = threading.Lock()
        self.yolo_inference_lock = threading.Lock()
        self.stats = {"total": 0, "ai_runs": 0, "skipped": 0}
        self.trackers = {}
        self.yolo_trackers = {}
        self.yolo_hysteresis = {}
        self.contraband_tracker = DynamicContrabandTracker()  # cam_id -> {cls_id: {"conf": float, "box": list, "ttl": int}}
        self.last_run = {}  # For throttling
        self.flicker_trace = bool(get_config("debug", "flicker_trace", False))  # Phase A diagnostic gate

        custom_vals = custom_values if custom_values is not None else kwargs.get("custom_values")
        self._set_logic_sensitivity(sensitivity, custom_vals)
        self._setup_hardware()
        self._load_models()

        # Skeletal Edges (MoveNet standard - without face-slashing diagonal edges)
        self.EDGES = [(0, 1), (0, 2), (1, 3), (2, 4), (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11),
                      (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]

    def _set_logic_sensitivity(self, level, custom_values=None):
        if level == "high":
            self.CONF_THR = 0.06
            self.AGG_THR = 0.08  # Normalized (8% of frame width/sec)
            self.ACTIVE_THR = 0.04
            self.ALERT_FRAMES = 2
            self.motion_threshold = 1200
            self.motion_ratio = 0.005
            self.yolo_knife_conf = 0.30
            self.yolo_cell_conf = 0.30
            self.yolo_fallback_conf = 0.50
        elif level == "low":
            self.CONF_THR = 0.12
            self.AGG_THR = 0.15
            self.ACTIVE_THR = 0.08
            self.ALERT_FRAMES = 5
            self.motion_threshold = 3000
            self.motion_ratio = 0.012
            self.yolo_knife_conf = 0.40
            self.yolo_cell_conf = 0.40
            self.yolo_fallback_conf = 0.60
        elif level == "custom" and custom_values:
            self.CONF_THR = float(custom_values.get("conf_thr", 0.08))
            raw_agg = float(custom_values.get("agg_thr", 0.10))
            self.AGG_THR = raw_agg if raw_agg <= 1.0 else (raw_agg / 1000.0)
            raw_act = float(custom_values.get("active_thr", 0.05))
            self.ACTIVE_THR = raw_act if raw_act <= 1.0 else (raw_act / 1000.0)
            self.ALERT_FRAMES = int(custom_values.get("alert_frames", 3))
            self.motion_threshold = int(custom_values.get("motion_threshold", 1800))
            self.motion_ratio = float(custom_values.get("motion_ratio", 0.008))
            self.yolo_knife_conf = float(custom_values.get("yolo_knife_conf", 0.30))
            self.yolo_cell_conf = float(custom_values.get("yolo_cell_conf", 0.30))
            self.yolo_fallback_conf = float(custom_values.get("yolo_fallback_conf", 0.50))
        else:  # medium (default)
            self.CONF_THR = 0.08
            self.AGG_THR = 0.10
            self.ACTIVE_THR = 0.05
            self.ALERT_FRAMES = 3
            self.motion_threshold = 1800
            self.motion_ratio = 0.008
            self.yolo_knife_conf = 0.30
            self.yolo_cell_conf = 0.30
            self.yolo_fallback_conf = 0.50

    def apply_profile(self, level, custom_values=None):
        """Hot-reload thresholds on a running engine without reinit."""
        with self.lock:
            self._set_logic_sensitivity(level, custom_values)
            print(f"--- AI ENGINE: Profile switched to '{level}' (CONF_THR={self.CONF_THR:.2f}) ---")

    def _setup_hardware(self):
        """Enable GPU for YOLO26s and force CPU for MoveNet to conserve VRAM."""
        # --- MoveNet / ONNX (Forced CPU) ---
        if ONNX_AVAILABLE:
            print("MoveNet: ONNX Runtime CPU execution")
            CapstoneDebug.log("All", "MoveNet running on CPU via ONNX Runtime")
        else:
            print("MoveNet: ONNX unavailable — skipped")

        # --- YOLO26s / PyTorch ---
        if YOLO_AVAILABLE:
            if torch.cuda.is_available():
                self.yolo_device = 0  # GPU index
                print(f" YOLO26s: GPU Accelerated — {torch.cuda.get_device_name(0)}")
            else:
                self.yolo_device = 'cpu'
                print("YOLO26s: No CUDA GPU detected — running on CPU")
        else:
            self.yolo_device = 'cpu'
            print("YOLO26s: Ultralytics/PyTorch unavailable — skipped")

    def _load_models(self):
        """Clean modular loading for explanation."""
        model_dir = get_models_dir()
        if ONNX_AVAILABLE:
            print("Loading MoveNet MultiPose (behavior engine)...")
            try:
                model_path = os.path.join(model_dir, "movenet_multipose.onnx")
                if os.path.exists(model_path):
                    self.movenet = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                    print(f"MoveNet loaded from ONNX path: {model_path}")
                else:
                    print(f"MoveNet skipped: ONNX model missing at {model_path}")
            except Exception as e:
                print(f"MoveNet load failed: {e}")
        else:
            print("MoveNet skipped: ONNX unavailable.")

        if self.enable_yolo:
            from monitor_app.config import get_config

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
                    self.active_model_path = candidate_path  # Phase B1: source path for per-camera clones
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

    def process_frame(self, frame, camera_id="0", frame_uuid=None, motion_pre_detected=None, frame_index=None):
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
            "processing_mode": "Power Saving (No Motion)",
            "frame_index": frame_index
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

    def run_movenet_only(self, frame, camera_id="0", frame_index=None, draw=True):
        """Run only MoveNet inference (CPU-bound). Thread-safe.
        Returns partial result dict with behavior detections.

        draw=False skips skeleton rendering inside the inference pass. The async
        parallel path (central_inference._run_parallel_inference) passes a frame COPY
        whose pixels are discarded after keypoint extraction — drawing on it was dead
        work on the CPU-bound MoveNet thread. The final visible skeleton is drawn by
        central_inference._render_person_boxes on the real output frame. (RC-4; the
        call is flag-gated rather than removed so the synchronous process_frame path
        keeps its original behavior — see implementation_plan.md.)"""
        res = {
            "frame": frame, "num_people": 0, "alert_triggered": False,
            "alerts": [], "detections": {"behavior": [], "contraband": []},
            "tracked_persons": [],
            "frame_index": frame_index
        }
        if self.movenet:
            with self.tf_inference_lock:
                self._run_movenet_logic(res, camera_id, draw=draw)
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
    def compute_bbox_from_keypoints(kps, frame_shape, min_conf=None):
        """
        Computes the bounding box of a person based on their keypoints.
        kps: (17, 3) where columns are y, x, conf (normalized 0-1)
        frame_shape: (height, width, channels)
        min_conf: keypoint confidence floor; defaults to config movenet.bbox_kp_conf (0.1).
        Returns: (x1, y1, x2, y2)
        """
        h, w = frame_shape[:2]

        # Phase C2: threshold externalized to config (Rule 7); default preserves prior 0.1.
        if min_conf is None:
            min_conf = get_config("movenet", "bbox_kp_conf", 0.1)
        valid_kps = [kp for kp in kps if kp[2] > min_conf]

        if not valid_kps:
            return None

        ys = [kp[0] * h for kp in valid_kps]
        xs = [kp[1] * w for kp in valid_kps]
        
        # Add a bit of padding (configurable, default 0.075 for clean framing and no pixel crowding)
        pad_pct = float(get_config("movenet", "bbox_padding_pct", 0.075))
        padding_y = h * pad_pct
        padding_x = w * pad_pct
        
        x1 = max(0, int(min(xs) - padding_x))
        y1 = max(0, int(min(ys) - padding_y))
        x2 = min(w, int(max(xs) + padding_x))
        y2 = min(h, int(max(ys) + padding_y))
        
        return (x1, y1, x2, y2)

    def _run_movenet_logic(self, res, cam_id, draw=True):
        img_input = cv2.cvtColor(res["frame"], cv2.COLOR_BGR2RGB)
        img_input = cv2.resize(img_input, (256, 256))
        input_data = np.expand_dims(img_input, axis=0).astype(np.int32)

        try:
            input_name = self.movenet.get_inputs()[0].name
            outputs = self.movenet.run(None, {input_name: input_data})
            kpts = outputs[0][0]

            # Phase C2: MoveNet gate thresholds externalized to config (Rule 7).
            # Defaults preserve prior in-code behavior exactly (0.25 gate, min 5 keypoints).
            mv_cfg = get_config("movenet") or {}
            ghost_kp_conf = float(mv_cfg.get("ghost_kp_conf", 0.25))
            ghost_min_kp = int(mv_cfg.get("ghost_min_keypoints", 5))
            ghost_min_torso = int(mv_cfg.get("ghost_min_torso_keypoints", 2))

            raw_detected = []
            for i in range(6):  # Max 6 people
                person = kpts[i, :51].reshape(17, 3)
                conf = np.mean(person[:, 2])
                if conf > self.CONF_THR:
                    # Structural validity: require minimum keypoints AND core body visibility
                    valid_kps = [kp for kp in person if kp[2] > ghost_kp_conf]
                    n_valid = len(valid_kps)
                    has_shoulders = person[5, 2] > ghost_kp_conf and person[6, 2] > ghost_kp_conf
                    has_hips = person[11, 2] > ghost_kp_conf and person[12, 2] > ghost_kp_conf
                    # Count visible torso anchors (L/R shoulder, L/R hip). Requiring N of these
                    # instead of a COMPLETE pair stops a single shoulder-keypoint dip from
                    # collapsing the detection (the dominant flicker cause on occluded subjects).
                    torso_count = sum(1 for idx in (5, 6, 11, 12) if person[idx, 2] > ghost_kp_conf)
                    passed = self._passes_ghost_filter(n_valid, torso_count, ghost_min_kp, ghost_min_torso)

                    # Phase A3: ghost-gate trace — shows which gate oscillates near threshold
                    if self.flicker_trace:
                        print(f"[FLICKER-A3] cam={cam_id} fidx={res.get('frame_index')} slot={i} "
                              f"mean_conf={float(conf):.3f} n_valid={n_valid} torso={torso_count} "
                              f"has_sh={has_shoulders} has_hip={has_hips} "
                              f"L_sh={float(person[5,2]):.3f} R_sh={float(person[6,2]):.3f} "
                              f"pass={passed}", flush=True)

                    # Ghost filter: need >= ghost_min_kp valid keypoints AND >= ghost_min_torso
                    # of the 4 torso anchors visible.
                    if not passed:
                        continue

                    # Robust centroid calculation to prevent ID swaps due to occluded hips
                    if has_hips:
                        hip_centroid = ((person[11, 1] + person[12, 1]) / 2, (person[11, 0] + person[12, 0]) / 2)
                    elif has_shoulders:
                        sh_w = abs(person[5, 1] - person[6, 1])
                        torso_offset_y = max(0.08, min(0.35, 1.35 * sh_w)) if sh_w > 0.02 else 0.18
                        sh_x = (person[5, 1] + person[6, 1]) / 2
                        sh_y = (person[5, 0] + person[6, 0]) / 2
                        hip_centroid = (sh_x, min(1.0, sh_y + torso_offset_y))
                    else:
                        xs = [kp[1] for kp in valid_kps]
                        ys = [kp[0] for kp in valid_kps]
                        hip_centroid = (float(np.mean(xs)), float(np.mean(ys)))

                    raw_detected.append((person, i, hip_centroid, conf))

            # Robust NMS: suppress duplicate detections of the same person (split detections)
            # Evaluates bounding box IoU / IoA inclusion as well as centroid distance
            frame_h, frame_w = res["frame"].shape[:2]
            nms_threshold_px = 0.15 * frame_w
            bboxes = [MotionOptimizedEngine.compute_bbox_from_keypoints(d[0], (frame_h, frame_w)) for d in raw_detected]
            suppressed = set()
            for i_det in range(len(raw_detected)):
                if i_det in suppressed:
                    continue
                b_i = bboxes[i_det]
                for j_det in range(i_det + 1, len(raw_detected)):
                    if j_det in suppressed:
                        continue
                    b_j = bboxes[j_det]
                    cx_i, cy_i = raw_detected[i_det][2]
                    cx_j, cy_j = raw_detected[j_det][2]
                    dist_px = (((cx_i - cx_j) * frame_w) ** 2 + ((cy_i - cy_j) * frame_h) ** 2) ** 0.5

                    is_dup = dist_px < nms_threshold_px
                    if not is_dup and b_i and b_j:
                        x1 = max(b_i[0], b_j[0])
                        y1 = max(b_i[1], b_j[1])
                        x2 = min(b_i[2], b_j[2])
                        y2 = min(b_i[3], b_j[3])
                        inter = max(0, x2 - x1) * max(0, y2 - y1)
                        if inter > 0:
                            area_i = max(1, (b_i[2] - b_i[0]) * (b_i[3] - b_i[1]))
                            area_j = max(1, (b_j[2] - b_j[0]) * (b_j[3] - b_j[1]))
                            iou = inter / (area_i + area_j - inter)
                            ioa_min = inter / min(area_i, area_j)
                            if iou > 0.30 or ioa_min > 0.50:
                                is_dup = True

                    if is_dup:
                        # Prioritize detection with more valid keypoints (more complete body pose)
                        n_kps_i = sum(1 for kp in raw_detected[i_det][0] if kp[2] > ghost_kp_conf)
                        n_kps_j = sum(1 for kp in raw_detected[j_det][0] if kp[2] > ghost_kp_conf)
                        if n_kps_i >= n_kps_j + 2:
                            suppressed.add(j_det)
                        elif n_kps_j >= n_kps_i + 2:
                            suppressed.add(i_det)
                            break
                        elif raw_detected[i_det][3] >= raw_detected[j_det][3]:
                            suppressed.add(j_det)
                        else:
                            suppressed.add(i_det)
                            break

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

            frame_number = res.get("frame_index")
            if frame_number is None:
                frame_number = self.stats["total"]

            # C4 (deferred): this is update #1 of the same per-camera tracker singleton; update #2
            # runs in behaviors/engine.py::analyze_packet on the worker thread. This early update
            # assigns stable_ids that classify_behavior() below keys on. Collapsing the two is
            # deferred pending A4 live data — the two run on different cadences (this on the async
            # MoveNet thread, #2 on the worker thread which also refreshes last_seen during
            # motion-gate skips), so a naive removal could worsen reacquire flicker. The C1 render
            # hysteresis already masks the reacquire blink.
            if tracked_list:
                tracker.update(tracked_list, frame_number)

            detected_people = []
            for tp in tracked_list:
                person = tp.keypoints
                stable_id = tp.stable_id
                raw_id = tp.raw_person_id
                
                res["num_people"] += 1
                if draw:
                    self.draw_skeleton(res["frame"], person, stable_id)
                custom_time = res.get("timestamp", None)
                label, score = self.classify_behavior(person, stable_id, cam_id, res["frame"].shape, custom_time=custom_time)

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

    def _get_tracker_yaml(self):
        """Phase B3: build a ByteTrack YAML from config (yolo.tracker) once and cache its path.
        This is what makes the intended track_high_thresh (formerly the inert
        tracker_config.TRACKER_CFG['track_thresh']=0.2) actually take effect. Falls back to the
        packaged 'bytetrack.yaml' if generation fails so tracking never hard-breaks."""
        if self._tracker_yaml_path is not None:
            return self._tracker_yaml_path
        try:
            import yaml
            tcfg = get_config("yolo", "tracker", {}) or {}
            doc = {
                "tracker_type": "bytetrack",
                "track_high_thresh": float(tcfg.get("track_high_thresh", 0.50)),
                "track_low_thresh": float(tcfg.get("track_low_thresh", 0.20)),
                "new_track_thresh": float(tcfg.get("new_track_thresh", 0.40)),
                "track_buffer": int(tcfg.get("track_buffer", 30)),
                "match_thresh": float(tcfg.get("match_thresh", 0.5)),
                "fuse_score": bool(tcfg.get("fuse_score", True)),
            }
            out_dir = os.path.join(os.path.dirname(__file__), "models")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "bytetrack_generated.yaml")
            with open(out_path, "w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False)
            self._tracker_yaml_path = out_path
            print(f"[YOLO] ByteTrack config generated from config.yaml -> {doc}")
        except Exception as e:
            print(f"[YOLO] Tracker YAML generation failed ({e}); using packaged bytetrack.yaml")
            self._tracker_yaml_path = "bytetrack.yaml"
        return self._tracker_yaml_path

    @staticmethod
    def _passes_ghost_filter(n_valid, torso_count, ghost_min_kp, ghost_min_torso):
        """Ghost/structure filter decision. Accepts a person only with enough total keypoints
        AND enough of the 4 torso anchors (L/R shoulder, L/R hip) visible. Requiring a COUNT of
        torso anchors rather than a complete pair is what stops a single shoulder-keypoint dip
        from collapsing the detection and blinking the box off (the dominant MoveNet flicker)."""
        return not (n_valid < ghost_min_kp or torso_count < ghost_min_torso)

    @staticmethod
    def _untracked_cache_key(cls_id, x1, y1, x2, y2, grid_px):
        """Phase B2: stable hysteresis key for an id-less detection. Quantizes the box centre
        to a grid so a stationary object's per-frame pixel jitter maps to one key instead of a
        fresh key every frame (which previously defeated the untracked-path hysteresis)."""
        grid = max(1, int(grid_px))
        gx = ((x1 + x2) // 2) // grid
        gy = ((y1 + y2) // 2) // grid
        return f"untracked_{cls_id}_{gx}_{gy}"

    def _get_yolo_for_camera(self, cam_id):
        """Phase B1: return a per-camera YOLO instance so each feed keeps ISOLATED ByteTrack
        state. The shared worker interleaves frames from all cameras onto one queue, so a single
        global tracker churns track_ids every frame with >=2 active cameras (the primary YOLO
        flicker cause). Controlled by yolo.tracker_isolation; 'shared' restores the legacy path."""
        isolation = get_config("yolo", "tracker_isolation", "per_camera")
        if isolation != "per_camera" or not self.active_model_path:
            return self.yolo_custom
        model = self.yolo_per_cam.get(cam_id)
        if model is None:
            try:
                model = YOLO(self.active_model_path)
                self.yolo_per_cam[cam_id] = model
                print(f"[YOLO] Per-camera ByteTrack instance created for cam {cam_id} "
                      f"({len(self.yolo_per_cam)} total) from {os.path.basename(self.active_model_path)}")
            except Exception as e:
                print(f"[YOLO] Per-camera instance load failed for cam {cam_id}: {e}; using shared model")
                return self.yolo_custom
        return model

    def _run_yolo_logic(self, res, cam_id):
        """
        YOLO LOGIC with ByteTrack.
        - Run custom YOLO model with tracking enabled.
        - Extract boxes and tracking IDs directly.
        """
        device = self.yolo_device  # Cached at __init__ via _setup_hardware()
        detections_found = []

        # Phase B1: per-camera instance -> isolated ByteTrack state
        model = self._get_yolo_for_camera(cam_id)

        if model:
            try:
                from monitor_app.config import get_config
                inference_imgsz = get_config("yolo", "inference_imgsz", 960)

                # Phase A2: prove one tracker sees interleaved cameras (per-thread/per-cam trace)
                if self.flicker_trace:
                    print(f"[FLICKER-A2] _run_yolo_logic cam={cam_id} "
                          f"thread={threading.get_ident()} model_id={id(model)} "
                          f"isolation={get_config('yolo', 'tracker_isolation', 'per_camera')}", flush=True)

                try:
                    results = model.predict(res["frame"], verbose=False,
                                            imgsz=inference_imgsz, device=device)

                except Exception as e:
                    print(f"[YOLO] CRITICAL: tracking failed on active model '{getattr(self, 'active_model_name', 'unknown')}': {e}")
                    model_dir = get_models_dir()
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
                                self.active_model_path = fallback_path
                                # Phase B1: drop stale per-camera clones so they rebuild from the fallback
                                self.yolo_per_cam = {}
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

                current_det_keys = set()
                yolo_hyst_ttl = int(get_config("yolo", "detection_hysteresis_frames", 5))

                raw_candidates = []
                if results:
                    for r in results:
                        if r.boxes is None or len(r.boxes) == 0:
                            continue

                        for box in r.boxes:
                            conf = float(box.conf[0])
                            cls_id = int(box.cls[0])
                            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                            track_id = int(box.id[0]) if box.id is not None else -1

                            # Phase A1: per-detection track_id/conf/box trace
                            if self.flicker_trace:
                                print(f"[FLICKER-A1] cam={cam_id} fidx={res.get('frame_index')} "
                                      f"cls={cls_id} track_id={track_id} id_is_none={box.id is None} "
                                      f"conf={conf:.3f} box=({x1},{y1},{x2},{y2})", flush=True)

                            if cls_id in CLASS_NAMES and conf > CONF_THRESHOLDS.get(cls_id, fallback_thr):
                                raw_candidates.append({
                                    "box": [x1, y1, x2, y2],
                                    "conf": conf,
                                    "cls_id": cls_id,
                                    "track_id": track_id
                                })

                # Batch track update for untracked contraband detections
                untracked_items = [c for c in raw_candidates if c["track_id"] == -1]
                batch_boxes = [c["box"] for c in untracked_items]
                batch_confs = [c["conf"] for c in untracked_items]
                batch_cls = [c["cls_id"] for c in untracked_items]

                # Step tracker (even when empty) so lost tracks decay naturally
                trk_results = self.contraband_tracker.update(cam_id, batch_boxes, batch_confs, batch_cls)
                trk_idx = 0

                for cand in raw_candidates:
                    cls_id = cand["cls_id"]
                    conf = cand["conf"]
                    x1, y1, x2, y2 = cand["box"]
                    track_id = cand["track_id"]

                    if track_id != -1:
                        effective_track_id = track_id
                    else:
                        effective_track_id = trk_results[trk_idx]["track_id"] if trk_idx < len(trk_results) else (abs(hash((cls_id, x1, y1))) % 9000 + 1000)
                        trk_idx += 1

                    cache_key = effective_track_id
                    current_det_keys.add(cache_key)

                    # Update hysteresis cache
                    if cam_id not in self.yolo_hysteresis:
                        self.yolo_hysteresis[cam_id] = {}

                    self.yolo_hysteresis[cam_id][cache_key] = {
                        "conf": conf,
                        "confidence": conf,
                        "box": [x1, y1, x2, y2],
                        "track_id": effective_track_id,
                        "cls_id": cls_id,
                        "ttl": yolo_hyst_ttl
                    }

                    detections_found.append({
                        "name": CLASS_NAMES[cls_id],
                        "conf": conf,
                        "confidence": conf,
                        "box": [x1, y1, x2, y2],
                        "track_id": effective_track_id,
                        "source": "combined"
                    })

                # Apply hysteresis for missing detections unconditionally across every camera frame
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
                                    "confidence": data.get("confidence", data["conf"]),
                                    "box": data["box"],
                                    "track_id": data["track_id"],
                                    "source": "combined_hysteresis"
                                })

                # Update active track time to keep motion gate open if detections exist (live or coasted)
                if detections_found:
                    from monitor_app.central_inference import get_inference_manager
                    mgr = get_inference_manager()
                    if mgr:
                        mgr.update_active_track_time(cam_id)

                # Phase A1: hysteresis-cache snapshot (which keys are live vs coasting)
                if self.flicker_trace:
                    cache_keys = list(self.yolo_hysteresis.get(cam_id, {}).keys())
                    sources = [d.get("source") for d in detections_found]
                    print(f"[FLICKER-A1] cam={cam_id} fidx={res.get('frame_index')} "
                          f"live_keys={sorted(str(k) for k in current_det_keys)} "
                          f"cache_keys={sorted(str(k) for k in cache_keys)} "
                          f"emitted_sources={sources}", flush=True)
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
                "track_id": track_id,
                # RC-2: propagate provenance so the renderer can skip-draw a coasting
                # hysteresis ghost that overlaps a live box. Additive key only — the
                # decision path (decision.py) reads name/confidence/box/track_id and is
                # unaffected; the detection still reaches DecisionEngine either way.
                "source": det.get("source", "combined")
            })
            CapstoneDebug.log(cam_id, f"CONTRABAND FOUND: {name} ({conf:.2f}) [ID: {track_id}]")

    def classify_behavior(self, kps, p_id, cam_id, frame_shape, custom_time=None):
        frame_h, frame_w = frame_shape[:2]
        key = f"{cam_id}_{p_id}"
        coords = kps[:, :2] * np.array([frame_h, frame_w])
        confs = kps[:, 2]

        current_time = custom_time if custom_time is not None else time.time()

        if key not in self.trackers:
            self.trackers[key] = {
                'prev_coords': coords,
                'prev_confs': confs,
                'smoothed_coords': coords.copy(),
                'history': [],
                'alert_count': 0,
                'time': current_time
            }
            return "Normal", 0.0

        tracker = self.trackers[key]
        dt = current_time - tracker['time']
        if dt < 0.01: return "Normal", 0.0

        # Reset tracker if gap is too large to prevent velocity spikes from tracking gaps/reappearance
        max_dt_reset = float(get_config("behavior", "max_dt_reset", 0.40))
        if dt > max_dt_reset:
            tracker['prev_coords'] = coords
            tracker['prev_confs'] = confs
            tracker['smoothed_coords'] = coords.copy()
            tracker['time'] = current_time
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
        tracker['time'] = current_time

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
        kp_conf = get_config("movenet", "bbox_kp_conf", 0.10)
        for y, x, c in kps:
            if c > kp_conf:
                cv2.circle(frame, (int(x * w), int(y * h)), 4, color, -1, lineType=cv2.LINE_AA)
        for p1, p2 in self.EDGES:
            if kps[p1, 2] > kp_conf and kps[p2, 2] > kp_conf:
                cv2.line(frame, (int(kps[p1, 1] * w), int(kps[p1, 0] * h)),
                         (int(kps[p2, 1] * w), int(kps[p2, 0] * h)), color, 2, lineType=cv2.LINE_AA)
        # Connect head to torso cleanly via neck line (nose -> shoulder midpoint)
        # Eliminates face-slashing diagonal edges across cheeks and mouth, with single-shoulder fallback
        sh5_ok = kps[5, 2] > kp_conf
        sh6_ok = kps[6, 2] > kp_conf
        if kps[0, 2] > kp_conf and (sh5_ok or sh6_ok):
            if sh5_ok and sh6_ok:
                mid_sh_x = int((kps[5, 1] + kps[6, 1]) * 0.5 * w)
                mid_sh_y = int((kps[5, 0] + kps[6, 0]) * 0.5 * h)
            elif sh5_ok:
                mid_sh_x = int(kps[5, 1] * w)
                mid_sh_y = int(kps[5, 0] * h)
            else:
                mid_sh_x = int(kps[6, 1] * w)
                mid_sh_y = int(kps[6, 0] * h)
            nose_x = int(kps[0, 1] * w)
            nose_y = int(kps[0, 0] * h)
            cv2.line(frame, (nose_x, nose_y), (mid_sh_x, mid_sh_y), color, 2, lineType=cv2.LINE_AA)

    def label_person(self, frame, kps, p_id, label, score):
        h, w = frame.shape[:2]
        x, y = int(kps[0, 1] * w), int(kps[0, 0] * h)
        color = (0, 0, 255) if "Aggressive" in label else (255, 255, 255)
        cv2.putText(frame, f"P{p_id + 1}: {label}", (x, y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, lineType=cv2.LINE_AA)

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
