with open('monitor_app/camera_view.py', 'r', encoding='utf-8') as f:
    cv_text = f.read()

# 1. Update CameraMonitorScreen.__init__ attributes
target_init = """        self.cameras = []
        self.grid_container = None
        self.active_alert_incident_id = None
        self._alert_banner_visible = False
        self._alert_thumb_photo = None
        self._alert_auto_dismiss_job = None"""

repl_init = """        self.cameras = []
        self.grid_container = None
        self.active_alert_incident_id = None
        self._alert_banner_visible = False
        self._alert_thumb_photo = None
        self._alert_auto_dismiss_job = None
        self._is_monitoring = False
        self._connecting = False
        self._connect_thread = None
        self._poll_connecting_job = None"""

assert target_init in cv_text, "target_init not found"
cv_text = cv_text.replace(target_init, repl_init, 1)

# 2. Update _on_incident_alert and _on_decision_alert
target_alerts = """    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for confirmed incidents\"\"\"
        self.after(0, lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity: self._show_alert_banner(c, i, e, f, severity=s))

    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for fast preliminary decision triggers\"\"\"
        self.after(0, lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity: self._show_alert_banner(c, i, e, f, sc, severity=s))"""

repl_alerts = """    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for confirmed incidents\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                self.after_idle(lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity: self._show_alert_banner(c, i, e, f, severity=s))
        except Exception:
            pass

    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for fast preliminary decision triggers\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                self.after_idle(lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity: self._show_alert_banner(c, i, e, f, sc, severity=s))
        except Exception:
            pass"""

assert target_alerts in cv_text, "target_alerts not found"
cv_text = cv_text.replace(target_alerts, repl_alerts, 1)

# 3. Update start_monitoring and stop_monitoring in CameraMonitorScreen
target_start_stop = """    def start_monitoring(self):
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().start()
        
        self._show_connecting_overlay()
        
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        def connect_camera(cam):
            cam.start()
            return cam

        def connect_all():
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
            
        threading.Thread(target=connect_all, daemon=True).start()

    def _show_connecting_overlay(self):
        if not hasattr(self, 'loading_overlay') or not self.loading_overlay.winfo_exists():
            self.loading_overlay = ctk.CTkFrame(self.grid_container, fg_color="black", bg_color="black")
            self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            
            lbl = ctk.CTkLabel(
                self.loading_overlay, 
                text="Connecting to cameras...", 
                font=("Segoe UI Bold", 24), 
                text_color="white"
            )
            lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_connecting_overlay(self):
        if hasattr(self, 'loading_overlay') and self.loading_overlay.winfo_exists():
            self.loading_overlay.destroy()

    def _refresh_camera_widgets(self):
        pass

    def stop_monitoring(self):
        try:
            from monitor_app.events import get_event_bus
            get_event_bus().unsubscribe("INCIDENT_START", self._on_incident_alert)
            get_event_bus().unsubscribe("DECISION_TRIGGER", self._on_decision_alert)
        except Exception:
            pass
        if self._alert_auto_dismiss_job:
            self.after_cancel(self._alert_auto_dismiss_job)
            self._alert_auto_dismiss_job = None
        for cam in self.cameras:
            cam.stop()
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().stop()"""

