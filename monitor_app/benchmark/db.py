import os
import sqlite3
from typing import Dict, List, Optional

class BenchmarkDBManager:
    """
    Manages benchmark database operations for reproducible runs and golden baseline tracking.
    Stored at monitor_app/benchmark.db.
    """
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to benchmark.db in data_path (parallel to executable)
            from monitor_app.utils import data_path
            self.db_path = data_path("benchmark.db")
        else:
            self.db_path = db_path
        
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize database tables for runs and metrics timelines."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._get_connection() as conn:
            # Table 1: Benchmark Runs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    git_commit TEXT,
                    config_yaml_hash TEXT,
                    telemetry_schema_version TEXT,
                    pipeline_version TEXT,
                    behavior_module_version TEXT,
                    config_version TEXT,
                    os TEXT,
                    python_version TEXT,
                    cuda_version TEXT,
                    torch_version TEXT,
                    tensorflow_version TEXT,
                    host_name TEXT,
                    cpu_model TEXT,
                    gpu_model TEXT,
                    ram_total_gb REAL,
                    operator_profile TEXT,
                    camera_count INTEGER,
                    camera_resolution TEXT,
                    target_fps INTEGER,
                    yolo_model TEXT,
                    movenet_model TEXT,
                    performance_score REAL,
                    is_golden_baseline INTEGER DEFAULT 0,
                    hardware_hash TEXT,
                    display_label TEXT,
                    p95_latency_ms REAL
                )
            """)
            
            # Migration check for hardware_hash, display_label, p95_latency_ms
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row[1] for row in cursor.fetchall()]
            if "hardware_hash" not in columns:
                conn.execute("ALTER TABLE runs ADD COLUMN hardware_hash TEXT")
            if "display_label" not in columns:
                conn.execute("ALTER TABLE runs ADD COLUMN display_label TEXT")
            if "p95_latency_ms" not in columns:
                conn.execute("ALTER TABLE runs ADD COLUMN p95_latency_ms REAL")
            
            # Table 2: High-Resolution Timeline Logs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    timestamp REAL,
                    cpu_percent REAL,
                    ram_used_gb REAL,
                    vram_allocated_mb REAL,
                    gpu_temp REAL,
                    gpu_clock_mhz REAL,
                    cpu_clock_mhz REAL,
                    queue_size INTEGER,
                    avg_latency_ms REAL,
                    FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def _get_short_cpu(self, cpu_str: str) -> str:
        if not cpu_str: return "Unknown CPU"
        import re
        match = re.search(r'(Core\s*(?:i\d|Ultra\s*\d|\w+))', cpu_str, re.IGNORECASE)
        if match: return match.group(1).strip()
        match = re.search(r'(Ryzen\s*\d+)', cpu_str, re.IGNORECASE)
        if match: return match.group(1).strip()
        parts = cpu_str.split()
        return " ".join(parts[:2]) if len(parts) >= 2 else cpu_str[:15]

    def save_run(self, manifest: dict, timeline: List[dict], performance_score: float) -> str:
        """Saves run manifest and time-series logs to the database."""
        run_id = manifest.get("run_id")
        p95_latency = manifest.get("p95_latency")  # Expected to be passed in manifest
        cpu_str = manifest.get("hardware", {}).get("cpu", "")
        short_cpu_name = self._get_short_cpu(cpu_str)

        with self._get_connection() as conn:
            # Calculate display_label counter
            count_query = conn.execute("SELECT COUNT(*) FROM runs WHERE display_label LIKE ?", (f"{short_cpu_name} - Run %",)).fetchone()[0]
            display_label = f"{short_cpu_name} - Run {count_query + 1}"

            # Insert Run metadata
            conn.execute("""
                INSERT OR REPLACE INTO runs (
                    run_id, timestamp, git_commit, config_yaml_hash,
                    telemetry_schema_version, pipeline_version, behavior_module_version, config_version,
                    os, python_version, cuda_version, torch_version, tensorflow_version,
                    host_name, cpu_model, gpu_model, ram_total_gb,
                    operator_profile, camera_count, camera_resolution, target_fps,
                    yolo_model, movenet_model, performance_score, hardware_hash,
                    display_label, p95_latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                manifest.get("timestamp"),
                manifest.get("git_commit"),
                manifest.get("config_yaml_hash"),
                manifest.get("versions", {}).get("telemetry_schema_version"),
                manifest.get("versions", {}).get("pipeline_version"),
                manifest.get("versions", {}).get("behavior_module_version"),
                manifest.get("versions", {}).get("config_version"),
                manifest.get("environment", {}).get("os"),
                manifest.get("environment", {}).get("python"),
                manifest.get("environment", {}).get("cuda"),
                manifest.get("environment", {}).get("torch"),
                manifest.get("environment", {}).get("tensorflow"),
                manifest.get("hardware", {}).get("host_name"),
                manifest.get("hardware", {}).get("cpu"),
                manifest.get("hardware", {}).get("gpu"),
                manifest.get("hardware", {}).get("ram_total_gb"),
                manifest.get("settings", {}).get("operator_profile"),
                manifest.get("settings", {}).get("camera_count"),
                manifest.get("settings", {}).get("camera_resolution"),
                manifest.get("settings", {}).get("target_fps"),
                manifest.get("settings", {}).get("yolo_model"),
                manifest.get("settings", {}).get("movenet_model"),
                performance_score,
                manifest.get("hardware_hash"),
                display_label,
                p95_latency
            ))
            
            # Insert Timeline series
            for t_point in timeline:
                conn.execute("""
                    INSERT INTO metrics_timeline (
                        run_id, timestamp, cpu_percent, ram_used_gb, vram_allocated_mb,
                        gpu_temp, gpu_clock_mhz, cpu_clock_mhz, queue_size, avg_latency_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    t_point.get("timestamp"),
                    t_point.get("cpu_percent"),
                    t_point.get("ram_used_gb"),
                    t_point.get("vram_allocated_mb"),
                    t_point.get("gpu_temp"),
                    t_point.get("gpu_clock_mhz"),
                    t_point.get("cpu_clock_mhz"),
                    t_point.get("queue_size"),
                    t_point.get("avg_latency_ms")
                ))
            conn.commit()
        return run_id

    def set_golden_baseline(self, run_id: str):
        """Locks a specific run_id as the Golden Baseline, resetting previous."""
        with self._get_connection() as conn:
            conn.execute("UPDATE runs SET is_golden_baseline = 0")
            conn.execute("UPDATE runs SET is_golden_baseline = 1 WHERE run_id = ?", (run_id,))
            conn.commit()

    def get_golden_baseline(self) -> Optional[dict]:
        """Fetch the current Golden Baseline run details."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE is_golden_baseline = 1").fetchone()
            return dict(row) if row else None

    def get_last_run(self) -> Optional[dict]:
        """Fetch the most recent run details."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM runs ORDER BY timestamp DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def get_run_history(self) -> List[dict]:
        """Get list of historical runs."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY timestamp DESC").fetchall()
            return [dict(r) for r in rows]

    def get_timeline(self, run_id: str) -> List[dict]:
        """Get time-series snapshots for a run."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM metrics_timeline WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)).fetchall()
            return [dict(r) for r in rows]
