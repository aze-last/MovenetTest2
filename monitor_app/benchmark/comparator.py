import os
import json
from typing import Dict, Optional, Tuple

class BenchmarkComparator:
    """
    Compares two benchmark runs side-by-side, aligning metrics, calculating delta
    percentages, and evaluating compliance with pipeline version locks.
    """
    @staticmethod
    def compare_runs(manifest_a: dict, timeline_a: list, manifest_b: dict, timeline_b: list) -> Tuple[dict, Optional[str], Optional[str]]:
        """
        Compares Manifest A (Baseline) and Manifest B (Current).
        Returns:
            - comparison_matrix: dict of metrics with baseline, current, and delta % values
            - winner: string indicating which run performed better
            - warning: warning message if version mismatch or other compatibility issues
        """
        warning = None
        
        # 1. Version Compatibility Check
        ver_a = manifest_a.get("versions", {}).get("pipeline_version", "1.0")
        ver_b = manifest_b.get("versions", {}).get("pipeline_version", "1.0")
        
        # Split major versions
        major_a = ver_a.split(".")[0]
        major_b = ver_b.split(".")[0]
        if major_a != major_b:
            warning = f"Version Mismatch Warning: Comparing Pipeline {ver_b} against Baseline {ver_a}. Results may be inconsistent."

        # 2. Extract metrics to compare
        metrics_a = BenchmarkComparator._calculate_timeline_averages(timeline_a, manifest_a)
        metrics_b = BenchmarkComparator._calculate_timeline_averages(timeline_b, manifest_b)
        
        comparison_matrix = {}
        for key, name_unit in BenchmarkComparator._get_comparison_keys().items():
            name, unit = name_unit
            val_a = metrics_a.get(key, 0.0)
            val_b = metrics_b.get(key, 0.0)
            
            # Calculate delta % (B relative to A)
            if val_a > 0.0:
                delta = ((val_b - val_a) / val_a) * 100.0
            else:
                delta = 0.0
                
            comparison_matrix[name] = {
                "unit": unit,
                "baseline": round(val_a, 2),
                "current": round(val_b, 2),
                "delta": round(delta, 1)
            }

        # 3. Determine Winner
        score_a = manifest_a.get("score", manifest_a.get("performance_score", 0.0))
        score_b = manifest_b.get("score", manifest_b.get("performance_score", 0.0))
        
        if score_b > score_a:
            winner = f"Current Run ({manifest_b['run_id']}) is faster by {round(score_b - score_a, 1)} pts"
        elif score_a > score_b:
            winner = f"Baseline Run ({manifest_a['run_id']}) is faster by {round(score_a - score_b, 1)} pts"
        else:
            winner = "Performance is identical."

        return comparison_matrix, winner, warning

    @staticmethod
    def _get_comparison_keys() -> dict:
        return {
            "avg_cpu": ("Average CPU Usage", "%"),
            "max_cpu": ("Peak CPU Usage", "%"),
            "avg_ram": ("Average RAM Allocation", "GB"),
            "avg_vram": ("Average VRAM Allocation", "MB"),
            "gpu_temp": ("Peak GPU Temperature", "°C"),
            "avg_fps": ("Average Frame Rate", "FPS"),
            "latency": ("Total Pipeline Latency P95", "ms"),
            "dropped_frames": ("Total Dropped Frames", "frames")
        }

    @staticmethod
    def _calculate_timeline_averages(timeline: list, manifest: dict) -> dict:
        if not timeline:
            return {}
        
        cpus = [(t.get("cpu_percent") or 0.0) for t in timeline]
        rams = [(t.get("ram_used_gb") or 0.0) for t in timeline]
        vrams = [(t.get("vram_allocated_mb") or 0.0) for t in timeline]
        gpu_temps = [(t.get("gpu_temp") or 0.0) for t in timeline]
        
        # Read latencies and FPS from timeline if available, fallback to manifest
        avg_latencies = [(t.get("avg_latency_ms") or 0.0) for t in timeline if (t.get("avg_latency_ms") or 0.0) > 0.0]
        p95_lat = sorted(avg_latencies)[int(len(avg_latencies) * 0.95)] if avg_latencies else manifest.get("p95_latency", 90.0)

        # Average FPS
        avg_fps = manifest.get("avg_fps", 15.0)
        
        return {
            "avg_cpu": sum(cpus) / len(cpus) if cpus else 0.0,
            "max_cpu": max(cpus) if cpus else 0.0,
            "avg_ram": sum(rams) / len(rams) if rams else 0.0,
            "avg_vram": sum(vrams) / len(vrams) if vrams else 0.0,
            "gpu_temp": max(gpu_temps) if gpu_temps else 0.0,
            "avg_fps": avg_fps,
            "latency": p95_lat,
            "dropped_frames": manifest.get("dropped_frames", 0)
        }
