import pytest
from unittest.mock import MagicMock, patch
from monitor_app.alert_manager import get_sound_alert_manager
from monitor_app.decision import get_dismissal_registry

def test_dismiss_stops_sound_and_registers_track():
    """Verify dismissal flow: shows banner -> starts sound -> dismiss clicks -> stops sound & registers track."""
    sound_mgr = get_sound_alert_manager()
    reg = get_dismissal_registry()
    reg.clear_all()
    sound_mgr.stop_beating_loop()

    # Mock winsound.Beep
    with patch("monitor_app.alert_manager.winsound"):
        # Simulate CameraMonitorScreen mock
        class MockScreen:
            def __init__(self):
                self.active_alert_camera_id = None
                self.active_alert_contraband_ids = []
                self._alert_banner_visible = False
                self._alert_auto_dismiss_job = None
                self.alert_banner_frame = MagicMock()

            def _show_alert_banner(self, camera_id, incident_id, event_type, frame=None, scores=None, severity=None, contraband_ids=None):
                self.active_alert_camera_id = str(camera_id)
                self.active_alert_contraband_ids = list(contraband_ids or [])
                self._alert_banner_visible = True
                sound_mgr.start_beating_loop(incident_id or f"ALERT_{camera_id}")

            def _dismiss_alert_banner(self):
                sound_mgr.stop_beating_loop()
                cam_id = getattr(self, "active_alert_camera_id", None)
                if cam_id:
                    for tid in getattr(self, "active_alert_contraband_ids", []):
                        reg.dismiss_track(cam_id, tid)
                self._alert_banner_visible = False

        screen = MockScreen()
        
        # Trigger alert for light glare / phone ID 505 on Camera 1
        screen._show_alert_banner(
            camera_id="1",
            incident_id="INC_TEST_001",
            event_type="Cellphone (85% >= 30%)",
            contraband_ids=[505]
        )
        
        assert screen.active_alert_camera_id == "1"
        assert 505 in screen.active_alert_contraband_ids
        assert sound_mgr.is_beating()
        assert not reg.is_track_dismissed("1", 505)
        
        # Operator clicks Dismiss
        screen._dismiss_alert_banner()
        
        # Sound must stop and track 505 must be registered as dismissed
        assert not sound_mgr.is_beating()
        assert reg.is_track_dismissed("1", 505)
        
        # New phone ID 777 on Camera 1 should NOT be dismissed
        assert not reg.is_track_dismissed("1", 777)

