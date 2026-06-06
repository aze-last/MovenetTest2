import os
import tensorflow_hub as hub

MODEL_HANDLE = "https://tfhub.dev/google/movenet/multipose/lightning/1"
DEFAULT_CACHE_DIR = os.path.join("monitor_app", "models", "movenet_multipose")

os.environ.setdefault("TFHUB_CACHE_DIR", DEFAULT_CACHE_DIR)

local_path = os.environ.get("MOVENET_LOCAL_PATH")

if local_path:
    hub.load(local_path)
    print(f"MoveNet loaded from local path: {local_path}")
else:
    hub.load(MODEL_HANDLE)
    print(f"MoveNet downloaded and cached in: {os.environ['TFHUB_CACHE_DIR']}")
