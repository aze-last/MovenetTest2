import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

try:
    import tensorflow as tf
    TF_AVAILABLE = True
except Exception:
    TF_AVAILABLE = False
    tf = None

try:
    import tensorflow_hub as hub
    HUB_AVAILABLE = True
except Exception:
    HUB_AVAILABLE = False
    hub = None

if TF_AVAILABLE:
    try:
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
            print("✅ MoveNet: GPU Accelerated")
        else:
            print("❌ MoveNet: GPU not available")
    except Exception:
        print("❌ MoveNet: GPU not available")

# =========================
# Tune parameters here
# =========================
CONF_THR = 0.25          # keypoint confidence cutoff
AGG_THR = 450.0         # pixels/sec for aggressive
ACTIVE_THR = 140.0       # pixels/sec for fast movement
MOTION_THRESHOLD = 4500 # gate for running MoveNet
MOTION_RATIO = 0.009    # adaptive gate based on frame size


EDGES = [
    (0,1),(0,2),(1,3),(2,4),(0,5),(0,6),(5,7),(7,9),
    (6,8),(8,10),(5,6),(5,11),(6,12),(11,12),(11,13),
    (13,15),(12,14),(14,16)
]


class MoveNetTuner:
    def __init__(self, model_dir):
        self.model_dir = model_dir
        self.movenet = None
        self.trackers = {}
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30, detectShadows=False)
        self.last_gray = None
        self._setup_hardware()
        self._load_model()

    def _setup_hardware(self):
        if not TF_AVAILABLE:
            return
        try:
            gpus = tf.config.list_physical_devices("GPU")
            if gpus:
                for gpu in gpus:
                    tf.config.experimental.set_memory_growth(gpu, True)
                print(f"MoveNet Tuner: GPU enabled ({gpus[0].name})")
            else:
                print("MoveNet Tuner: No GPU detected, using CPU.")
        except Exception as e:
            print(f"MoveNet Tuner: GPU setup failed: {e}")

    def _load_model(self):
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow not available in this environment.")

        local_model_path = None
        if os.path.exists(self.model_dir):
            if os.path.exists(os.path.join(self.model_dir, "saved_model.pb")):
                local_model_path = self.model_dir
            else:
                for root, _dirs, files in os.walk(self.model_dir):
                    if "saved_model.pb" in files:
                        local_model_path = root
                        break

        if local_model_path:
            self.movenet = tf.saved_model.load(local_model_path).signatures["serving_default"]
            print(f"MoveNet loaded from local path: {local_model_path}")
        elif HUB_AVAILABLE:
            self.movenet = hub.load("https://tfhub.dev/google/movenet/multipose/lightning/1").signatures["serving_default"]
            print("MoveNet loaded from TFHub.")
        else:
            raise RuntimeError("tensorflow_hub not available and local model missing.")

    def detect_motion(self, frame):
        frame_h, frame_w = frame.shape[:2]
        adaptive_threshold = max(MOTION_THRESHOLD, int(frame_h * frame_w * MOTION_RATIO))

        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (15, 15), 0)
        mask = self.bg_subtractor.apply(gray)
        score = cv2.countNonZero(mask)

        if self.last_gray is not None:
            diff = cv2.absdiff(self.last_gray, gray)
            _, t = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            score = max(score, cv2.countNonZero(t))

        self.last_gray = gray
        return score > adaptive_threshold, score

    def classify_behavior(self, kps, frame_shape, person_key):
        frame_h, frame_w = frame_shape[:2]
        scaled = kps[:, :2] * np.array([frame_h, frame_w])

        if person_key not in self.trackers:
            self.trackers[person_key] = {"prev": scaled, "history": [], "time": time.time()}
            return "Normal", 0.0

        tracker = self.trackers[person_key]
        dt = time.time() - tracker["time"]
        if dt < 0.01:
            return "Normal", 0.0

        speed = np.linalg.norm(
            scaled[[7, 8, 9, 10]] - tracker["prev"][ [7, 8, 9, 10] ],
            axis=1
        ).mean() / dt

        tracker["prev"] = scaled
        tracker["time"] = time.time()
        tracker["history"].append(speed)
        if len(tracker["history"]) > 5:
            tracker["history"].pop(0)

        avg = float(np.mean(tracker["history"]))
        if avg > AGG_THR:
            return "Aggressive / Fighting", avg
        if avg > ACTIVE_THR:
            return "Fast Movement", avg
        return "Normal", avg

    def draw_skeleton(self, frame, kps, p_id):
        h, w = frame.shape[:2]
        color = [(0, 255, 0), (255, 0, 0), (0, 255, 255)][p_id % 3]
        for y, x, c in kps:
            if c > CONF_THR:
                cv2.circle(frame, (int(x * w), int(y * h)), 4, color, -1)
        for p1, p2 in EDGES:
            if kps[p1, 2] > CONF_THR and kps[p2, 2] > CONF_THR:
                cv2.line(
                    frame,
                    (int(kps[p1, 1] * w), int(kps[p1, 0] * h)),
                    (int(kps[p2, 1] * w), int(kps[p2, 0] * h)),
                    color,
                    2
                )

    def run(self, camera_index=0, backend=None):
        if backend is None:
            cap = cv2.VideoCapture(camera_index)
        else:
            cap = cv2.VideoCapture(camera_index, backend)
        if not cap.isOpened():
            raise RuntimeError("Failed to open camera.")

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.03)
                    continue

                moving, score = self.detect_motion(frame)
                if moving:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img_input = cv2.resize(rgb, (256, 256))
                    tensor = tf.cast(img_input, dtype=tf.int32)[tf.newaxis, ...]
                    outputs = self.movenet(tensor)
                    kpts = outputs["output_0"].numpy()[0]

                    for i in range(6):
                        person = kpts[i, :51].reshape(17, 3)
                        conf = float(np.mean(person[:, 2]))
                        if conf > CONF_THR:
                            self.draw_skeleton(frame, person, i)
                            label, speed = self.classify_behavior(person, frame.shape, f"0_{i}")
                            if label != "Normal":
                                cv2.putText(
                                    frame,
                                    f"P{i+1}: {label} ({speed:.1f})",
                                    (10, 30 + i * 20),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6,
                                    (0, 0, 255),
                                    2
                                )

                cv2.putText(
                    frame,
                    f"Motion: {score}",
                    (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

                cv2.imshow("MoveNet Tuner", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()


def _parse_args(argv):
    cam_index = 0
    backend = "dshow"
    for arg in argv[1:]:
        if arg.startswith("--cam="):
            cam_index = int(arg.split("=", 1)[1])
        elif arg.startswith("--backend="):
            backend = arg.split("=", 1)[1].lower()
    return cam_index, backend


def _backend_from_name(name):
    if name == "dshow":
        return cv2.CAP_DSHOW
    if name == "msmf":
        return cv2.CAP_MSMF
    if name == "ffmpeg":
        return cv2.CAP_FFMPEG
    return None


if __name__ == "__main__":
    model_dir = os.path.join(os.path.dirname(__file__), "models", "movenet_multipose")
    tuner = MoveNetTuner(model_dir)
    cam_index, backend_name = _parse_args(sys.argv)
    backend = _backend_from_name(backend_name)
    tuner.run(camera_index=cam_index, backend=backend)
