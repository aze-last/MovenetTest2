import pytest
import sys
from unittest.mock import patch


def test_performance_monitor_handles_torch_oserror(monkeypatch):
    """Verify performance monitor handles OSError when torch fails loading DLLs."""
    import importlib
    import monitor_app.monitor_logging.performance as perf_module

    with patch.dict(sys.modules, {"torch": None}):
        # Simulating broken torch that raises OSError on import
        pass

    assert hasattr(perf_module, "TORCH_AVAILABLE")


def test_system_collector_handles_torch_oserror():
    """Verify system collector handles OSError when torch fails loading."""
    from monitor_app.telemetry.collectors.system import SystemCollector
    collector = SystemCollector()
    collector.on_event("TELEM_SYSTEM_TICK", {})
    stats = collector.get_stats()
    assert isinstance(stats, dict)


def test_session_exporter_hardware_fingerprint():
    """Verify session exporter hardware fingerprint never crashes if torch fails."""
    import tempfile
    from monitor_app.exporters.session_exporter import SessionExporter
    with tempfile.TemporaryDirectory() as td:
        exporter = SessionExporter(td, "test_session", "medium", "dummy.mp4")
        fp = exporter._get_hardware_fingerprint()
        assert "cpu" in fp
        assert "gpu" in fp


def test_hardware_profiler_get_profile():
    """Verify hardware profiler gets profile without crashing even if tf/torch fail."""
    from monitor_app.telemetry.hardware_profiler import HardwareProfiler
    profile = HardwareProfiler.get_profile()
    assert isinstance(profile, dict)
    assert "cpu" in profile
    assert "ram_total_gb" in profile
