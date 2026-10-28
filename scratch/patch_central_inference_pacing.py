# scratch/patch_central_inference_pacing.py

with open("monitor_app/central_inference.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. In __init__, add _in_flight_cameras and _in_flight_lock
old_init = """        self.movenet_skip = 2
        self.yolo_skip = 1"""

new_init = """        self.movenet_skip = 2
        self.yolo_skip = 1
        self._in_flight_cameras = set()
        self._in_flight_lock = threading.Lock()"""

if old_init in content:
    content = content.replace(old_init, new_init, 1)
    print("Added _in_flight_cameras to __init__")
else:
    print("Warning: old_init not found")

# 2. Add pacing helper methods
pacing_methods = """    def has_in_flight_task(self, camera_id: Any) -> bool:
        cam_str = str(camera_id)
        with self._in_flight_lock:
            return cam_str in self._in_flight_cameras

    def mark_task_in_flight(self, camera_id: Any):
        cam_str = str(camera_id)
        with self._in_flight_lock:
            self._in_flight_cameras.add(cam_str)

    def clear_task_in_flight(self, camera_id: Any):
        cam_str = str(camera_id)
        with self._in_flight_lock:
            self._in_flight_cameras.discard(cam_str)
"""

target_method = "    def has_active_tracks(self, camera_id: str) -> bool:"
if "def has_in_flight_task" not in content:
    content = content.replace(target_method, pacing_methods + "\n" + target_method, 1)
    print("Added pacing helper methods")

# 3. Update _draw_contraband_boxes signature and camera_id dismissal check
old_draw = """    def _draw_contraband_boxes(self, frame, detections):
        \"\"\"Single draw helper for contraband boxes (live + power-saving paths).
        Renders clean institutional bounding box with corner brackets and high-contrast pill badge.\"\"\"
        import cv2
        frame_h, frame_w = frame.shape[:2]
        base_thick = max(2, int(frame_w / 720))
        bracket_thick = base_thick + 1

        for det in self._contraband_for_render(detections):
            name = det.get("name", "Unknown")
            track_id = det.get("track_id", -1)
            conf = float(det.get("confidence", 0.0))
            x1, y1, x2, y2 = map(int, det.get("box", [0, 0, 0, 0]))

            is_dismissed = bool(det.get("dismissed"))"""

new_draw = """    def _draw_contraband_boxes(self, frame, detections, camera_id=None):
        \"\"\"Single draw helper for contraband boxes (live + power-saving paths).
        Renders clean institutional bounding box with corner brackets and high-contrast pill badge.\"\"\"
        import cv2
        frame_h, frame_w = frame.shape[:2]
        base_thick = max(2, int(frame_w / 720))
        bracket_thick = base_thick + 1

        for det in self._contraband_for_render(detections):
            name = det.get("name", "Unknown")
            track_id = det.get("track_id", -1)
            conf = float(det.get("confidence", 0.0))
            x1, y1, x2, y2 = map(int, det.get("box", [0, 0, 0, 0]))

            is_dismissed = bool(det.get("dismissed"))
            if not is_dismissed and camera_id is not None:
                from monitor_app.decision import get_dismissal_registry
                is_dismissed = get_dismissal_registry().is_track_dismissed(camera_id, track_id)"""

if old_draw in content:
    content = content.replace(old_draw, new_draw, 1)
    print("Updated _draw_contraband_boxes with camera_id check")
else:
    print("Warning: old_draw not found")

# 4. Pass camera_id to _draw_contraband_boxes call sites
content = content.replace(
    'self._draw_contraband_boxes(merged["frame"], merged["detections"]["contraband"])',
    'self._draw_contraband_boxes(merged["frame"], merged["detections"]["contraband"], camera_id=camera_id)'
)
content = content.replace(
    'self._draw_contraband_boxes(\n                                            res["frame"], res["detections"]["contraband"])',
    'self._draw_contraband_boxes(res["frame"], res["detections"]["contraband"], camera_id=packet.camera_id)'
)

# 5. Clear task in flight in _worker_loop
old_worker_done = """                task.event.set()
                self.task_queue.task_done()"""

new_worker_done = """                task.event.set()
                self.clear_task_in_flight(packet.camera_id)
                self.task_queue.task_done()"""

if old_worker_done in content:
    content = content.replace(old_worker_done, new_worker_done, 1)
    print("Added clear_task_in_flight to _worker_loop")

# 6. Mark and clear in submit_task and submit_task_async
old_submit_async = """    def submit_task_async(self, packet: EvidencePacket, callback: Optional[Callable] = None):
        \"\"\"
        Non-blocking task submission. Submits frame and returns immediately.
        When processing completes, callback(result_packet) is called from a background thread.
        
        This prevents camera worker threads from blocking on GPU inference.
        \"\"\"
        task = InferenceTask(packet, callback=callback)"""

new_submit_async = """    def submit_task_async(self, packet: EvidencePacket, callback: Optional[Callable] = None):
        \"\"\"
        Non-blocking task submission. Submits frame and returns immediately.
        When processing completes, callback(result_packet) is called from a background thread.
        
        This prevents camera worker threads from blocking on GPU inference.
        \"\"\"
        self.mark_task_in_flight(packet.camera_id)
        task = InferenceTask(packet, callback=callback)"""

if old_submit_async in content:
    content = content.replace(old_submit_async, new_submit_async, 1)
    print("Added mark_task_in_flight to submit_task_async")

old_drop_async = """                    dropped_task.event.set()
                    self.task_queue.task_done()"""

new_drop_async = """                    dropped_task.event.set()
                    self.clear_task_in_flight(dropped_task.packet.camera_id)
                    self.task_queue.task_done()"""

if old_drop_async in content:
    content = content.replace(old_drop_async, new_drop_async)
    print("Added clear_task_in_flight to dropped tasks")

# Synchronous submit_task
old_submit = """    def submit_task(self, packet: EvidencePacket) -> EvidencePacket:
        \"\"\"
        Submit a task to the queue. Enforces bounded size with frame-dropping
        and returns the processed EvidencePacket.
        \"\"\"
        task = InferenceTask(packet)"""

new_submit = """    def submit_task(self, packet: EvidencePacket) -> EvidencePacket:
        \"\"\"
        Submit a task to the queue. Enforces bounded size with frame-dropping
        and returns the processed EvidencePacket.
        \"\"\"
        self.mark_task_in_flight(packet.camera_id)
        task = InferenceTask(packet)"""

if old_submit in content:
    content = content.replace(old_submit, new_submit, 1)
    print("Added mark_task_in_flight to submit_task")

old_submit_return = """            from monitor_app.monitor_logging import SystemEvents
            SystemEvents.inference_timeout(packet.camera_id, 3.0)
        return task.result"""

new_submit_return = """            from monitor_app.monitor_logging import SystemEvents
            SystemEvents.inference_timeout(packet.camera_id, 3.0)
        self.clear_task_in_flight(packet.camera_id)
        return task.result"""

if old_submit_return in content:
    content = content.replace(old_submit_return, new_submit_return, 1)
    print("Added clear_task_in_flight to submit_task return")

with open("monitor_app/central_inference.py", "w", encoding="utf-8") as f:
    f.write(content)

print("monitor_app/central_inference.py updated successfully!")

