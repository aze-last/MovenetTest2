import os
import re

def patch_camera_view():
    path = 'monitor_app/camera_view.py'
    with open(path, 'r', encoding='utf-8') as f:
        cv = f.read()

    # 1. Init variables
    if 'self.last_alert_triggered = False' not in cv:
        target = 'self.recorder = IncidentRecorder(self.camera_id)'
        replacement = 'self.recorder = IncidentRecorder(self.camera_id)\n        self.last_alert_triggered = False\n        self.last_alert_desc = ""'
        assert target in cv, "IncidentRecorder init not found"
        cv = cv.replace(target, replacement, 1)

    # 2. Async callback queue put
    target_cb = '''                            if _cam_self.result_queue.full():
                                try:
                                    _cam_self.result_queue.get_nowait()
                                except queue.Empty:
                                    pass
                            _cam_self.result_queue.put((img_pil, alert_active))'''

    replacement_cb = '''                            alert_desc = result_packet.alerts[0] if (getattr(result_packet, "alerts", None) and len(result_packet.alerts) > 0) else ""
                            if _cam_self.result_queue.full():
                                try:
                                    _cam_self.result_queue.get_nowait()
                                except queue.Empty:
                                    pass
                            _cam_self.result_queue.put((img_pil, alert_active, alert_desc))'''

    if target_cb in cv:
        cv = cv.replace(target_cb, replacement_cb, 1)

    # 3. Update loop queue get
    target_get = '''            try:
                # Try to get latest from worker (non-blocking)
                rgb_data, alert_triggered = self.result_queue.get_nowait()
                frame_rgb = rgb_data
            except queue.Empty:
                # If no new frame from worker, just continue with old or skip
                frame_rgb = None
                # We don't return here so we don't break the loop, 
                # but we'll skip the drawing block if frame_rgb is None
                pass'''

    replacement_get = '''            try:
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
                pass'''

    if target_get in cv:
        cv = cv.replace(target_get, replacement_get, 1)

    # 4. Status block
    target_status = '''        # --- status ---
        # Show status from the recorder (NORMAL, RECORDING, or COOLDOWN)
        status_text, status_color = self.recorder.get_status_info()
        self.lbl_status.configure(text=status_text, foreground=status_color)
        
        # Dynamically highlight card canvas border based on state
        if self.recorder.state == self.recorder.RECORDING:
            self.canvas.configure(highlightthickness=3, highlightbackground="#f25c5c")
        elif self.recorder.state == self.recorder.COOLDOWN:
            self.canvas.configure(highlightthickness=2, highlightbackground="#ffa500")
        else:
            self.canvas.configure(highlightthickness=1, highlightbackground="#1e2c3a")
        
        # Update global alert state
        utils.GlobalState.set_alert(self.camera_id, self.recorder.state == self.recorder.RECORDING)'''

    replacement_status = '''        # --- status ---
        # Show status from recorder or active AI detection
        rec_status, rec_color = self.recorder.get_status_info()
        if self.recorder.state == self.recorder.RECORDING:
            status_text = rec_status
            status_color = rec_color
            self.canvas.configure(highlightthickness=3, highlightbackground="#f25c5c")
            utils.GlobalState.set_alert(self.camera_id, True)
        elif self.recorder.state == self.recorder.COOLDOWN:
            status_text = rec_status
            status_color = rec_color
            self.canvas.configure(highlightthickness=2, highlightbackground="#ffa500")
            utils.GlobalState.set_alert(self.camera_id, False)
        elif getattr(self, "last_alert_triggered", False):
            tag = f": {self.last_alert_desc}" if getattr(self, "last_alert_desc", "") else ""
            status_text = f"ALERT{tag}"
            status_color = "#f25c5c"
            self.canvas.configure(highlightthickness=2, highlightbackground="#f25c5c")
            utils.GlobalState.set_alert(self.camera_id, True)
        else:
            status_text = "NORMAL"
            status_color = utils.COLOR_SUCCESS
            self.canvas.configure(highlightthickness=1, highlightbackground="#1e2c3a")
            utils.GlobalState.set_alert(self.camera_id, False)

        self.lbl_status.configure(text=status_text, foreground=status_color)'''

    if target_status in cv:
        cv = cv.replace(target_status, replacement_status, 1)

    # 5. Alert banner & review incident in CameraMonitorScreen
    target_callbacks = '''    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for confirmed incidents"""
        self.after(0, lambda: self._show_alert_banner(camera_id, incident_id, event_type, frame, severity=severity))

    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for fast preliminary decision triggers"""
        self.after(0, lambda: self._show_alert_banner(camera_id, getattr(self, "active_alert_incident_id", None), event_type, frame, confidence_scores, severity=severity))

    def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None):
        self.active_alert_incident_id = incident_id'''

    replacement_callbacks = '''    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for confirmed incidents"""
        self.after(0, lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity: self._show_alert_banner(c, i, e, f, severity=s))

    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        """EventBus callback for fast preliminary decision triggers"""
        self.after(0, lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity: self._show_alert_banner(c, i, e, f, sc, severity=s))

    def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None):
        if incident_id:
            self.active_alert_incident_id = incident_id'''

    if target_callbacks in cv:
        cv = cv.replace(target_callbacks, replacement_callbacks, 1)

    target_review = '''    def _review_active_incident(self):
        """Jump to Incidents screen with the current active alert incident loaded."""
        root = self.winfo_toplevel()
        if hasattr(root, "switch_screen"):
            root.switch_screen("Incidents", initial_incident_id=self.active_alert_incident_id)'''

    replacement_review = '''    def _review_active_incident(self):
        """Jump to Incidents screen with the current active alert incident loaded."""
        root = self.winfo_toplevel()
        target_id = getattr(self, "active_alert_incident_id", None)
        if not target_id:
            try:
                import sqlite3
                from monitor_app.utils import data_path
                db = data_path("incidents.db")
                if os.path.exists(db):
                    conn = sqlite3.connect(db)
                    c = conn.cursor()
                    c.execute("SELECT event_id FROM incidents ORDER BY timestamp_start DESC LIMIT 1")
                    row = c.fetchone()
                    conn.close()
                    if row:
                        target_id = row[0]
            except Exception as e:
                logger.error(f"Failed to fetch latest incident for review: {e}")
        if hasattr(root, "switch_screen"):
            root.switch_screen("Incidents", initial_incident_id=target_id)'''

    if target_review in cv:
        cv = cv.replace(target_review, replacement_review, 1)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(cv)
    print("Patched camera_view.py successfully.")

