import os
import sys
import time
import cv2
import numpy as np

# Ensure root in sys.path
sys.path.insert(0, os.path.abspath("."))

from monitor_app.ai_engine import MotionOptimizedEngine
from monitor_app.evidence import TrackedPerson
from monitor_app.tracking.stable_id import StableIDTracker
from monitor_app.config import get_config

def audit_stable_id_creations(video_path, max_frames=1800):
    print(f"=== AUDITING STABLE ID CREATIONS ON {video_path} ===")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video FPS: {fps}, Total Frames: {total_frames}, Resolution: {cap.get(cv2.CAP_PROP_FRAME_WIDTH)}x{cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")

    engine = MotionOptimizedEngine()
    engine.enable_movenet = True
    engine.enable_yolo = False  # Isolate MoveNet & person tracking

    # Instrument StableIDTracker to log detailed diagnostics on new ID creation
    tracker = StableIDTracker(max_distance=120.0, grace_period=30)
    tracker._trace = True

    # Track historical anchor mode per stable_id: {sid: anchor_mode}
    track_anchor_history = {}
    track_last_seen = {}

    creations_log = []
    leap_grace_count = 0
    leap_new_id_count = 0

    frame_idx = 0
    start_time = time.time()

    while cap.isOpened() and frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        # Run MoveNet inference
        res = engine.run_movenet_only(frame, camera_id="audit_cam", frame_index=frame_idx, draw=False)
        
        # MoveNet extracts raw_detected: (person, i, hip_centroid, conf)
        # In engine._run_movenet_logic, anchor mode was determined:
        # Let's inspect raw keypoints from res["tracked_persons"] if any
        tracked_persons = res.get("tracked_persons", [])
        
        # We also monitor tracker state directly
        # Let's see what happens during tracker update
        # To get the exact reason code for new ID creation:
        # We inspect persons passed to tracker vs existing tracks before matching
        existing_tracks_before = {sid: dict(data) for sid, data in tracker._tracks.items()}

        # Check for frame leap > grace_period
        frame_delta = None if tracker._last_frame_number is None else (frame_idx - tracker._last_frame_number)
        is_leap = frame_delta is not None and frame_delta > tracker.grace_period
        if is_leap:
            leap_grace_count += 1

        # Perform update
        tracker.update(tracked_persons, frame_idx)

        # Detect which persons got newly assigned IDs
        for p in tracked_persons:
            sid = p.stable_id
            if sid not in existing_tracks_before:
                # Newly created ID!
                # Determine reason code:
                # 1. Was tracker empty?
                if not existing_tracks_before:
                    reason = "FIRST_DETECTIONS_OR_EMPTY"
                    nearest_dist = None
                    nearest_sid = None
                    last_seen_dt = None
                else:
                    # Find nearest existing track before update
                    cx, cy = p.hip_centroid or (0.0, 0.0)
                    is_norm_c = (-1.0 <= cx <= 2.0) and (-1.0 <= cy <= 2.0)
                    cx_s = cx * 1920.0 if is_norm_c else cx
                    cy_s = cy * 1080.0 if is_norm_c else cy

                    min_dist = 1e9
                    nearest_sid = None
                    for esid, edata in existing_tracks_before.items():
                        ex, ey = edata.get("hip_centroid", (0.0, 0.0))
                        is_norm_e = (-1.0 <= ex <= 2.0) and (-1.0 <= ey <= 2.0)
                        ex_s = ex * 1920.0 if is_norm_e else ex
                        ey_s = ey * 1080.0 if is_norm_e else ey
                        d = ((cx_s - ex_s)**2 + (cy_s - ey_s)**2)**0.5
                        if d < min_dist:
                            min_dist = d
                            nearest_sid = esid
                    
                    nearest_dist = min_dist
                    last_seen_frame = existing_tracks_before[nearest_sid].get("last_seen_frame", 0)
                    frame_gap = frame_idx - last_seen_frame
                    last_seen_dt = frame_gap / fps

                    # Identify anchor mode for this person
                    kps = p.keypoints
                    has_hips = kps[11, 2] > 0.10 and kps[12, 2] > 0.10
                    has_shoulders = kps[5, 2] > 0.10 and kps[6, 2] > 0.10
                    current_anchor = "hip" if has_hips else ("shoulder" if has_shoulders else "mean")

                    prev_anchor = track_anchor_history.get(nearest_sid, "unknown")

                    if is_leap and frame_gap > tracker.grace_period:
                        reason = "FRAME_GAP_GT_GRACE"
                        if is_leap:
                            leap_new_id_count += 1
                    elif prev_anchor != "unknown" and prev_anchor != current_anchor:
                        reason = "ANCHOR_MODE_SWITCH"
                    elif min_dist > tracker.max_distance:
                        reason = "NO_TRACK_WITHIN_GATE"
                    else:
                        reason = "COMPETITION_OR_OTHER"

                # Record anchor mode
                kps = p.keypoints
                has_hips = kps[11, 2] > 0.10 and kps[12, 2] > 0.10
                has_shoulders = kps[5, 2] > 0.10 and kps[6, 2] > 0.10
                anchor_type = "hip" if has_hips else ("shoulder" if has_shoulders else "mean")
                track_anchor_history[sid] = anchor_type

                creations_log.append({
                    "frame": frame_idx,
                    "new_sid": sid,
                    "reason": reason,
                    "nearest_dist": nearest_dist,
                    "nearest_sid": nearest_sid,
                    "last_seen_dt": last_seen_dt,
                    "anchor_type": anchor_type
                })

        if frame_idx % 150 == 0:
            print(f"Processed {frame_idx}/{min(total_frames, max_frames)} frames ({(frame_idx/max_frames)*100:.1f}%) | Active tracks: {len(tracker._tracks)} | New IDs so far: {len(creations_log)}")

    cap.release()
    elapsed = time.time() - start_time
    print(f"\n--- AUDIT COMPLETE in {elapsed:.2f}s ({frame_idx/elapsed:.1f} FPS) ---")
    print(f"Total New ID Creations: {len(creations_log)}")
    print(f"LEAP>grace occurrences: {leap_grace_count}, Resulted in New IDs: {leap_new_id_count}")

    # Summarize by Reason
    from collections import Counter
    counts = Counter(c["reason"] for c in creations_log)
    print("\n--- NEW ID CREATION BREAKDOWN ---")
    for r, count in counts.most_common():
        pct = (count / len(creations_log)) * 100 if creations_log else 0
        print(f"  {r:<28}: {count:>4} ({pct:5.1f}%)")

    # Sample creations
    print("\nSample creations:")
    for c in creations_log[:15]:
        dist_str = f"{c['nearest_dist']:.1f}px" if c['nearest_dist'] is not None else "N/A"
        dt_str = f"{c['last_seen_dt']:.2f}s" if c['last_seen_dt'] is not None else "N/A"
        print(f"  Frame {c['frame']:>4}: New ID #{c['new_sid']:<2} | Reason: {c['reason']:<22} | Nearest: ID #{c['nearest_sid']} @ {dist_str} | dt: {dt_str} | Anchor: {c['anchor_type']}")

    return creations_log, leap_grace_count, leap_new_id_count

if __name__ == "__main__":
    video_p = r"recordings\cam_14\2026-08-25\event_2026-08-25_15-20-10_cam14_knife___cellphone___knife.mp4"
    if not os.path.exists(video_p):
        print(f"File not found: {video_p}")
        sys.exit(1)
    audit_stable_id_creations(video_p, max_frames=1800)  # 1800 frames @ 15fps = 120s (2 minutes)
