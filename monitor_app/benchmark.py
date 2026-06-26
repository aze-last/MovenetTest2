import sys
import os
import time
import threading
import psutil
import numpy as np
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_app.evidence import EvidencePacket
from monitor_app.central_inference import get_inference_manager

def run_benchmark(duration_seconds=30):
    print("=== CELLWATCH AI PERFORMANCE BENCHMARK ===")
    print(f"Target duration: {duration_seconds} seconds")
    print(f"Simulating 4 camera feeds at 15 FPS each...")
    
    manager = get_inference_manager()
    manager.start()
    
    # Wait for engines to initialize in worker thread
    print("Waiting for central inference manager engine to initialize...")
    for _ in range(45):
        if manager.engine is not None:
            break
        time.sleep(1.0)
        
    if manager.engine is None:
        print("Warning: Engine failed to initialize in time.")
        
    # Additional brief warm up for CUDA initialization
    print("Warming up CUDA context (3 seconds)...")
    time.sleep(3.0)
    
    # Initialize metrics
    frame_counts = [0] * 4
    latencies = []
    inference_times = []
    
    running = True
    lock = threading.Lock()
    
    # Stats tracking per camera
    cam_start_times = [0.0] * 4
    cam_end_times = [0.0] * 4
    
    def cam_simulator(cam_idx):
        nonlocal running
        cam_start_times[cam_idx] = time.time()
        
        while running:
            # Simulate 15 FPS (sleep ~66ms)
            time.sleep(0.066)
            if not running:
                break
                
            packet = EvidencePacket(
                camera_id=str(cam_idx),
                timestamp=time.time(),
                frame=np.zeros((480, 640, 3), dtype=np.uint8),
                motion_detected=True,
                motion_score=12000.0
            )
            
            t_submit = time.perf_counter()
            res = manager.submit_task(packet)
            t_done = time.perf_counter()
            
            latency = (t_done - t_submit) * 1000.0 # ms
            
            with lock:
                frame_counts[cam_idx] += 1
                latencies.append(latency)
                # Capture processing mode or time if returned
                if res.processing_mode != "Inference Timeout":
                    # Estimate inference time (excluding queue wait time)
                    inference_times.append(latency) # placeholder for actual inference
                    
        cam_end_times[cam_idx] = time.time()

    # Launch threads
    threads = []
    for idx in range(4):
        t = threading.Thread(target=cam_simulator, args=(idx,))
        threads.append(t)
        t.start()
        
    # Gather CPU/RAM/VRAM utilization over time
    cpu_usages = []
    ram_usages = []
    vram_usages = []
    
    start_time = time.time()
    while time.time() - start_time < duration_seconds:
        cpu_usages.append(psutil.cpu_percent())
        ram_usages.append(psutil.virtual_memory().percent)
        
        if TORCH_AVAILABLE and torch.cuda.is_available():
            # Convert bytes to MB
            vram_mb = torch.cuda.memory_reserved(0) / (1024 * 1024)
            vram_usages.append(vram_mb)
        else:
            vram_usages.append(0.0)
            
        time.sleep(1.0)
        
    running = False
    
    for t in threads:
        t.join()
        
    manager.stop()
    
    # Calculate Results
    total_elapsed = time.time() - start_time
    total_frames = sum(frame_counts)
    overall_fps = total_frames / total_elapsed
    
    per_cam_fps = []
    for idx in range(4):
        cam_duration = cam_end_times[idx] - cam_start_times[idx]
        per_cam_fps.append(frame_counts[idx] / cam_duration if cam_duration > 0 else 0.0)
        
    avg_latency = np.mean(latencies) if latencies else 0.0
    p95_latency = np.percentile(latencies, 95) if latencies else 0.0
    avg_cpu = np.mean(cpu_usages) if cpu_usages else 0.0
    avg_ram = np.mean(ram_usages) if ram_usages else 0.0
    max_vram = np.max(vram_usages) if vram_usages else 0.0
    
    # Output markdown report
    report_content = f"""# CellWatch AI Benchmark Performance Report

## System Specifications
- **CPU**: Ryzen 7 7435HS
- **RAM**: 16GB
- **GPU**: RTX 2050 (4GB VRAM)

## Test Run Details
- **Test Duration**: {total_elapsed:.2f} seconds
- **Total Processed Frames**: {total_frames}

## Measured Performance
| Metric | Average | Peak / p95 |
| --- | --- | --- |
| **Overall FPS** | {overall_fps:.2f} | - |
| **Queue Latency (ms)** | {avg_latency:.2f} ms | {p95_latency:.2f} ms (p95) |
| **CPU Utilization (%)** | {avg_cpu:.2f}% | - |
| **RAM Utilization (%)** | {avg_ram:.2f}% | - |
| **GPU VRAM Reservation (MB)** | - | {max_vram:.2f} MB |

## Per-Camera Throughput
"""
    for idx in range(4):
        report_content += f"- **Camera {idx} FPS**: {per_cam_fps[idx]:.2f} FPS (Processed {frame_counts[idx]} frames)\n"
        
    print("\nBenchmark completed. Report content:")
    print(report_content)
    
    # Save report
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", "benchmark_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report_content)
    print(f"Report saved to {report_path}")

if __name__ == "__main__":
    duration = 30
    if len(sys.argv) > 1:
        duration = int(sys.argv[1])
    run_benchmark(duration)
