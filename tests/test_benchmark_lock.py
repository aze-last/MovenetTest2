import sys
import os
import pytest

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_app.utils import GlobalState

def test_benchmark_lock_lifecycle():
    # Initial state
    assert GlobalState.benchmark_active is False
    assert GlobalState.get_frozen_config() is None

    # Apply lock
    dummy_config = {
        "camera_count": 4,
        "profile": "quick",
        "yolo_model": "yolov8n.pt",
        "movenet_model": "movenet_lightning",
        "target_fps": 15,
        "resolution": "640x480"
    }
    GlobalState.lock_benchmark(dummy_config)
    
    assert GlobalState.benchmark_active is True
    assert GlobalState.get_metrics()["benchmark_active"] is True
    
    frozen = GlobalState.get_frozen_config()
    assert frozen is not None
    assert frozen["camera_count"] == 4
    assert frozen["profile"] == "quick"

    # Release lock
    GlobalState.unlock_benchmark()
    assert GlobalState.benchmark_active is False
    assert GlobalState.get_frozen_config() is None
    assert GlobalState.get_metrics()["benchmark_active"] is False
