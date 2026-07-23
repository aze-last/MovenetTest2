import threading
import queue
import time
import concurrent.futures
from typing import Callable, Optional
from monitor_app.evidence import EvidencePacket
from monitor_app import profile_store
from monitor_app.config import get_config
from monitor_app.logger import get_module_logger

logger = get_module_logger("Central Inference")

class InferenceTask:
    def __init__(self, packet: EvidencePacket, callback: Optional[Callable] = None):
        self.packet = packet
        self.event = threading.Event()
        self.result: Optional[EvidencePacket] = None
        self.callback = callback

class CentralInferenceManager:
    """
    Centralized Inference Queue manager.
    Coordinates all YOLO26s (GPU) and MoveNet (CPU) inference with parallel workers
    to maximize hardware utilization.
    
    Architecture:
    - Main worker thread: dispatches frames, runs behavior/fusion/decision post-processing
    - MoveNet thread: dedicated CPU-bound pose estimation
    - YOLO thread: dedicated GPU-bound object detection
    - MoveNet and YOLO run concurrently on the same frame, results merge
    """
    def __init__(self, maxsize: int = 16):
        self.task_queue = queue.Queue(maxsize=maxsize)
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.engine = None
        self.lock = threading.Lock()
        self.result_lock = threading.Lock()
        self.last_active_track_times = {}
        self.hysteresis_timeout = 3.0  # seconds
        self.inference_paused = False
        self.last_gpu_retry_time = 0.0
        self.frame_indices = {}
        self.movenet_indices = {}
        self.last_movenet_results = {}
        self.last_yolo_results = {}
        
        self.movenet_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.callback_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.movenet_pending = {}
        # Phase C1/C3: render-side box + alert-colour hysteresis, per camera:
        #   cam_id -> {stable_id: {"bbox", "is_alert", "alert_hold", "misses"}}
        self.box_hysteresis = {}

        # Performance tuning parameters
        self.movenet_skip = 2
        self.yolo_skip = 1
    def has_active_tracks(self, camera_id: str) -> bool:
        with self.lock:
            last_time = self.last_active_track_times.get(str(camera_id), 0.0)
            return (time.time() - last_time) < self.hysteresis_timeout

    def update_active_track_time(self, camera_id: str):
        with self.lock:
            self.last_active_track_times[str(camera_id)] = time.time()

    def get_state(self):
        from monitor_app.health import ComponentState
        if not self.running:
            return ComponentState.IDLE
        if self.inference_paused:
            return ComponentState.RECOVERING
        if self.task_queue.full():
            return ComponentState.WAITING
        return ComponentState.RUNNING

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            
            # Start performance monitor
            from monitor_app.monitor_logging import get_performance_monitor
            get_performance_monitor().start()
            
            # Register with Health Monitor
            from monitor_app.health import get_health_monitor
            get_health_monitor().register_component("Central Inference", self.get_state)
            
            logger.info("Queue Worker started (parallel MoveNet+YOLO mode).")

    def stop(self):
        with self.lock:
            self.running = False
        if self.worker_thread:
            # Put dummy task to wake up queue
            try:
                self.task_queue.put_nowait(None)
            except queue.Full:
                pass
            self.worker_thread.join(timeout=1.0)
            self.worker_thread = None
            
        # Stop performance monitor
        from monitor_app.monitor_logging import get_performance_monitor
        get_performance_monitor().stop()
        logger.info("Queue Worker stopped.")

    def _initialize_engine(self):
        from monitor_app.ai_engine import MotionOptimizedEngine, BasicMotionEngine, ONNX_AVAILABLE, YOLO_AVAILABLE
        ai_cfg = profile_store.get_ai_settings()
        profile = ai_cfg["active_profile"]
        custom_vals = ai_cfg["custom_settings"] if profile == "custom" else None

        ai_available = ONNX_AVAILABLE or YOLO_AVAILABLE
        if ai_available and MotionOptimizedEngine is not None:
            logger.info("Initializing MotionOptimizedEngine (YOLO-GPU + MoveNet-CPU)...")
            self.engine = MotionOptimizedEngine(
                debug=False,
                sensitivity=profile,
                custom_values=custom_vals,
                enable_yolo=True,
                prefer_gpu=True,
                force_gpu=True,
                force_yolo_gpu=True
            )
        elif ai_available and BasicMotionEngine is not None:
            logger.info("Initializing BasicMotionEngine fallback...")
            self.engine = BasicMotionEngine(sensitivity=profile)

    def _run_parallel_inference(self, frame, camera_id, frame_uuid, frame_index=None):
        """Run MoveNet (CPU) and YOLO (GPU) concurrently on the same frame.
        Returns merged result dict."""
        
        movenet_result = {}
        yolo_result = {}
        movenet_error = None
        yolo_error = None
        
        def _movenet_worker(frm_copy, cid):
            try:
                ms = time.perf_counter()
                # RC-4: draw=False — this frame copy's pixels are discarded after keypoint
                # extraction; the visible skeleton is drawn in _render_person_boxes.
                res = self.engine.run_movenet_only(frm_copy, cid, frame_index=frame_index, draw=False)
                with self.result_lock:
                    self.last_movenet_results[cid] = res
                me = time.perf_counter()
                print(f"[TIMING] MoveNet (CPU Async): {(me-ms)*1000.0:.1f} ms", flush=True)
            except Exception as e:
                print(f"[TIMING] MoveNet Async Error: {e}", flush=True)
                logger.error(f"MoveNet async error: {e}", camera_id=cid)
            finally:
                self.movenet_pending[cid] = False
        
        def _yolo_worker():
            nonlocal yolo_result, yolo_error
            try:
                ys = time.perf_counter()
                yolo_result = self.engine.run_yolo_only(frame, camera_id)
                with self.result_lock:
                    self.last_yolo_results[camera_id] = yolo_result
                ye = time.perf_counter()
                print(f"[TIMING] YOLO (GPU): {(ye-ys)*1000.0:.1f} ms", flush=True)
            except Exception as e:
                print(f"[TIMING] YOLO Error: {e}", flush=True)
                yolo_error = e
        
        # Track local index
        self.movenet_indices[camera_id] = self.movenet_indices.get(camera_id, 0) + 1
        f_idx = self.movenet_indices[camera_id]

        # Check what needs to run based on skip
        has_movenet = self.engine.movenet is not None and (f_idx % self.movenet_skip == 0)
        has_yolo = self.engine.enable_yolo and self.engine.yolo_custom is not None and (f_idx % self.yolo_skip == 0)
        
        # Prevent queueing multiple MoveNet tasks for the same camera
        if has_movenet and self.movenet_pending.get(camera_id, False):
            has_movenet = False # Skip this frame for MoveNet if it's still running
        
        if has_movenet:
            self.movenet_pending[camera_id] = True
            # We copy the frame so the array isn't mutated while waiting in executor
            self.movenet_executor.submit(_movenet_worker, frame.copy(), camera_id)
            
        if has_yolo:
            _yolo_worker()
            
        if movenet_error:
            logger.error(f"MoveNet parallel error: {movenet_error}", camera_id=camera_id)
        if yolo_error:
            logger.error(f"YOLO parallel error: {yolo_error}", camera_id=camera_id)
        
        # Merge results: MoveNet provides people/behavior, YOLO provides contraband
        with self.result_lock:
            movenet_result = self.last_movenet_results.get(camera_id, {})
            yolo_result = self.last_yolo_results.get(camera_id, {})
            
            merged = {
                "frame": frame,
                "num_people": movenet_result.get("num_people", 0),
                "alert_triggered": movenet_result.get("alert_triggered", False) or yolo_result.get("alert_triggered", False),
                "alerts": movenet_result.get("alerts", []) + yolo_result.get("alerts", []),
                "detections": {
                    "behavior": movenet_result.get("detections", {}).get("behavior", []),
                    "contraband": yolo_result.get("detections", {}).get("contraband", []),
                },
                "processing_mode": "AI ACTIVE (Parallel GPU+CPU)",
                "tracked_persons": movenet_result.get("tracked_persons", []),
                # RC-4: frame index the cached MoveNet result was computed on, so the
                # renderer can skip drawing a stale skeleton onto a much newer frame.
                "movenet_src_frame_index": movenet_result.get("frame_index"),
            }
        
        # --- PHASE 2 Render: Continuous Box Drawing ---
        # RC-2: draw through the render-dedup helper; merged["detections"] itself is
        # untouched, so the decision path still sees every detection (ghosts included).
        self._draw_contraband_boxes(merged["frame"], merged["detections"]["contraband"])

        return merged

    @staticmethod
    def _iou(box_a, box_b):
        """Intersection-over-union of two (x1, y1, x2, y2) boxes."""
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    @classmethod
    def _contraband_for_render(cls, detections):
        """RC-2 render-only dedup: drop a coasting hysteresis ghost from the DRAW list
        when a live detection of the same class overlaps it above
        yolo.hysteresis_dedup_iou (the stacked-box symptom: old track_id key coasts at
        the old position while the re-identified track draws live).

        Render path only. The full detections list — ghosts included — has already been
        written to res["detections"]["contraband"] / packet.detections, which is what
        DecisionEngine (decision.py:63,93), AlertManager and IncidentRecorder consume.
        Nothing is removed from that list here."""
        thr = float(get_config("yolo", "hysteresis_dedup_iou", 0.5))
        live = [d for d in detections if d.get("source") != "combined_hysteresis"]
        drawable = list(live)
        for ghost in detections:
            if ghost.get("source") != "combined_hysteresis":
                continue
            overlaps_live = any(
                d.get("name") == ghost.get("name")
                and cls._iou(d.get("box", [0, 0, 0, 0]), ghost.get("box", [0, 0, 0, 0])) >= thr
                for d in live
            )
            if not overlaps_live:
                drawable.append(ghost)
        return drawable

    def _draw_contraband_boxes(self, frame, detections):
        """Single draw helper for contraband boxes (live + power-saving paths)."""
        import cv2
        for det in self._contraband_for_render(detections):
            name = det.get("name", "Unknown")
            track_id = det.get("track_id", -1)
            x1, y1, x2, y2 = map(int, det.get("box", [0, 0, 0, 0]))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.putText(frame, f"ALERT: {name.upper()} (ID: {track_id})",
                        (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    def _compute_is_alert(self, packet, p):
        """Raw per-frame alert state for a person: legacy behavior detection (matched by
        raw_person_id) OR new behavior evidence (matched by stable_id)."""
        for b_det in packet.detections.get("behavior", []):
            if (b_det.get("person_index") == p.raw_person_id
                    and b_det.get("label") in ("Aggressive / Fighting", "Fast Movement")):
                return True
        for ev in packet.behavior_evidence:
            if ev.stable_id == p.stable_id:
                return True
        return False

    def _draw_person_box(self, frame, bbox, stable_id, is_alert):
        import cv2
        color = (0, 0, 255) if is_alert else (0, 255, 0)
        x1, y1, x2, y2 = bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"ID {stable_id}", (x1, max(0, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    def _render_person_boxes(self, packet, frame_index=None, movenet_src_frame_index=None):
        """Phase C1/C3: draw MoveNet person boxes with temporal render hysteresis.

        C1 — a person's box coasts (keeps its last-good bbox) for up to
        movenet.detection_hysteresis_frames frames when the ghost filter briefly drops the
        detection, so the box no longer blinks on a 1-2 frame keypoint dip.
        C3 — alert colour latches for the same window so single-frame evidence gaps do not
        strobe the box red<->green.
        RC-4 — skeleton lines are only drawn when the MoveNet result is fresh enough
        (movenet.skeleton_max_age_frames): a cached pose re-rendered on a much newer frame
        draws limbs at the old position and then visibly snaps when the next inference
        lands. Boxes (padded, coarser) still coast; only the precise skeleton is gated.
        Rendering-only: behavior, fusion, and decision paths are deliberately untouched, so
        coasting can never fabricate an incident."""
        from monitor_app.ai_engine import MotionOptimizedEngine

        cam_id = packet.camera_id
        hyst_frames = int(get_config("movenet", "detection_hysteresis_frames", 8))

        # RC-4: skeleton freshness gate
        skel_max_age = int(get_config("movenet", "skeleton_max_age_frames", 3))
        skeleton_fresh = True
        if frame_index is not None and movenet_src_frame_index is not None:
            skeleton_fresh = (frame_index - movenet_src_frame_index) <= skel_max_age

        cache = self.box_hysteresis.setdefault(cam_id, {})
        present_ids = set()

        for p in packet.tracked_persons:
            if p.keypoints is None:
                continue
            # Restore MoveNet skeletal lines on the final frame (fresh detections only)
            if skeleton_fresh and hasattr(self.engine, 'draw_skeleton'):
                self.engine.draw_skeleton(packet.frame, p.keypoints, p.stable_id)

            bbox = MotionOptimizedEngine.compute_bbox_from_keypoints(p.keypoints, packet.frame.shape)
            if not bbox:
                continue
            p.bbox = bbox

            raw_alert = self._compute_is_alert(packet, p)
            prev = cache.get(p.stable_id, {})
            if raw_alert:
                alert_hold = hyst_frames
            else:
                alert_hold = max(0, int(prev.get("alert_hold", 0)) - 1)
            is_alert = raw_alert or alert_hold > 0

            cache[p.stable_id] = {"bbox": bbox, "is_alert": is_alert,
                                  "alert_hold": alert_hold, "misses": 0}
            present_ids.add(p.stable_id)
            self._draw_person_box(packet.frame, bbox, p.stable_id, is_alert)

        # C1 — coast recently-seen persons that dropped out this frame
        # RC-3: skip-draw a coasted box that overlaps a LIVE person box above
        # movenet.coast_dedup_iou — the stacked-box case where an ID churn leaves the
        # old ID coasting on top of the same person's new live box. The cache entry
        # still ages normally (misses/alert_hold), only the draw is suppressed; and
        # this is render-only — packet.tracked_persons / behavior_evidence, which the
        # behavior, fusion and decision paths consume, never contained coasted
        # entries in the first place.
        coast_thr = float(get_config("movenet", "coast_dedup_iou", 0.6))
        live_boxes = [cache[sid]["bbox"] for sid in present_ids if cache.get(sid, {}).get("bbox")]
        for sid in list(cache.keys()):
            if sid in present_ids:
                continue
            entry = cache[sid]
            entry["misses"] = int(entry.get("misses", 0)) + 1
            if entry["misses"] > hyst_frames:
                del cache[sid]
                continue
            entry["alert_hold"] = max(0, int(entry.get("alert_hold", 0)) - 1)
            entry["is_alert"] = entry["alert_hold"] > 0
            overlaps_live = any(
                self._iou(entry["bbox"], lb) >= coast_thr for lb in live_boxes
            )
            if not overlaps_live:
                self._draw_person_box(packet.frame, entry["bbox"], sid, entry["is_alert"])

    def _worker_loop(self):
        # 1. Load active settings and initialize AI engine
        if self.engine is None:
            try:
                self._initialize_engine()
            except Exception as e:
                logger.error(f"Engine init failed: {e}")
                self.engine = None

        # 2. Main processing loop
        while self.running:
            try:
                task = self.task_queue.get(timeout=0.1)
                if task is None: # Stop signal
                    break
                
                packet = task.packet
                start_time = time.perf_counter()
                
                ctx = None
                if packet.frame_uuid:
                    from monitor_app.telemetry import get_telemetry_engine
                    ctx = get_telemetry_engine().get_context(packet.frame_uuid)
                    if ctx:
                        ctx.mark("queue_exit")
                
                # Check for GPU recovery retry
                if self.inference_paused:
                    now = time.time()
                    if now - self.last_gpu_retry_time >= 8.0:
                        self.last_gpu_retry_time = now
                        logger.info("Attempting GPU recovery...")
                        try:
                            self._initialize_engine()
                            if self.engine:
                                self.inference_paused = False
                                from monitor_app.utils import GlobalState
                                GlobalState.system_status = "ONLINE"
                                logger.info("GPU recovery successful! Resuming AI inference.")
                        except Exception as retry_ex:
                            logger.error(f"GPU recovery failed: {retry_ex}")

                # Process inference if engine exists and not paused
                if self.engine and not self.inference_paused:
                    try:
                        cam_id = packet.camera_id
                        self.frame_indices[cam_id] = self.frame_indices.get(cam_id, 0) + 1
                        frame_index = self.frame_indices[cam_id]

                        if packet.camera_id == "99":
                            res = packet.to_dict()
                        else:
                            # ── PARALLEL INFERENCE: MoveNet (CPU) + YOLO (GPU) concurrently ──
                            from monitor_app.ai_engine import MotionOptimizedEngine
                            if isinstance(self.engine, MotionOptimizedEngine):
                                # Use pre-detected motion to skip redundant computation
                                motion_flag = packet.motion_detected if packet.motion_detected else None
                                
                                # Check if motion gate / ungated processing applies
                                from monitor_app.config import get_config
                                gate_cfg = get_config("motion_gate")
                                movenet_gated = gate_cfg.get("motion_gate_movenet_enabled", True)
                                yolo_gated = gate_cfg.get("motion_gate_yolo_enabled", True)
                                
                                should_run = motion_flag or not movenet_gated or not yolo_gated
                                
                                if should_run:
                                    inf_start = time.perf_counter()
                                    res = self._run_parallel_inference(
                                        packet.frame, packet.camera_id, packet.frame_uuid, frame_index=frame_index
                                    )
                                    inf_end = time.perf_counter()
                                    inf_ms = (inf_end - inf_start) * 1000.0
                                    print(f"[TIMING] Full inference cycle (Cam {packet.camera_id}): {inf_ms:.1f} ms", flush=True)
                                    # Track stats
                                    with self.engine.lock:
                                        self.engine.stats["ai_runs"] += 1
                                        self.engine.stats["total"] += 1
                                else:
                                    with self.engine.lock:
                                        self.engine.stats["total"] += 1
                                        self.engine.stats["skipped"] += 1
                                        
                                    with self.result_lock:
                                        last_m = self.last_movenet_results.get(packet.camera_id, {})
                                        last_y = self.last_yolo_results.get(packet.camera_id, {})
                                        
                                        res = {
                                            "frame": packet.frame,
                                            "num_people": last_m.get("num_people", 0),
                                            "alert_triggered": last_m.get("alert_triggered", False) or last_y.get("alert_triggered", False),
                                            "alerts": last_m.get("alerts", []) + last_y.get("alerts", []),
                                            "detections": {
                                                "behavior": last_m.get("detections", {}).get("behavior", []),
                                                "contraband": last_y.get("detections", {}).get("contraband", []),
                                            },
                                            "processing_mode": "Power Saving (No Motion)",
                                            "tracked_persons": last_m.get("tracked_persons", []),
                                            "movenet_src_frame_index": last_m.get("frame_index"),
                                        }
                                        
                                        # Re-draw YOLO contraband boxes so they persist
                                        # (RC-2: same render-dedup helper as the live path)
                                        self._draw_contraband_boxes(
                                            res["frame"], res["detections"]["contraband"])
                            else:
                                # Fallback: BasicMotionEngine or unknown engine type
                                res = self.engine.process_frame(
                                    packet.frame, packet.camera_id, packet.frame_uuid
                                )
                        
                        # Map outcome back to EvidencePacket
                        packet.frame = res.get("frame", packet.frame)
                        packet.num_people = res.get("num_people", 0)
                        packet.alert_triggered = bool(res.get("alert_triggered", False))
                        packet.alerts = res.get("alerts", [])
                        packet.detections = res.get("detections", {"behavior": [], "contraband": []})
                        packet.processing_mode = res.get("processing_mode", "Standard")
                        packet.tracked_persons = list(res.get("tracked_persons", []))
                        packet.behavior_evidence = list(res.get("behavior_evidence", []))

                        # Run modular behavior engine (stable ID tracking & concealment analysis)
                        from monitor_app.behaviors import get_behavior_engine
                        ai_cfg = profile_store.get_ai_settings()
                        profile = ai_cfg["active_profile"]
                        
                        if ctx:
                            ctx.mark("behavior_start")
                        get_behavior_engine().analyze_packet(packet, frame_index, profile)
                        if ctx:
                            ctx.mark("behavior_end")

                        # --- CONCEALMENT: per-camera observations -> fusion -> behavior ---
                        from monitor_app.config import get_concealment_config
                        if get_concealment_config("enabled", True):
                            from monitor_app.hand_observation import get_hand_observation_classifier
                            from monitor_app.fusion import get_camera_fusion
                            from monitor_app.concealment_fusion import get_concealment_fusion_engine
                            from monitor_app.behaviors.concealment_detector import get_concealment_detector

                            if ctx:
                                ctx.mark("fusion_start")

                            classifier = get_hand_observation_classifier()
                            observations = []
                            for person in packet.tracked_persons:
                                observations.extend(
                                    classifier.classify_person(person, frame_index)
                                )

                            camera_fusion = get_camera_fusion()
                            camera_fusion.update_hand_observations(packet.camera_id, observations)
                            fused = get_concealment_fusion_engine().fuse_all_zones(
                                camera_fusion.get_hand_observations_snapshot()
                            )
                            packet.fused_concealment = fused

                            concealment_evidence = get_concealment_detector().process_fused(
                                fused,
                                frame_index,
                                profile,
                                packet.camera_id,
                                packet.timestamp,
                            )
                            packet.behavior_evidence.extend(concealment_evidence)

                            if ctx:
                                ctx.mark("fusion_end")

                        # --- ALERT SYNC & BBOX DRAWING ---
                        for ev in packet.behavior_evidence:
                            alert_str = f"Person {ev.stable_id}: {ev.behavior_type.upper()}"
                            if alert_str not in packet.alerts:
                                packet.alerts.append(alert_str)
                        if packet.behavior_evidence:
                            packet.alert_triggered = True

                        # Phase C1/C3: person boxes with temporal render hysteresis
                        # (RC-4: skeleton draw gated on MoveNet result freshness)
                        self._render_person_boxes(
                            packet,
                            frame_index=frame_index,
                            movenet_src_frame_index=res.get("movenet_src_frame_index"),
                        )

                        # --- PHASE 5: FUSION, DECISION & ALERT ROUTING ---
                        try:
                            from monitor_app.fusion import get_camera_fusion
                            from monitor_app.decision import get_decision_engine
                            from monitor_app.events import get_event_bus

                            if ctx:
                                ctx.mark("fusion_start")
                            # 1. Update Fused Telemetry State
                            get_camera_fusion().update(packet)
                            if ctx:
                                ctx.mark("fusion_end")
                                ctx.mark("decision_start")

                            # 2. Evaluate Decision
                            decision_engine = get_decision_engine()
                            
                            # Publish Tick to allow Hysteresis state machine to progress
                            get_event_bus().publish("FRAME_TICK", camera_id=packet.camera_id)
                            
                            if decision_engine.evaluate_trigger(packet):
                                # 3. Command Alert execution via Event Bus
                                evt_type, conf_scores = decision_engine.get_event_details(packet)
                                get_event_bus().publish(
                                    "DECISION_TRIGGER",
                                    camera_id=packet.camera_id,
                                    event_type=evt_type,
                                    confidence_scores=conf_scores,
                                    frame=packet.frame,
                                    ai_results=res
                                )
                            if ctx:
                                ctx.mark("decision_end")
                        except Exception as route_ex:
                            logger.error(f"Phase 5 Routing Error: {route_ex}")

                    except Exception as ex:
                        logger.error(f"Processing error: {ex}", camera_id=packet.camera_id)
                        packet.processing_mode = "Inference Error"
                        
                        # GPU exception recovery trigger:
                        # Pause AI, notify UI, set retry timer
                        self.inference_paused = True
                        self.last_gpu_retry_time = time.time()
                        from monitor_app.utils import GlobalState
                        GlobalState.system_status = "GPU inference unavailable"
                        logger.error("GPU exception detected. Pausing AI inference. Operator notified: GPU inference unavailable.")
                else:
                    packet.processing_mode = "GPU inference unavailable" if self.inference_paused else "No AI Engine Loaded"

                # Track performance latency
                latency = time.perf_counter() - start_time
                from monitor_app.monitor_logging import get_performance_monitor
                get_performance_monitor().track_frame(latency)

                # Telemetry end-of-pipeline retirement and dispatch
                if packet.frame_uuid and ctx:
                    from monitor_app.telemetry import get_telemetry_engine
                    # Retire from registry
                    get_telemetry_engine().retire_context(packet.frame_uuid)
                    
                    # Add database/recorder placeholders
                    ctx.mark("recorder_write_start")
                    ctx.mark("recorder_write_end")
                    ctx.mark("database_write_start")
                    ctx.mark("database_write_end")
                    
                    # Publish completed telemetry event
                    from monitor_app.events import get_event_bus, TELEM_PIPELINE_COMPLETE
                    get_event_bus().publish(TELEM_PIPELINE_COMPLETE, TELEM_PIPELINE_COMPLETE, ctx.to_dict())

                task.result = packet
                if hasattr(task, 'callback') and task.callback:
                    self.callback_executor.submit(task.callback, task.result)
                task.event.set()
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"worker loop error: {e}")

    def submit_task(self, packet: EvidencePacket) -> EvidencePacket:
        """
        Submit a task to the queue. Enforces bounded size with frame-dropping
        and returns the processed EvidencePacket.
        """
        task = InferenceTask(packet)
        
        # Mark queue enter timestamp
        if packet.frame_uuid:
            from monitor_app.telemetry import get_telemetry_engine
            ctx = get_telemetry_engine().get_context(packet.frame_uuid)
            if ctx:
                ctx.mark("queue_enter")

        # Frame dropping policy: If queue is full, drop oldest task
        while True:
            try:
                self.task_queue.put_nowait(task)
                break
            except queue.Full:
                try:
                    dropped_task = self.task_queue.get_nowait()
                    # Release dropped task immediately returning unprocessed packet
                    dropped_task.result = dropped_task.packet
                    dropped_task.packet.processing_mode = "Queue Drop (Backpressure)"
                    
                    from monitor_app.monitor_logging import SystemEvents, get_performance_monitor
                    get_performance_monitor().track_dropped_frame()
                    SystemEvents.queue_overflow(dropped_task.packet.camera_id, self.task_queue.qsize())
                    
                    # Retire dropped context and publish event loss telemetry
                    if dropped_task.packet.frame_uuid:
                        from monitor_app.telemetry import get_telemetry_engine
                        from monitor_app.events import get_event_bus, TELEM_FRAME_DROPPED
                        get_telemetry_engine().retire_context(dropped_task.packet.frame_uuid)
                        get_event_bus().publish(TELEM_FRAME_DROPPED, TELEM_FRAME_DROPPED, {
                            "camera_id": dropped_task.packet.camera_id,
                            "frame_uuid": dropped_task.packet.frame_uuid,
                            "reason": "queue_backpressure"
                        })

                    dropped_task.event.set()
                    self.task_queue.task_done()
                except queue.Empty:
                    pass

        # Wait for processing with a 3.0 second timeout (reduced from 5.0 for faster recovery)
        finished = task.event.wait(timeout=3.0)
        if not finished:
            # Timeout recovery
            task.result = packet
            packet.processing_mode = "Inference Timeout"
            
            # Retire context on timeout
            if packet.frame_uuid:
                from monitor_app.telemetry import get_telemetry_engine
                get_telemetry_engine().retire_context(packet.frame_uuid)
            
            from monitor_app.monitor_logging import SystemEvents
            SystemEvents.inference_timeout(packet.camera_id, 3.0)
        return task.result

    def submit_task_async(self, packet: EvidencePacket, callback: Optional[Callable] = None):
        """
        Non-blocking task submission. Submits frame and returns immediately.
        When processing completes, callback(result_packet) is called from a background thread.
        
        This prevents camera worker threads from blocking on GPU inference.
        """
        task = InferenceTask(packet, callback=callback)
        
        if packet.frame_uuid:
            from monitor_app.telemetry import get_telemetry_engine
            ctx = get_telemetry_engine().get_context(packet.frame_uuid)
            if ctx:
                ctx.mark("queue_enter")

        # Frame dropping policy
        while True:
            try:
                self.task_queue.put_nowait(task)
                break
            except queue.Full:
                try:
                    dropped_task = self.task_queue.get_nowait()
                    dropped_task.result = dropped_task.packet
                    dropped_task.packet.processing_mode = "Queue Drop (Backpressure)"
                    
                    from monitor_app.monitor_logging import SystemEvents, get_performance_monitor
                    get_performance_monitor().track_dropped_frame()
                    SystemEvents.queue_overflow(dropped_task.packet.camera_id, self.task_queue.qsize())
                    
                    if dropped_task.packet.frame_uuid:
                        from monitor_app.telemetry import get_telemetry_engine
                        from monitor_app.events import get_event_bus, TELEM_FRAME_DROPPED
                        get_telemetry_engine().retire_context(dropped_task.packet.frame_uuid)
                        get_event_bus().publish(TELEM_FRAME_DROPPED, TELEM_FRAME_DROPPED, {
                            "camera_id": dropped_task.packet.camera_id,
                            "frame_uuid": dropped_task.packet.frame_uuid,
                            "reason": "queue_backpressure"
                        })
                    
                    if hasattr(dropped_task, 'callback') and dropped_task.callback:
                        self.callback_executor.submit(dropped_task.callback, dropped_task.result)
                    
                    dropped_task.event.set()
                    self.task_queue.task_done()
                except queue.Empty:
                    pass



# Global Centralized Inference Manager Singleton
_global_inference_manager = CentralInferenceManager()

def get_inference_manager() -> CentralInferenceManager:
    return _global_inference_manager