repl_start_stop = """    def start_monitoring(self):
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().start()
        
        self._is_monitoring = True
        self._connecting = True
        self._show_connecting_overlay()
        
        import threading
        
        def connect_camera(cam):
            cam.start()
            return cam

        def connect_all():
            if self.cameras:
                import time
                for cam in list(self.cameras):
                    if not getattr(self, "_is_monitoring", False):
                        break
                    try:
                        connect_camera(cam)
                    except Exception as e:
                        print(f"[Camera] Failed to connect {cam}: {e}")
                    time.sleep(0.08)  # 80ms stagger prevents USB bus contention
            self._connecting = False
            
        self._connect_thread = threading.Thread(target=connect_all, daemon=True)
        self._connect_thread.start()
        self._poll_connecting_status()

    def _poll_connecting_status(self):
        if not self.winfo_exists() or not getattr(self, "_is_monitoring", False):
            self._hide_connecting_overlay()
            return
        if not getattr(self, "_connecting", True):
            self._hide_connecting_overlay()
            self._refresh_camera_widgets()
        else:
            self._poll_connecting_job = self.after(100, self._poll_connecting_status)

    def _show_connecting_overlay(self):
        if not hasattr(self, 'loading_overlay') or not self.loading_overlay.winfo_exists():
            self.loading_overlay = ctk.CTkFrame(self.grid_container, fg_color="black", bg_color="black")
            self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            
            lbl = ctk.CTkLabel(
                self.loading_overlay, 
                text="Connecting to cameras...", 
                font=("Segoe UI Bold", 24), 
                text_color="white"
            )
            lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_connecting_overlay(self):
        if hasattr(self, 'loading_overlay') and self.loading_overlay.winfo_exists():
            self.loading_overlay.destroy()

    def _refresh_camera_widgets(self):
        pass

    def stop_monitoring(self):
        self._is_monitoring = False
        self._connecting = False
        if hasattr(self, "_poll_connecting_job") and self._poll_connecting_job:
            try:
                self.after_cancel(self._poll_connecting_job)
            except Exception:
                pass
            self._poll_connecting_job = None
        if self._alert_auto_dismiss_job:
            try:
                self.after_cancel(self._alert_auto_dismiss_job)
            except Exception:
                pass
            self._alert_auto_dismiss_job = None
        try:
            from monitor_app.events import get_event_bus
            get_event_bus().unsubscribe("INCIDENT_START", self._on_incident_alert)
            get_event_bus().unsubscribe("DECISION_TRIGGER", self._on_decision_alert)
        except Exception:
            pass
        for cam in self.cameras:
            cam.stop()
        if hasattr(self, "_connect_thread") and self._connect_thread and self._connect_thread.is_alive():
            self._connect_thread.join(timeout=1.5)
            self._connect_thread = None
        from monitor_app.central_inference import get_inference_manager
        get_inference_manager().stop()"""

assert target_start_stop in cv_text, "target_start_stop not found"
cv_text = cv_text.replace(target_start_stop, repl_start_stop, 1)

# 4. In CameraFeedWidget.__init__, add UI loop init and flags
target_widget_init = """        self.recorder = IncidentRecorder(self.camera_id)
        self.last_alert_triggered = False
        self.last_alert_desc = ""
        
        # Local CPU motion gating
        self.gater = LocalMotionGater()

        self.setup_ui()"""

repl_widget_init = """        self.recorder = IncidentRecorder(self.camera_id)
        self.last_alert_triggered = False
        self.last_alert_desc = ""
        self.is_offline = False
        self.is_stopped = False
        
        # Local CPU motion gating
        self.gater = LocalMotionGater()

        self.setup_ui()
        self.after(50, self.update_loop)"""

assert target_widget_init in cv_text, "target_widget_init not found"
cv_text = cv_text.replace(target_widget_init, repl_widget_init, 1)

# 5. In CameraFeedWidget.start(), remove cross-thread self.after(0, self.update_loop)
target_widget_start = """        # Track active cameras globally
        utils.GlobalState.register_camera(self.camera_id)
        self.after(0, self.update_loop)"""

repl_widget_start = """        # Track active cameras globally
        utils.GlobalState.register_camera(self.camera_id)"""

assert target_widget_start in cv_text, "target_widget_start not found"
cv_text = cv_text.replace(target_widget_start, repl_widget_start, 1)

# 6. In CameraFeedWidget._open_capture, replace cross-thread self.after with self.is_offline = True
target_offline = """        print(f"Camera {self.camera_id}: could not open source '{src}'")
        
        def _set_offline():
            try:
                self.lbl_status.configure(text="OFFLINE", foreground="#f25c5c")
                self.draw_placeholder("Offline")
            except Exception:
                pass
        self.after(0, _set_offline)"""

repl_offline = """        print(f"Camera {self.camera_id}: could not open source '{src}'")
        self.is_offline = True"""

assert target_offline in cv_text, "target_offline not found"
cv_text = cv_text.replace(target_offline, repl_offline, 1)