def patch_incidents():
    path = 'monitor_app/incidents.py'
    with open(path, 'r', encoding='utf-8') as f:
        inc = f.read()

    # 1. Subscribe to events in __init__
    target_init = '''        self._build_header()
        self._build_tabs()
        self.refresh_overview()'''

    replacement_init = '''        self._build_header()
        self._build_tabs()
        self.refresh_overview()

        # Real-time EventBus synchronization
        from monitor_app.events import get_event_bus, INCIDENT_START, INCIDENT_STOP, TELEM_DB_WRITE_COMPLETE
        bus = get_event_bus()
        self._bus_handlers = {
            "INCIDENT_START": self._on_live_incident_start,
            "INCIDENT_STOP": self._on_live_incident_stop,
            TELEM_DB_WRITE_COMPLETE: self._on_live_db_complete
        }
        for event, handler in self._bus_handlers.items():
            bus.subscribe(event, handler)'''

    if target_init in inc:
        inc = inc.replace(target_init, replacement_init, 1)

    # 2. Add stop_monitoring / event methods
    target_stop = '''    def stop_monitoring(self):
        if hasattr(self, "review_tab") and self.review_tab:
            self.review_tab.stop_monitoring()'''

    replacement_stop = '''    def _on_live_incident_start(self, *args, **kwargs):
        self.after(300, self._refresh_live_state)

    def _on_live_incident_stop(self, *args, **kwargs):
        self.after(600, self._refresh_live_state)

    def _on_live_db_complete(self, *args, **kwargs):
        self.after(300, self._refresh_live_state)

    def _refresh_live_state(self):
        try:
            self.refresh_overview()
            if hasattr(self, "review_tab") and self.review_tab:
                self.review_tab.refresh_inbox(auto_select_first=False)
            if hasattr(self, "log_tab") and self.log_tab:
                self.log_tab.refresh_data()
        except Exception:
            pass

    def stop_monitoring(self):
        try:
            from monitor_app.events import get_event_bus
            bus = get_event_bus()
            for event, handler in getattr(self, "_bus_handlers", {}).items():
                bus.unsubscribe(event, handler)
            self._bus_handlers = {}
        except Exception:
            pass
        if hasattr(self, "review_tab") and self.review_tab:
            self.review_tab.stop_monitoring()

    def destroy(self):
        self.stop_monitoring()
        super().destroy()'''

    if target_stop in inc:
        inc = inc.replace(target_stop, replacement_stop, 1)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(inc)
    print("Patched incidents.py successfully.")

def patch_main():
    path = 'monitor_app/main.py'
    with open(path, 'r', encoding='utf-8') as f:
        main = f.read()

    # 1. In __init__, subscribe to INCIDENT_START
    target_init = '''        # Load last used screen from state
        last_screen = self.state_manager.get_setting("last_screen", "Dashboard")
        self.switch_screen(last_screen)'''

    replacement_init = '''        # Real-time incident alert indicator
        from monitor_app.events import get_event_bus
        get_event_bus().subscribe("INCIDENT_START", self._on_incident_alert_nav)

        # Load last used screen from state
        last_screen = self.state_manager.get_setting("last_screen", "Dashboard")
        self.switch_screen(last_screen)'''

    if target_init in main:
        main = main.replace(target_init, replacement_init, 1)

    # 2. In switch_screen, reset badge and define _on_incident_alert_nav
    target_switch = '''    def switch_screen(self, screen_name, initial_incident_id=None):
        # Clear current screen'''

    replacement_switch = '''    def _on_incident_alert_nav(self, *args, **kwargs):
        def _notify():
            if getattr(self, "current_screen", None) != "Incidents" and "Incidents" in self.nav_buttons:
                self.nav_buttons["Incidents"].configure(text="Incidents 🚨")
        self.after(0, _notify)

    def switch_screen(self, screen_name, initial_incident_id=None):
        if screen_name == "Incidents":
            if "Incidents" in getattr(self, "nav_buttons", {}):
                self.nav_buttons["Incidents"].configure(text="Incidents")
        # Clear current screen'''

    if target_switch in main:
        main = main.replace(target_switch, replacement_switch, 1)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(main)
    print("Patched main.py successfully.")

if __name__ == "__main__":
    patch_camera_view()
    patch_incidents()
    patch_main()

