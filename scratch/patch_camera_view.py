with open('monitor_app/camera_view.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Patch start_monitoring stagger
target_connect = """        def connect_all():
            if self.cameras:
                with ThreadPoolExecutor(max_workers=len(self.cameras)) as executor:
                    futures = {executor.submit(connect_camera, cam): cam for cam in self.cameras}
                    for future in futures:
                        try:
                            future.result()
                        except Exception as e:
                            print(f"[Camera] Failed to connect {futures[future]}: {e}")
            self.after(0, self._hide_connecting_overlay)
            self.after(0, self._refresh_camera_widgets)
            
        threading.Thread(target=connect_all, daemon=True).start()"""

repl_connect = """        def connect_all():
            if self.cameras:
                import time
                for cam in self.cameras:
                    try:
                        connect_camera(cam)
                    except Exception as e:
                        print(f"[Camera] Failed to connect {cam}: {e}")
                    time.sleep(0.08)  # 80ms stagger prevents USB bus contention
            self.after(0, self._hide_connecting_overlay)
            self.after(0, self._refresh_camera_widgets)
            
        threading.Thread(target=connect_all, daemon=True).start()"""

assert target_connect in text, "target_connect not found"
text = text.replace(target_connect, repl_connect, 1)

# 2. Patch _open_capture: join thread before release, DSHOW first for webcams, probe read
target_open = """    def _open_capture(self):
        \"\"\"Open (or reopen) the video capture with fallback backends.\"\"\"
        if self.cap:
            old_cap = self.cap
            self.cap = None
            threading.Thread(target=lambda c: c.release(), args=(old_cap,), daemon=True).start()

        if self.cap_thread and self.cap_thread.is_alive():
            logger.info(f"Waiting for old capture thread of camera {self.camera_id} to exit...", camera_id=self.camera_id)
            self.cap_thread.join(timeout=3.0)
            self.cap_thread = None

        src = self.source
        # Try MSMF first (Windows default), then DirectShow fallback
        if isinstance(src, int):
            backends = [cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY]
        else:
            backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]"""

repl_open = """    def _open_capture(self):
        \"\"\"Open (or reopen) the video capture with fallback backends.\"\"\"
        if self.cap_thread and self.cap_thread.is_alive():
            logger.info(f"Waiting for old capture thread of camera {self.camera_id} to exit...", camera_id=self.camera_id)
            self.cap_thread.join(timeout=1.0)
            self.cap_thread = None

        if self.cap:
            old_cap = self.cap
            self.cap = None
            try:
                old_cap.release()
            except Exception:
                pass

        src = self.source
        # For integer webcams, prefer DSHOW on Windows because it releases cleanly and avoids MSMF device locks
        if isinstance(src, int):
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        else:
            backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]"""

assert target_open in text, "target_open not found"
text = text.replace(target_open, repl_open, 1)

# 3. Patch probe read in _open_capture
target_probe = """                if cap.isOpened():
                    if isinstance(src, int):
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    else:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        
                    self.cap = cap"""

repl_probe = """                if cap.isOpened():
                    if isinstance(src, int):
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    else:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                    # Probe read: verify the device handle actually yields valid frames
                    test_ret, test_frame = cap.read()
                    if not test_ret or test_frame is None or getattr(test_frame, "size", 0) == 0:
                        cap.release()
                        continue
                        
                    self.cap = cap"""

assert target_probe in text, "target_probe not found"
text = text.replace(target_probe, repl_probe, 1)

# 4. Patch CameraFeedWidget.stop() to join threads, close recorder, and drain queues
target_stop = """    def stop(self):
        self.running = False
        try:
            self.frame_queue.put_nowait((False, None))
        except Exception:
            pass
        if self.cap:
            old_cap = self.cap
            self.cap = None
            threading.Thread(target=lambda c: c.release(), args=(old_cap,), daemon=True).start()
        # AlertManager and IncidentRecorder are loosely coupled via EventBus
        utils.GlobalState.unregister_camera(self.camera_id)"""

repl_stop = """    def stop(self):
        self.running = False
        try:
            self.frame_queue.put_nowait((False, None))
        except Exception:
            pass

        # Join capture thread first so native read loop terminates
        if self.cap_thread and self.cap_thread.is_alive():
            self.cap_thread.join(timeout=0.8)
            self.cap_thread = None

        # Synchronously release capture handle once read thread is dead
        if self.cap:
            try:
                self.cap.release()
            except Exception as e:
                logger.debug(f"Error releasing capture on camera {self.camera_id}: {e}")
            self.cap = None

        # Join worker thread
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.8)
            self.worker_thread = None

        # Cleanly finalize and close incident recorder
        if hasattr(self, "recorder") and self.recorder:
            try:
                self.recorder.close()
            except Exception as e:
                logger.error(f"Error closing recorder for camera {self.camera_id}: {e}")

        # Drain queues
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break

        # AlertManager and IncidentRecorder are loosely coupled via EventBus
        utils.GlobalState.unregister_camera(self.camera_id)"""

assert target_stop in text, "target_stop not found"
text = text.replace(target_stop, repl_stop, 1)

with open('monitor_app/camera_view.py', 'w', encoding='utf-8', newline='') as f:
    f.write(text)

print("SUCCESS: camera_view.py patched")

