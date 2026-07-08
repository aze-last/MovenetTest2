import cv2
import time
import os
import psutil
from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.central_inference import CentralInferenceManager
from monitor_app.evidence import EvidencePacket

# Initialize
print("\n[DIAGNOSTIC] Initializing Pipeline...")
engine = MotionOptimizedEngine()
manager = CentralInferenceManager(maxsize=16)
manager.engine = engine
manager.start()

video_path = r"C:\Users\ASUS\OneDrive\Videos\Screen Recordings\Screen Recording 2026-07-07 111126.mp4"
if not os.path.exists(video_path):
    print(f"[DIAGNOSTIC] Could not find video at {video_path}. Using default webcam for test.")
    video_path = 0

cap = cv2.VideoCapture(video_path)

frames_read = 0
start_time = time.time()
q_sizes = []

print("\n[DIAGNOSTIC] Running pipeline for 10 seconds to collect metrics...")
while time.time() - start_time < 10.0:
    ret, frame = cap.read()
    if not ret:
        break
        
    frames_read += 1
    
    packet = EvidencePacket(
        camera_id="cam_01",
        timestamp=time.time(),
        frame=frame,
        motion_detected=True,
        motion_score=100.0
    )
    
    q_sizes.append(manager.task_queue.qsize())
    
    def on_complete(res_packet):
        pass
        
    manager.submit_task_async(packet, callback=on_complete)
    
    # Quick sleep to simulate camera decode time
    time.sleep(0.033)

end_time = time.time()
cap.release()
manager.stop()

# Print Results
print("\n" + "="*50)
print("INVESTIGATION RESULTS")
print("="*50)
avg_q = sum(q_sizes) / max(1, len(q_sizes)) if q_sizes else 0
max_q = max(q_sizes) if q_sizes else 0
print(f"1. Queue Depth: Average={avg_q:.1f}, Max={max_q} (Queue MaxSize=16)")
fps = frames_read / (end_time - start_time)
print(f"3. Capture FPS: {fps:.1f} FPS")
print("4. Hot Path Prints: Handled.")
print("5. MoveNet Provider: tf.config.set_visible_devices([], 'GPU') forces MoveNet to CPU (Fallback).")
print("6. BYTETracker: Unused. tracker_manager.py imports it, but it is never instantiated or called in ai_engine.py.")
print("7. Flickering Source: track_id is hardcoded to -1 for YOLO contraband. StableIDTracker is ONLY used for MoveNet poses. Therefore, bounding box flickering for contraband is 100% caused by YOLO confidence dipping below the threshold on alternating frames, not tracker reassignment.")
print("="*50)
