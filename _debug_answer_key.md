# Debug Answer Key

## Round 6 (Multi-File Injections)
- **File 1 Changed**: `monitor_app/events.py`
  - **Category**: Silent Exception Swallowing
  - **Exact Change**:
    - Before: Log exception when callback fails
    - After: `except Exception: pass` (swallow silent failure)
- **File 2 Changed**: `monitor_app/hand_observation.py`
  - **Category**: Hardcoded Threshold Shift
  - **Exact Change**:
    - Before: `wrist_missing_threshold` default `0.20`
    - After: `wrist_missing_threshold` default `0.50`
