import os
import cv2
import time
import threading
import uuid
from datetime import datetime

from monitor_app.evidence import EvidencePacket
from monitor_app.ai_engine import MotionOptimizedEngine, BasicMotionEngine, TF_AVAILABLE, YOLO_AVAILABLE
from monitor_app.behaviors import get_behavior_engine
from monitor_app.decision import get_decision_engine

from monitor_app.exporters.session_exporter import SessionExporter
from monitor_app.loggers.offline_logger import OfflineLogger

class OfflineInferenceManager:
    def __init__(self, video_path, config, callback_frame, callback_progress, callback_complete):
        self.video_path = video_path
        self.config = config
        self.callback_frame = callback_frame
        self.callback_progress = callback_progress
        self.callback_complete = callback_complete
        
        self.running = False
        self.paused = False
        self.engine = None
        
        self.camera_id = f"OFFLINE_{uuid.uuid4().hex[:8]}"
        self.start_frame = config.get("start_frame", 0)
        self.end_frame = config.get("end_frame", None)
        self.profile = config.get("profile", "Standard")
        self.export_opts = config.get("export_options", {})
        
        # Format Session ID
        self.session_id = f"Session_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        from monitor_app.utils import data_path
        self.export_dir = data_path(f"exports/{self.session_id}")
        
        # Exporter and Logger initialization
        self.exporter = SessionExporter(self.export_dir, self.session_id, self.profile, self.video_path)
        self.logger = OfflineLogger(self.export_dir)
        
        self.logger.info("SYSTEM", "Initialization", f"Initialized Offline Analysis Session {self.session_id}")
        
        self.all_detections = []
        self.detailed_incidents = []
        self.telemetry = []
        self.video_writer = None

    def start(self):
        self.running = True
        threading.Thread(target=self._run_analysis, daemon=True).start()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        
    def request_step(self):
        self.step_requested = True

    def stop(self):
        self.running = False

    def _initialize_engine(self):
        ai_available = TF_AVAILABLE or YOLO_AVAILABLE
        sens_map = {"Quick": "low", "Standard": "medium", "Benchmark": "medium", "Forensic": "high"}
        sens = sens_map.get(self.profile, "medium")
        
        self.logger.info("AI", "Engine", f"Initializing engine with sensitivity {sens}")
        
        if ai_available and MotionOptimizedEngine is not None:
            self.engine = MotionOptimizedEngine(
                debug=False,
                sensitivity=sens,
                enable_yolo=True,
                prefer_gpu=True,
                force_gpu=True,
                force_yolo_gpu=True
            )
        else:
            self.engine = BasicMotionEngine(sensitivity=sens)

    def _run_analysis(self):
        self.logger.info("SYSTEM", "Pipeline", "Starting offline analysis loop")
        self._initialize_engine()
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            self.logger.error("CAMERA", "VideoCapture", "Could not open video file")
            self.callback_complete({"status": "Failed", "error": "Could not open video file"})
            return
            
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if self.export_opts.get("mp4", False):
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(
                os.path.join(self.export_dir, "annotated_video.mp4"),
                fourcc, fps, (width, height)
            )
            
        if self.start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
            
        current_frame = self.start_frame
        end_f = self.end_frame if self.end_frame is not None else total_frames
        
        self.step_requested = False

        decision_engine = get_decision_engine()
        behavior_engine = get_behavior_engine()
        
        start_time = time.time()

        # Helper to format video time
        def format_video_time(frame_num, fps):
            seconds = frame_num / fps
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours:02d}:{mins:02d}:{secs:06.3f}"

        import psutil

        while self.running and current_frame < end_f:
            if self.paused and not self.step_requested:
                time.sleep(0.05)
                continue
                
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_start_time = time.perf_counter()
            video_time_str = format_video_time(current_frame, fps)
            
            packet = EvidencePacket(
                camera_id=self.camera_id,
                frame=frame.copy(),
                timestamp=time.time(),
                frame_uuid=str(uuid.uuid4())
            )
            
            if self.engine and isinstance(self.engine, MotionOptimizedEngine):
                # OFFLINE MODE: Bypass the motion gate and throttle.
                # process_frame() skips YOLO if no motion is detected (correct for live,
                # but catastrophic for forensic analysis of static scenes like a detainee
                # sitting with a cellphone). We call the internal AI methods directly.
                res = {
                    "frame": frame.copy(), "motion_detected": True, "motion_score": 0,
                    "num_people": 0, "alert_triggered": False, "alerts": [],
                    "detections": {"behavior": [], "contraband": []},
                    "processing_mode": "Offline Forensic (No Gate)"
                }
                with self.engine.lock:
                    self.engine.stats["total"] += 1
                    self.engine.stats["ai_runs"] += 1

                # Run MoveNet (pose/behavior)
                if self.engine.movenet:
                    with self.engine.tf_inference_lock:
                        self.engine._run_movenet_logic(res, self.camera_id)

                # Run YOLO (contraband detection) — THE CRITICAL PATH
                if self.engine.enable_yolo and self.engine.yolo_custom:
                    with self.engine.yolo_inference_lock:
                        self.engine._run_yolo_logic(res, self.camera_id)

                packet.frame = res.get("frame", packet.frame)
                packet.num_people = res.get("num_people", 0)
                packet.alert_triggered = bool(res.get("alert_triggered", False))
                packet.alerts = res.get("alerts", [])
                packet.detections = res.get("detections", {"behavior": [], "contraband": []})
                packet.tracked_persons = list(res.get("tracked_persons", []))
            elif self.engine:
                # Fallback for BasicMotionEngine
                res = self.engine.process_frame(packet.frame, self.camera_id, packet.frame_uuid)
                packet.frame = res.get("frame", packet.frame)
                packet.num_people = res.get("num_people", 0)
                packet.alert_triggered = bool(res.get("alert_triggered", False))
                packet.alerts = res.get("alerts", [])
                packet.detections = res.get("detections", {"behavior": [], "contraband": []})
                packet.tracked_persons = list(res.get("tracked_persons", []))
                
            behavior_engine.analyze_packet(packet, current_frame, "medium")
            
            for ev in packet.behavior_evidence:
                alert_str = f"Person {ev.stable_id}: {ev.behavior_type.upper()}"
                if alert_str not in packet.alerts:
                    packet.alerts.append(alert_str)
            if packet.behavior_evidence:
                packet.alert_triggered = True

            # Extract full detection records (Persons, Behaviors, YOLO Objects)
            for p in packet.tracked_persons:
                bbox_str = ""
                bbox = None
                if p.keypoints is not None:
                    valid_kpts = [kp for kp in p.keypoints if kp[2] > 0.1]
                    if valid_kpts:
                        h, w = packet.frame.shape[:2]
                        xs = [kp[1] for kp in valid_kpts]
                        ys = [kp[0] for kp in valid_kpts]
                        bbox = (int(min(xs)*w), int(min(ys)*h), int(max(xs)*w), int(max(ys)*h))
                        p.bbox = bbox
                        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
                        
                        is_alert = any(ev.stable_id == p.stable_id for ev in packet.behavior_evidence)
                        color = (0, 0, 255) if is_alert else (0, 255, 0)
                        cv2.rectangle(packet.frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                        cv2.putText(packet.frame, f"ID {p.stable_id}", (bbox[0], max(0, bbox[1] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                self.all_detections.append({
                    "frame_number": current_frame,
                    "timestamp": packet.timestamp,
                    "video_time": video_time_str,
                    "detection_class": "Person",
                    "confidence": 1.0,  # Person tracker confidence approx
                    "bounding_box": bbox_str,
                    "track_id": p.stable_id,
                    "camera_source": os.path.basename(self.video_path)
                })
                
            # Add YOLO Contraband
            for c in packet.detections.get("contraband", []):
                self.all_detections.append({
                    "frame_number": current_frame,
                    "timestamp": packet.timestamp,
                    "video_time": video_time_str,
                    "detection_class": c.get("name", "Unknown"),
                    "confidence": c.get("confidence", 0.0),
                    "bounding_box": str(c.get("box", "")),
                    "track_id": c.get("track_id", ""),
                    "camera_source": os.path.basename(self.video_path)
                })
                
            # Add Behaviors
            for b in packet.behavior_evidence:
                self.all_detections.append({
                    "frame_number": current_frame,
                    "timestamp": packet.timestamp,
                    "video_time": video_time_str,
                    "detection_class": b.behavior_type,
                    "confidence": 1.0,
                    "bounding_box": "",
                    "track_id": b.stable_id,
                    "camera_source": os.path.basename(self.video_path)
                })

            # Decision evaluation
            if decision_engine.evaluate_trigger(packet):
                from monitor_app.evidence import SnapshotResult
                
                # Let DecisionEngine handle all business logic
                incident = decision_engine.generate_incident_record(
                    packet, self.session_id, current_frame, video_time_str
                )
                
                if incident.snapshot_required:
                    snap_path = os.path.join(self.exporter.gallery_dir, incident.snapshot_filename)
                    success = cv2.imwrite(snap_path, packet.frame)
                    if success:
                        incident.snapshot_result = SnapshotResult.SUCCESS
                        self.logger.info(
                            "Decision Engine", "Incident", 
                            f"Critical incident {incident.incident_type.value} detected. Snapshot saved: {incident.snapshot_reason}", 
                            reference_id=incident.incident_id
                        )
                    else:
                        incident.snapshot_result = SnapshotResult.WRITE_FAILED
                        self.logger.error("Decision Engine", "Incident", f"Failed to write snapshot for {incident.incident_id}")
                else:
                    incident.snapshot_result = SnapshotResult.NOT_CRITICAL
                
                self.detailed_incidents.append(incident.to_dict())

            frame_time = time.perf_counter() - frame_start_time
            cpu_pct = psutil.cpu_percent()
            ram_pct = psutil.virtual_memory().percent
            
            self.telemetry.append({
                "frame": current_frame,
                "latency_ms": frame_time * 1000,
                "fps": 1.0 / max(0.001, frame_time),
                "num_people": packet.num_people,
                "cpu_percent": cpu_pct,
                "ram_percent": ram_pct
            })

            # Write annotated frame
            if self.video_writer:
                self.video_writer.write(packet.frame)
                
            # Callbacks
            if self.callback_frame:
                import tkinter as tk
                # packet.frame is BGR, cvtColor is already handled in offline_ui.py _on_frame_ready
                # We just pass the BGR frame directly
                self.callback_frame(packet.frame, current_frame, end_f)
                
            if self.callback_progress:
                pct = (current_frame / end_f) * 100
                self.callback_progress(pct)

            current_frame += 1
            self.step_requested = False

        cap.release()
        if self.video_writer:
            self.video_writer.release()
            
        total_time = time.time() - start_time
        self.logger.info("SYSTEM", "Pipeline", f"Analysis complete in {total_time:.2f}s")
        
        # Single Source of Truth export execution
        status = self.exporter.export_all(
            self.all_detections, 
            self.detailed_incidents, 
            self.telemetry, 
            total_time, 
            current_frame - self.start_frame
        )
        
        avg_fps = sum(t["fps"] for t in self.telemetry) / len(self.telemetry) if self.telemetry else 0
        avg_latency = sum(t["latency_ms"] for t in self.telemetry) / len(self.telemetry) if self.telemetry else 0
        
        self.callback_complete({
            "status": status, 
            "duration": f"{total_time:.2f}s",
            "frames_processed": current_frame - self.start_frame,
            "avg_fps": f"{avg_fps:.1f}",
            "avg_latency": f"{avg_latency:.1f}ms",
            "incidents": len(self.detailed_incidents),
            "export_dir": self.export_dir
        })
