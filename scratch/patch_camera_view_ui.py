import os

# 1. Patch camera_view.py
with open("monitor_app/camera_view.py", "r", encoding="utf-8") as f:
    code = f.read()

# In __init__ add tracking variables
init_target = """        self.active_alert_incident_id = None
        self._alert_banner_visible = False"""

init_replacement = """        self.active_alert_incident_id = None
        self.active_alert_camera_id = None
        self.active_alert_contraband_ids = []
        self._alert_banner_visible = False"""

if init_target in code:
    code = code.replace(init_target, init_replacement)
elif init_target.replace("\n", "\r\n") in code:
    code = code.replace(init_target.replace("\n", "\r\n"), init_replacement.replace("\n", "\r\n"))

# Update _on_incident_alert
old_on_incident = """    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for confirmed incidents\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                self.after_idle(lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity: self._show_alert_banner(c, i, e, f, severity=s))
        except Exception:
            pass"""

new_on_incident = """    def _on_incident_alert(self, camera_id, incident_id, event_type, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for confirmed incidents\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                c_ids = []
                if ai_results and isinstance(ai_results, dict):
                    for det in ai_results.get("detections", {}).get("contraband", []):
                        tid = det.get("track_id")
                        if tid is not None and tid != -1:
                            c_ids.append(tid)
                self.after_idle(lambda c=camera_id, i=incident_id, e=event_type, f=frame, s=severity, ci=c_ids: self._show_alert_banner(c, i, e, f, severity=s, contraband_ids=ci))
        except Exception:
            pass"""

if old_on_incident in code:
    code = code.replace(old_on_incident, new_on_incident)
elif old_on_incident.replace("\n", "\r\n") in code:
    code = code.replace(old_on_incident.replace("\n", "\r\n"), new_on_incident.replace("\n", "\r\n"))

# Update _on_decision_alert
old_on_decision = """    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for fast preliminary decision triggers\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                self.after_idle(lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity: self._show_alert_banner(c, i, e, f, sc, severity=s))
        except Exception:
            pass"""

new_on_decision = """    def _on_decision_alert(self, camera_id, event_type, confidence_scores=None, frame=None, ai_results=None, severity=None, **kwargs):
        \"\"\"EventBus callback for fast preliminary decision triggers\"\"\"
        try:
            if self.winfo_exists() and getattr(self, "_is_monitoring", False):
                c_ids = []
                if ai_results and isinstance(ai_results, dict):
                    for det in ai_results.get("detections", {}).get("contraband", []):
                        tid = det.get("track_id")
                        if tid is not None and tid != -1:
                            c_ids.append(tid)
                self.after_idle(lambda c=camera_id, i=getattr(self, "active_alert_incident_id", None), e=event_type, f=frame, sc=confidence_scores, s=severity, ci=c_ids: self._show_alert_banner(c, i, e, f, sc, severity=s, contraband_ids=ci))
        except Exception:
            pass"""

if old_on_decision in code:
    code = code.replace(old_on_decision, new_on_decision)
elif old_on_decision.replace("\n", "\r\n") in code:
    code = code.replace(old_on_decision.replace("\n", "\r\n"), new_on_decision.replace("\n", "\r\n"))

# Update _show_alert_banner
old_show_banner = """    def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None):
        if incident_id:
            self.active_alert_incident_id = incident_id"""

new_show_banner = """    def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None, contraband_ids=None):
        if incident_id:
            self.active_alert_incident_id = incident_id
        self.active_alert_camera_id = str(camera_id)
        if contraband_ids:
            self.active_alert_contraband_ids = list(contraband_ids)
        elif not hasattr(self, "active_alert_contraband_ids"):
            self.active_alert_contraband_ids = []

        # Start continuous beating audio alert loop until dismissed
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().start_beating_loop(incident_id or f"ALERT_{camera_id}")
        except Exception:
            pass"""

if old_show_banner in code:
    code = code.replace(old_show_banner, new_show_banner)
elif old_show_banner.replace("\n", "\r\n") in code:
    code = code.replace(old_show_banner.replace("\n", "\r\n"), new_show_banner.replace("\n", "\r\n"))

# Update _dismiss_alert_banner
old_dismiss_banner = """    def _dismiss_alert_banner(self):
        if self._alert_banner_visible:
            self.alert_banner_frame.pack_forget()
            self._alert_banner_visible = False
        if self._alert_auto_dismiss_job:
            self.after_cancel(self._alert_auto_dismiss_job)
            self._alert_auto_dismiss_job = None"""

new_dismiss_banner = """    def _dismiss_alert_banner(self):
        # 1. Stop beating sound immediately upon dismissal
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass

        # 2. Register dismissal for the active contraband track IDs on this camera
        try:
            from monitor_app.decision import get_dismissal_registry
            reg = get_dismissal_registry()
            cam_id = getattr(self, "active_alert_camera_id", None)
            if cam_id:
                for tid in getattr(self, "active_alert_contraband_ids", []):
                    reg.dismiss_track(cam_id, tid)
        except Exception:
            pass

        if self._alert_banner_visible:
            self.alert_banner_frame.pack_forget()
            self._alert_banner_visible = False
        if self._alert_auto_dismiss_job:
            self.after_cancel(self._alert_auto_dismiss_job)
            self._alert_auto_dismiss_job = None"""

if old_dismiss_banner in code:
    code = code.replace(old_dismiss_banner, new_dismiss_banner)
elif old_dismiss_banner.replace("\n", "\r\n") in code:
    code = code.replace(old_dismiss_banner.replace("\n", "\r\n"), new_dismiss_banner.replace("\n", "\r\n"))

# Update stop_monitoring to also stop beating loop
old_stop_mon = """    def stop_monitoring(self):
        self._is_monitoring = False"""

new_stop_mon = """    def stop_monitoring(self):
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass
        self._is_monitoring = False"""

if old_stop_mon in code:
    code = code.replace(old_stop_mon, new_stop_mon)
elif old_stop_mon.replace("\n", "\r\n") in code:
    code = code.replace(old_stop_mon.replace("\n", "\r\n"), new_stop_mon.replace("\n", "\r\n"))

# Update _review_active_incident to stop beating loop
old_review = """    def _review_active_incident(self):
        \"\"\"Jump to Incidents screen with the current active alert incident loaded.\"\"\""""

new_review = """    def _review_active_incident(self):
        \"\"\"Jump to Incidents screen with the current active alert incident loaded.\"\"\"
        try:
            from monitor_app.alert_manager import get_sound_alert_manager
            get_sound_alert_manager().stop_beating_loop()
        except Exception:
            pass"""

if old_review in code:
    code = code.replace(old_review, new_review)
elif old_review.replace("\n", "\r\n") in code:
    code = code.replace(old_review.replace("\n", "\r\n"), new_review.replace("\n", "\r\n"))

with open("monitor_app/camera_view.py", "w", encoding="utf-8") as f:
    f.write(code)
print("camera_view.py updated successfully!")

