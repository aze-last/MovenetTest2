import time
import pytest
from unittest.mock import patch, MagicMock
from monitor_app.alert_manager import SoundAlertManager

def test_sound_alert_manager_beating_loop_lifecycle():
    """Verify start_beating_loop starts thread, sets is_beating, and stop_beating_loop halts it."""
    mgr = SoundAlertManager()
    mgr.enabled = True

    # Mock winsound.Beep so test runs silently and quickly without hardware audio
    with patch("monitor_app.alert_manager.winsound") as mock_ws:
        mock_ws.Beep = MagicMock()
        
        assert not mgr.is_beating()
        
        # Start beating loop
        mgr.start_beating_loop("TEST_ALERT_1")
        assert mgr.is_beating()
        
        # Give thread a brief slice to run at least one beep iteration
        time.sleep(0.1)
        assert mock_ws.Beep.called
        
        # Calling start again while active should be a no-op
        mgr.start_beating_loop("TEST_ALERT_2")
        assert mgr.is_beating()
        
        # Stop beating loop
        mgr.stop_beating_loop()
        assert not mgr.is_beating()
        
        # Ensure thread has terminated
        time.sleep(0.1)
        assert mgr._beating_thread is None or not mgr._beating_thread.is_alive()

def test_sound_alert_manager_disabled_does_not_beat():
    """Verify beating loop does not run when audio alerts are disabled."""
    mgr = SoundAlertManager()
    mgr.enabled = False
    
    mgr.start_beating_loop("TEST_ALERT_DISABLED")
    assert not mgr.is_beating()

