import os
import threading
import time
from typing import Dict, List, Optional, Tuple, Any
import cv2
import numpy as np

from monitor_app.config import get_config
from monitor_app.logger import get_module_logger

logger = get_module_logger("FaceBinder")


class OpportunisticFaceBinder:
    """
    Opportunistic face recognition binding engine for CellWatch AI.
    - CPU Execution: OpenCV Zoo YuNet detector + SFace recognizer.
    - Rate-limited: 1 Hz opportunistic probe on unbound tracks.
    - Multi-frame confirmation: k-of-N consensus (default 3 of 5, threshold >= 0.363).
    - Anti-collision: prevents binding the same enrolled inmate to two concurrent tracks on the same camera.
    - Privacy-first: strictly disabled by default (RA 10173 compliance).
    """

    def __init__(
        self,
        cosine_threshold: float = 0.363,
        k_confirmations: int = 3,
        n_window: int = 5,
        min_face_size_px: int = 50,
    ):
        self.cosine_threshold = cosine_threshold
        self.k_confirmations = k_confirmations
        self.n_window = n_window
        self.min_face_size_px = min_face_size_px

        self.lock = threading.Lock()
        self.gallery: Dict[str, Dict[str, Any]] = {}
        self.bound_identities: Dict[Tuple[str, int], Dict[str, Any]] = {}  # (cam_id, stable_id) -> data
        self.probe_history: Dict[Tuple[str, int], List[Optional[str]]] = {}  # (cam_id, stable_id) -> [sub_id, ...]
        self.last_probe_time: Dict[Tuple[str, int], float] = {}

        self._detector = None
        self._recognizer = None
        self._init_failed = False

    def is_enabled(self) -> bool:
        """Strict default-off privacy toggle (Data Privacy Act of 2012 / RA 10173)."""
        return bool(get_config("face_recognition", "enabled", False))

    def _ensure_models(self) -> bool:
        if self._detector is not None and self._recognizer is not None:
            return True
        if self._init_failed:
            return False

        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        yunet_path = os.path.join(models_dir, "face_detection_yunet_2023mar.onnx")
        sface_path = os.path.join(models_dir, "face_recognition_sface_2021dec.onnx")

        if not os.path.exists(yunet_path) or not os.path.exists(sface_path):
            logger.warning(
                f"Face recognition models missing. Disabling opportunistic face binding. "
                f"yunet={os.path.exists(yunet_path)}, sface={os.path.exists(sface_path)}"
            )
            self._init_failed = True
            return False

        try:
            self._detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 320))
            self._recognizer = cv2.FaceRecognizerSF.create(sface_path, "")
            logger.info("YuNet + SFace models successfully initialized on CPU.")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize YuNet/SFace models: {e}")
            self._init_failed = True
            return False

    def enroll_feature(self, subject_id: str, name: str, embedding: np.ndarray):
        """Enrolls a precomputed 128-d face embedding into the ephemeral gallery."""
        with self.lock:
            norm_emb = embedding / max(1e-6, np.linalg.norm(embedding))
            self.gallery[subject_id] = {
                "subject_id": subject_id,
                "name": name,
                "embedding": norm_emb.reshape(1, -1).astype(np.float32)
            }
            logger.info(f"Subject enrolled in gallery: {subject_id} ({name})")

    def enroll_face_image(self, subject_id: str, name: str, face_img_bgr: np.ndarray) -> bool:
        """Detects and enrolls a subject directly from a face image."""
        if not self._ensure_models():
            return False

        h, w = face_img_bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(face_img_bgr)
        if faces is None or len(faces) == 0:
            logger.warning(f"No face detected for enrollment: {subject_id}")
            return False

        aligned = self._recognizer.alignCrop(face_img_bgr, faces[0])
        feature = self._recognizer.feature(aligned)
        self.enroll_feature(subject_id, name, feature)
        return True

    def _extract_face_feature(self, frame: np.ndarray, head_bbox: List[int]) -> Optional[np.ndarray]:
        """Extracts 128-d face embedding from a bounding box crop."""
        if not self._ensure_models():
            return None

        x1, y1, x2, y2 = head_bbox
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(frame.shape[1], int(x2)), min(frame.shape[0], int(y2))
        if x2 - x1 < self.min_face_size_px or y2 - y1 < self.min_face_size_px:
            return None

        crop = frame[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        self._detector.setInputSize((cw, ch))
        _, faces = self._detector.detect(crop)
        if faces is None or len(faces) == 0:
            return None

        aligned = self._recognizer.alignCrop(crop, faces[0])
        feature = self._recognizer.feature(aligned)
        return feature / max(1e-6, np.linalg.norm(feature))

    def get_bound_identity(self, camera_id: str, stable_id: int) -> Optional[Dict[str, Any]]:
        """Returns the confirmed identity bound to a track, or None if unbound."""
        with self.lock:
            return self.bound_identities.get((camera_id, stable_id))

    def probe_track(
        self,
        camera_id: str,
        stable_id: int,
        frame: np.ndarray,
        head_bbox: List[int],
        current_time: float
    ) -> Optional[str]:
        """
        Attempts to bind an identity to an unconfirmed track.
        Returns subject_id if confirmed, or None.
        """
        if not self.is_enabled():
            return None

        track_key = (camera_id, stable_id)

        with self.lock:
            # If already bound, return confirmed subject
            if track_key in self.bound_identities:
                return self.bound_identities[track_key]["subject_id"]

            # 1 Hz probe throttling
            last_t = self.last_probe_time.get(track_key, 0.0)
            if current_time - last_t < 1.0:
                return None
            self.last_probe_time[track_key] = current_time

            if not self.gallery:
                return None

        # Feature extraction (outside lock for minimum latency contention)
        feature = self._extract_face_feature(frame, head_bbox)

        with self.lock:
            if feature is None:
                # Record a missed probe in the N-window
                hist = self.probe_history.setdefault(track_key, [])
                hist.append(None)
                if len(hist) > self.n_window:
                    hist.pop(0)
                return None

            # Compare against enrolled gallery
            best_id = None
            best_sim = -1.0
            for sub_id, entry in self.gallery.items():
                enrolled_feat = entry["embedding"]
                sim = float(np.dot(feature.flatten(), enrolled_feat.flatten()))
                if sim > best_sim:
                    best_sim = sim
                    best_id = sub_id

            hist = self.probe_history.setdefault(track_key, [])
            match_candidate = best_id if best_sim >= self.cosine_threshold else None
            hist.append(match_candidate)
            if len(hist) > self.n_window:
                hist.pop(0)

            # Check k-of-N confirmation
            if match_candidate is not None:
                match_count = sum(1 for m in hist if m == match_candidate)
                if match_count >= self.k_confirmations:
                    # Anti-collision check: ensure candidate is not bound to another active track on this camera
                    for (cam, sid), bound in self.bound_identities.items():
                        if cam == camera_id and sid != stable_id and bound["subject_id"] == match_candidate:
                            logger.warning(
                                f"Face binding anti-collision triggered: identity {match_candidate} "
                                f"already bound to track {sid} on cam={camera_id}"
                            )
                            return None

                    # Bind confirmed identity
                    self.bound_identities[track_key] = {
                        "subject_id": match_candidate,
                        "name": self.gallery[match_candidate]["name"],
                        "confidence": best_sim,
                        "bound_at": current_time,
                    }
                    logger.info(
                        f"Track identity confirmed via opportunistic face binding: cam={camera_id} "
                        f"stable_id={stable_id} -> {match_candidate} ({self.gallery[match_candidate]['name']}), "
                        f"confidence={best_sim:.3f}"
                    )
                    return match_candidate

            return None

    def unbind_track(self, camera_id: str, stable_id: int):
        """Clears bound identity when a track is retired/lost."""
        with self.lock:
            self.bound_identities.pop((camera_id, stable_id), None)
            self.probe_history.pop((camera_id, stable_id), None)
            self.last_probe_time.pop((camera_id, stable_id), None)
