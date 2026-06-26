import cv2
import os
import time
import sqlite3
import json
import re
import threading
from collections import deque
from datetime import datetime
import monitor_app.utils as utils

class IncidentRecorder:
    """
    Handles state machine, pre-roll buffering, and video recording for incidents.
    States: IDLE -> RECORDING -> COOLDOWN -> IDLE
    """
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    COOLDOWN = "COOLDOWN"

    def __init__(self, camera_id, recordings_dir="recordings", db_path="incidents.db", on_incident_callback=None):
        self.camera_id = str(camera_id).zfill(2)
        self.recordings_dir = recordings_dir
        self.db_path = db_path
        self.on_incident_callback = on_incident_callback
        self.state = self.IDLE
        
        # FPS & Timing
        self.target_fps = 15.0
        self.frame_interval = 1.0 / self.target_fps
        self.last_write_time = 0
        
        # Buffer: maxlen 75 = 5 seconds at 15 FPS
        self.pre_roll_buffer = deque(maxlen=75) 
        self.video_writer = None
        
        # Recording Window
        self.recording_start_time = 0
        self.cooldown_end_time = 0
        self.record_duration = 10  # Seconds AFTER trigger
        self.cooldown_duration = 25  # Seconds after recording ends
        
        # Metadata
        self.current_event_id = ""
        self.current_event_type = ""
        self.current_video_path = ""
        self.current_timestamp_start = ""
        self.confidence_scores = []

        self._init_db()
        self._ensure_dir()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS incidents (
                    event_id TEXT PRIMARY KEY,
                    camera_id TEXT,
                    timestamp_start TEXT,
                    timestamp_end TEXT,
                    event_type TEXT,
                    confidence_scores TEXT,
                    video_path TEXT,
                    comments TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    retention_days INTEGER,
                    review_status TEXT DEFAULT 'PENDING'
                )
            ''')

            self._ensure_columns(cursor)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database Init Error: {e}")

    def _ensure_columns(self, cursor):
        cursor.execute("PRAGMA table_info(incidents)")
        existing = {row[1] for row in cursor.fetchall()}
        columns = [
            ("timestamp_end", "TEXT", None),
            ("event_type", "TEXT", None),
            ("confidence_scores", "TEXT", None),
            ("video_path", "TEXT", None),
            ("comments", "TEXT", None),
            ("reviewed_by", "TEXT", None),
            ("reviewed_at", "TEXT", None),
            ("retention_days", "INTEGER", None),
            ("review_status", "TEXT", "'PENDING'"),
        ]
        for name, col_type, default in columns:
            if name in existing:
                continue
            default_clause = f" DEFAULT {default}" if default is not None else ""
            cursor.execute(f"ALTER TABLE incidents ADD COLUMN {name} {col_type}{default_clause}")

    def _ensure_dir(self):
        if not os.path.exists(self.recordings_dir):
            os.makedirs(self.recordings_dir)

    def process_frame(self, bgr_frame, ai_results):
        """
        Called every frame. bgr_frame MUST be in BGR format for OpenCV writer.
        """
        current_time = time.perf_counter()
        
        # 1. TIME-BASED SAMPLING: Ensure we only write/buffer at exactly 15 FPS
        if current_time - self.last_write_time < self.frame_interval:
            return
        self.last_write_time = current_time

        # 2. ALWAYS BUFFER (Pre-roll persistence across all states)
        # We store a copy to avoid external modifications
        self.pre_roll_buffer.append(bgr_frame.copy())

        # 3. STATE MACHINE (Recording mode only)
        if self.state == self.RECORDING:
            if self.video_writer:
                self.video_writer.write(bgr_frame)
            
            # Autonomously stop after duration ONLY if not manually stopped
            if time.time() - self.recording_start_time >= self.record_duration:
                self.stop_recording()
                
        elif self.state == self.COOLDOWN:
            if time.time() >= self.cooldown_end_time:
                self.state = self.IDLE
                print(f"Cam {self.camera_id}: Status -> IDLE")

    def trigger_recording(self, event_type, confidence_scores, current_frame, ai_results=None):
        """Exposed method to start recording, called by AlertManager."""
        if self.state == self.IDLE:
            self._start_recording(current_frame, event_type, confidence_scores)

    def stop_recording(self):
        """Exposed method to stop recording, called by AlertManager."""
        if self.state == self.RECORDING:
            self._stop_recording()

    def _start_recording(self, current_frame, event_type, confidence_scores):
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")
        
        self.current_event_type = event_type
        
        # Sanitize and Format Filename
        safe_type = re.sub(r'[^\w\-_\. ]', '_', self.current_event_type).lower().replace(" ", "_")
        if not safe_type: safe_type = "alert"
        
        dir_path = os.path.join(self.recordings_dir, f"cam_{self.camera_id}", date_str)
        if not os.path.exists(dir_path): os.makedirs(dir_path)
            
        filename = f"event_{date_str}_{time_str}_cam{self.camera_id}_{safe_type}.mp4"
        self.current_video_path = os.path.join(dir_path, filename)
        
        # Initialize Video Writer (Dynamic Size)
        h, w = current_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(self.current_video_path, fourcc, self.target_fps, (w, h))
        
        if not self.video_writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*'avc1')
            self.video_writer = cv2.VideoWriter(self.current_video_path, fourcc, self.target_fps, (w, h))

        # Write Pre-roll (SNAPSHOT - do not drain buffer)
        print(f"Cam {self.camera_id}: Triggered! Evidence: {self.current_event_type}")
        snapshot = list(self.pre_roll_buffer)
        for buf_frame in snapshot:
            self.video_writer.write(buf_frame)
            
        # Metadata Save
        self.current_event_id = f"EVT_{date_str.replace('-','')}_{time_str.replace('-','')}_{self.camera_id}"
        self.current_timestamp_start = now.isoformat()
        self.confidence_scores = confidence_scores
        
        self.state = self.RECORDING
        self.recording_start_time = time.time()

    def _stop_recording(self):
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            
        end_time = datetime.now().isoformat()
        self._save_metadata(end_time)
        
        self.state = self.COOLDOWN
        self.cooldown_end_time = time.time() + self.cooldown_duration
        print(f"Cam {self.camera_id}: Entering COOLDOWN.")

    def _save_metadata(self, end_time):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO incidents (
                    event_id, camera_id, timestamp_start, timestamp_end, 
                    event_type, confidence_scores, video_path, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.current_event_id,
                self.camera_id,
                self.current_timestamp_start,
                end_time,
                self.current_event_type,
                json.dumps(self.confidence_scores),
                self.current_video_path,
                'PENDING'
            ))
            conn.commit()
            conn.close()
            
            if self.on_incident_callback:
                self.on_incident_callback(self.current_event_id, self.current_event_type, self.current_video_path)
        except Exception as e:
            print(f"Metadata Save Error: {e}")

    def get_status_info(self):
        if self.state == self.RECORDING:
            return f"RECORDING: {self.current_event_type}", utils.COLOR_ALERT
        elif self.state == self.COOLDOWN:
            remaining = int(self.cooldown_end_time - time.time())
            return f"COOLDOWN ({max(0, remaining)}s)", "#FFA500"
        return "NORMAL", utils.COLOR_SUCCESS
