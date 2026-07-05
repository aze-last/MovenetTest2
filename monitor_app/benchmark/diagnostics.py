from typing import List, Dict

class PerformanceDiagnostics:
    """
    Expert rule-engine that audits benchmark metrics to pinpoint physical resource bottlenecks
    and estimate optimization gains.
    """
    @staticmethod
    def audit_run(manifest: dict, timeline: list, failures: dict, memory_slope_mb_min: float) -> List[dict]:
        recommendations = []

        # Extract averages/peaks from timeline
        cpu_usage = [(r.get("cpu_percent") or 0.0) for r in timeline]
        avg_cpu = sum(cpu_usage) / len(cpu_usage) if cpu_usage else 0.0
        
        gpu_temps = [(r.get("gpu_temp") or 0.0) for r in timeline]
        max_gpu_temp = max(gpu_temps) if gpu_temps else 0.0
        
        avg_latency = manifest.get("p95_latency", 90.0)
        camera_count = manifest.get("settings", {}).get("camera_count", 4)

        # Rule 1: CPU Saturation
        if avg_cpu > 85.0:
            recommendations.append({
                "issue": f"CPU execution Saturated (Average: {round(avg_cpu, 1)}%).",
                "recommendation": "Offload MoveNet parsing keypoints to GPU or lower the camera stream processing frequency."
            })

        # Rule 2: GPU Temperature Throttling
        if max_gpu_temp > 80.0:
            recommendations.append({
                "issue": f"High GPU thermals detected (Peak: {round(max_gpu_temp, 1)}°C).",
                "recommendation": "Hardware thermal throttling risk. Enable active system fan profiling or reduce target model parameters."
            })

        # Rule 3: Heavy Model Latency Spikes
        if avg_latency > 130.0:
            recommendations.append({
                "issue": f"High pipeline P95 latency (Average: {round(avg_latency, 1)} ms).",
                "recommendation": "Model forward pass overhead is high. Suggested actions: Decrease YOLO resolution or use the MoveNet lightning model."
            })

        # Rule 4: Memory Leak Detection
        if memory_slope_mb_min > 2.0:
            recommendations.append({
                "issue": f"Significant RAM heap growth detected ({round(memory_slope_mb_min, 2)} MB/min).",
                "recommendation": "Probable resource reference leaks. Investigate video buffer queues and verify cv2 VideoCapture releases."
            })

        # Rule 5: Camera Dropouts
        reconnects = failures.get("camera_reconnects", 0)
        if reconnects > 0:
            recommendations.append({
                "issue": f"Camera network dropped {reconnects} times during test.",
                "recommendation": "Unstable camera connections. Inspect hardware cabling or switch to wired PoE network."
            })

        if not recommendations:
            recommendations.append({
                "issue": "System performance is fully optimized.",
                "recommendation": "No resource anomalies or structural pipeline bottlenecks detected."
            })

        return recommendations
