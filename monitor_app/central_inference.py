import threading
import queue
import time
from typing import Callable, Optional
from monitor_app.evidence import EvidencePacket
from monitor_app import profile_store

class InferenceTask:
    def __init__(self, packet: EvidencePacket):
        self.packet = packet
        self.event = threading.Event()
        self.result: Optional[EvidencePacket] = None

class CentralInferenceManager:
    """
    Centralized Inference Queue manager.
    Coordinates all YOLOv8 (GPU) and MoveNet (CPU) inference requests in a single thread
    to prevent VRAM fragmentation, race conditions, and thread locks.
    """
    def __init__(self, maxsize: int = 8):
        self.task_queue = queue.Queue(maxsize=maxsize)
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.engine = None
        self.lock = threading.Lock()
        self.last_active_track_times = {}
        self.hysteresis_timeout = 3.0  # seconds

    def has_active_tracks(self, camera_id: str) -> bool:
        with self.lock:
            last_time = self.last_active_track_times.get(str(camera_id), 0.0)
            return (time.time() - last_time) < self.hysteresis_timeout

    def update_active_track_time(self, camera_id: str):
        with self.lock:
            self.last_active_track_times[str(camera_id)] = time.time()

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            print("Central Inference Queue Worker started.")

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
            print("Central Inference Queue Worker stopped.")

    def _worker_loop(self):
        # 1. Load active settings and initialize AI engine
        try:
            from monitor_app.ai_engine import MotionOptimizedEngine, BasicMotionEngine, TF_AVAILABLE, YOLO_AVAILABLE
            ai_cfg = profile_store.get_ai_settings()
            profile = ai_cfg["active_profile"]
            custom_vals = ai_cfg["custom_settings"] if profile == "custom" else None

            ai_available = TF_AVAILABLE or YOLO_AVAILABLE
            if ai_available and MotionOptimizedEngine is not None:
                print("Central Inference initializing MotionOptimizedEngine (YOLO-GPU + MoveNet-CPU)...")
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
                print("Central Inference initializing BasicMotionEngine fallback...")
                self.engine = BasicMotionEngine(sensitivity=profile)
        except Exception as e:
            print(f"Central Inference Engine init failed: {e}")
            self.engine = None

        # 2. Main processing loop
        while self.running:
            try:
                task = self.task_queue.get(timeout=0.1)
                if task is None: # Stop signal
                    break
                
                packet = task.packet
                # Process inference if engine exists
                if self.engine:
                    try:
                        if packet.camera_id == "99":
                            res = packet.to_dict()
                        else:
                            res = self.engine.process_frame(packet.frame, packet.camera_id)
                        # Map outcome back to EvidencePacket
                        packet.frame = res.get("frame", packet.frame)
                        packet.num_people = res.get("num_people", 0)
                        packet.alert_triggered = bool(res.get("alert_triggered", False))
                        packet.alerts = res.get("alerts", [])
                        packet.detections = res.get("detections", {"behavior": [], "contraband": []})
                        packet.processing_mode = res.get("processing_mode", "Standard")

                        # --- PHASE 5: FUSION, DECISION & ALERT ROUTING ---
                        try:
                            from monitor_app.fusion import get_camera_fusion
                            from monitor_app.decision import get_decision_engine
                            from monitor_app.alert_manager import get_alert_manager

                            # 1. Update Fused Telemetry State
                            get_camera_fusion().update(packet)

                            # 2. Evaluate Decision
                            decision_engine = get_decision_engine()
                            if decision_engine.evaluate_trigger(packet):
                                # 3. Command Alert execution
                                evt_type, conf_scores = decision_engine.get_event_details(packet)
                                get_alert_manager().trigger_alert(
                                    camera_id=packet.camera_id,
                                    event_type=evt_type,
                                    confidence_scores=conf_scores,
                                    frame=packet.frame,
                                    ai_results=res
                                )
                        except Exception as route_ex:
                            print(f"Central Inference Phase 5 Routing Error: {route_ex}")

                    except Exception as ex:
                        print(f"Central Inference processing error for Cam {packet.camera_id}: {ex}")
                        packet.processing_mode = "Inference Error"
                else:
                    packet.processing_mode = "No AI Engine Loaded"

                task.result = packet
                task.event.set()
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Central Inference worker loop error: {e}")

    def submit_task(self, packet: EvidencePacket) -> EvidencePacket:
        """
        Submit a task to the queue. Enforces bounded size with frame-dropping
        and returns the processed EvidencePacket.
        """
        task = InferenceTask(packet)
        
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
                    dropped_task.event.set()
                    self.task_queue.task_done()
                except queue.Empty:
                    pass

        # Wait for processing with a 5.0 second timeout to prevent GUI freezes during cold starts
        finished = task.event.wait(timeout=5.0)
        if not finished:
            # Timeout recovery
            task.result = packet
            packet.processing_mode = "Inference Timeout"
        return task.result

# Global Centralized Inference Manager Singleton
_global_inference_manager = CentralInferenceManager()

def get_inference_manager() -> CentralInferenceManager:
    return _global_inference_manager