# 7. In _on_inference_complete: ALWAYS forward frame to result_queue so canvas never freezes
target_cb = """                    cam_self = self  # capture reference for callback closure
                    def _on_inference_complete(result_packet, _cam_self=cam_self, _bfidx=benchmark_frame_idx):
                        try:
                            # Drop backpressure frames silently so canvas retains the last valid annotated frame
                            if getattr(result_packet, "processing_mode", None) == "Queue Drop (Backpressure)":
                                return

                            frame_to_show = result_packet.frame
                            alert_active = result_packet.alert_triggered
                            
                            # OpenCV resize on background thread: use INTER_AREA when downscaling for crisp non-pixelated lines
                            cw = _cam_self.target_width
                            ch = _cam_self.target_height
                            interp = cv2.INTER_AREA if (frame_to_show.shape[1] > cw and frame_to_show.shape[0] > ch) else cv2.INTER_LINEAR
                            resized_bgr = cv2.resize(frame_to_show, (cw, ch), interpolation=interp)
                            rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                            img_pil = Image.fromarray(rgb)
                            
                            alert_desc = result_packet.alerts[0] if (getattr(result_packet, "alerts", None) and len(result_packet.alerts) > 0) else ""
                            if _cam_self.result_queue.full():
                                try:
                                    _cam_self.result_queue.get_nowait()
                                except queue.Empty:
                                    pass
                            _cam_self.result_queue.put((img_pil, alert_active, alert_desc))
                            
                            # Incident recording
                            _cam_self.recorder.process_frame(frame_to_show, result_packet.to_dict())
                        except Exception as e:
                            print(f"Async callback error (Cam {_cam_self.camera_id}): {e}")"""

repl_cb = """                    cam_self = self  # capture reference for callback closure
                    def _on_inference_complete(result_packet, _cam_self=cam_self, _bfidx=benchmark_frame_idx):
                        try:
                            frame_to_show = result_packet.frame
                            alert_active = result_packet.alert_triggered
                            
                            # OpenCV resize on background thread: use INTER_AREA when downscaling for crisp non-pixelated lines
                            cw = _cam_self.target_width
                            ch = _cam_self.target_height
                            interp = cv2.INTER_AREA if (frame_to_show.shape[1] > cw and frame_to_show.shape[0] > ch) else cv2.INTER_LINEAR
                            resized_bgr = cv2.resize(frame_to_show, (cw, ch), interpolation=interp)
                            rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
                            img_pil = Image.fromarray(rgb)
                            
                            alert_desc = result_packet.alerts[0] if (getattr(result_packet, "alerts", None) and len(result_packet.alerts) > 0) else ""
                            if _cam_self.result_queue.full():
                                try:
                                    _cam_self.result_queue.get_nowait()
                                except queue.Empty:
                                    pass
                            _cam_self.result_queue.put((img_pil, alert_active, alert_desc))
                            
                            # Incident recording (only process full inference frames)
                            if getattr(result_packet, "processing_mode", None) != "Queue Drop (Backpressure)":
                                _cam_self.recorder.process_frame(frame_to_show, result_packet.to_dict())
                        except Exception as e:
                            print(f"Async callback error (Cam {_cam_self.camera_id}): {e}")"""

assert target_cb in cv_text, "target_cb not found"
cv_text = cv_text.replace(target_cb, repl_cb, 1)

# 8. In CameraFeedWidget.stop(): safe asynchronous release if capture thread still finishing
target_cam_stop = """    def stop(self):
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
            self.worker_thread = None"""

repl_cam_stop = """    def stop(self):
        self.running = False
        self.is_stopped = True
        try:
            self.frame_queue.put_nowait((False, None))
        except Exception:
            pass

        # Join capture thread first so native read loop terminates
        if self.cap_thread and self.cap_thread.is_alive():
            self.cap_thread.join(timeout=0.5)

        # Release capture handle cleanly
        if self.cap:
            old_cap = self.cap
            self.cap = None
            if self.cap_thread and self.cap_thread.is_alive():
                # Cap thread still finishing a blocking read; let it finish then release
                def _safe_release(c, ct):
                    try:
                        ct.join(timeout=1.5)
                        c.release()
                    except Exception:
                        pass
                threading.Thread(target=_safe_release, args=(old_cap, self.cap_thread), daemon=True).start()
            else:
                try:
                    old_cap.release()
                except Exception as e:
                    logger.debug(f"Error releasing capture on camera {self.camera_id}: {e}")
            self.cap_thread = None

        # Join worker thread
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
            self.worker_thread = None"""

