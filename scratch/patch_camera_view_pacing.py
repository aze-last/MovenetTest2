# scratch/patch_camera_view_pacing.py

with open("monitor_app/camera_view.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """                if gate_active:
                    # Initialize initial packet and submit to centralized GPU queue"""

replacement = """                if gate_active:
                    # Pacing check: if this camera already has an inference task in flight,
                    # don't pile onto task_queue to cause backpressure drop.
                    # Instead, push current frame directly into display queue (smooth 30 FPS display)
                    # while GPU processes the previous frame.
                    if manager.has_in_flight_task(str(self.camera_id)):
                        cw = self.target_width
                        ch = self.target_height
                        interp = cv2.INTER_AREA if (raw_frame.shape[1] > cw and raw_frame.shape[0] > ch) else cv2.INTER_LINEAR
                        resized_bgr = cv2.resize(raw_frame, (cw, ch), interpolation=interp)
                        rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                        img_pil = Image.fromarray(rgb)
                        
                        if self.result_queue.full():
                            try:
                                self.result_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self.result_queue.put((img_pil, getattr(self, "last_alert_triggered", False), getattr(self, "last_alert_desc", "")))
                        continue

                    # Initialize initial packet and submit to centralized GPU queue"""

if target in content:
    content = content.replace(target, replacement, 1)
    print("Replaced camera_view.py inference pacing check successfully!")
else:
    print("Warning: target not found in camera_view.py")

with open("monitor_app/camera_view.py", "w", encoding="utf-8") as f:
    f.write(content)

print("monitor_app/camera_view.py updated successfully!")

