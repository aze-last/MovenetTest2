# YOLO Engine Fallback Changes

## 1. `config.yaml`
Updated the `yolo` configuration block:
- Set `model_path` to `best.engine` (preferred TensorRT engine).
- Added `model_path_fallback: best.pt` (fallback PyTorch model).
- Changed `inference_imgsz` to `960` to perfectly match the TensorRT export dimensions.

## 2. `monitor_app/ai_engine.py`
Completely replaced the hardcoded `best.pt` loading block with a robust fallback mechanism:
- Loops through both `best.engine` and `best.pt`.
- If `.engine` is missing or fails to initialize (e.g. driver mismatch), it automatically tries `.pt`.
- Added `self.active_model_name` to expose the successfully loaded model for UI and logging.
- Promoted silent failures to a CRITICAL console warning if both models fail to load, clearly indicating contraband detection is disabled.