assert target_cam_stop in cv_text, "target_cam_stop not found"
cv_text = cv_text.replace(target_cam_stop, repl_cam_stop, 1)

# 9. In CameraFeedWidget.update_loop(), check is_stopped and is_offline
target_update_loop = """    def update_loop(self):
        if not self.running:
            return

        frame_rgb = None
        alert_triggered = False

        # --- real camera (poll queue) ---
        if self.source is not None:
            try:
                # Try to get latest from worker (non-blocking)
                item = self.result_queue.get_nowait()
                if len(item) == 3:
                    frame_rgb, alert_triggered, alert_desc = item
                else:
                    frame_rgb, alert_triggered = item
                    alert_desc = ""
                self.last_alert_triggered = bool(alert_triggered)
                if alert_triggered and alert_desc:
                    self.last_alert_desc = alert_desc
            except queue.Empty:
                # If no new frame from worker, just continue with old or skip
                frame_rgb = None
                pass
            
            # Special case for "Signal Lost" or "Reconnecting" handled by worker not putting data
            is_recon = getattr(self, "is_reconnecting", False)
            if frame_rgb is None and (not self.cap or not self.cap.isOpened() or is_recon):
                status_text = "Reconnecting..." if is_recon else "Signal Lost"
                self.draw_placeholder(status_text)
                
                status_lbl = "RECONNECTING" if is_recon else "OFFLINE"
                status_color = "#ff9f43" if is_recon else "#f25c5c"
                self.lbl_status.configure(text=status_lbl, foreground=status_color)
                
                self.after(30, self.update_loop)
                return"""

repl_update_loop = """    def update_loop(self):
        if getattr(self, "is_stopped", False) or not self.winfo_exists():
            return

        if not self.running:
            self.after(50, self.update_loop)
            return

        if getattr(self, "is_offline", False):
            self.lbl_status.configure(text="OFFLINE", foreground="#f25c5c")
            self.draw_placeholder("Offline")
            self.after(self.ui_frame_interval_ms, self.update_loop)
            return

        frame_rgb = None
        alert_triggered = False

        # --- real camera (poll queue) ---
        if self.source is not None:
            try:
                # Try to get latest from worker (non-blocking)
                item = self.result_queue.get_nowait()
                if len(item) == 3:
                    frame_rgb, alert_triggered, alert_desc = item
                else:
                    frame_rgb, alert_triggered = item
                    alert_desc = ""
                self.last_alert_triggered = bool(alert_triggered)
                if alert_triggered and alert_desc:
                    self.last_alert_desc = alert_desc
            except queue.Empty:
                # If no new frame from worker, just continue with old or skip
                frame_rgb = None
                pass
            
            # Special case for "Signal Lost" or "Reconnecting" handled by worker not putting data
            is_recon = getattr(self, "is_reconnecting", False)
            if frame_rgb is None and (not self.cap or not self.cap.isOpened() or is_recon):
                status_text = "Reconnecting..." if is_recon else "Signal Lost"
                self.draw_placeholder(status_text)
                
                status_lbl = "RECONNECTING" if is_recon else "OFFLINE"
                status_color = "#ff9f43" if is_recon else "#f25c5c"
                self.lbl_status.configure(text=status_lbl, foreground=status_color)
                
                self.after(30, self.update_loop)
                return"""

assert target_update_loop in cv_text, "target_update_loop not found"
cv_text = cv_text.replace(target_update_loop, repl_update_loop, 1)

with open('monitor_app/camera_view.py', 'w', encoding='utf-8', newline='') as f:
    f.write(cv_text)

print("SUCCESS: monitor_app/camera_view.py updated")

