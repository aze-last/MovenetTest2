"""RC-1 evidence harness (Phase A5) — NOT a pytest test.

Reproduces the exact production thread topology around StableIDTracker to prove or
refute that two threads can be inside tracker.update() concurrently:

  Thread A ("movenet-exec"):  concurrent.futures.ThreadPoolExecutor(max_workers=1),
                              identical to CentralInferenceManager.movenet_executor.
                              Calls tracker.update() the way
                              ai_engine._run_movenet_logic does (update #1).
  Thread B ("worker"):        plain loop thread, identical role to
                              CentralInferenceManager._worker_loop ->
                              BehaviorEngine.analyze_packet (update #2).

Both use the SAME per-camera tracker instance obtained through the real singleton
accessor get_behavior_engine()._get_tracker(cam_id), i.e. the same object identity
relationship as production (ai_engine.py:502 and behaviors/engine.py:35).

Run:
  .venv310\\Scripts\\python.exe tests\\diag_rc1_concurrency.py

Output: [FLICKER-A5] lines from StableIDTracker plus a final verdict. Any
"OVERLAP" line = two distinct thread idents concurrently inside update().
"""

import sys
import os
import threading
import time
import concurrent.futures

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from monitor_app.evidence import TrackedPerson
from monitor_app.behaviors import get_behavior_engine

CAM_ID = "diag_cam"
DURATION_S = 10.0
WORKER_FPS = 30.0     # worker-loop cadence (packets arriving from camera thread)
MOVENET_HZ = 12.0     # async MoveNet completion cadence (~80ms CPU inference)
N_PERSONS = 6         # MoveNet max — widens time spent inside update()


def make_persons(frame_number: int, jitter: float) -> list:
    """Multi-person list with slight per-frame centroid jitter, like a live scene."""
    persons = []
    for i in range(N_PERSONS):
        base_x = 0.1 + i * 0.15
        cx = base_x + jitter
        cy = 0.55 + jitter
        kps = np.zeros((17, 3), dtype=np.float32)
        kps[5] = [0.35, cx - 0.03, 0.9]   # shoulders
        kps[6] = [0.35, cx + 0.03, 0.9]
        kps[11] = [cy, cx - 0.02, 0.9]    # hips
        kps[12] = [cy, cx + 0.02, 0.9]
        persons.append(TrackedPerson(
            stable_id=-1, raw_person_id=i, camera_id=CAM_ID,
            keypoints=kps, hip_centroid=(cx, cy),
            confidence=0.8, frame_number=frame_number, timestamp=time.time(),
        ))
    return persons


def main():
    tracker = get_behavior_engine()._get_tracker(CAM_ID)
    tracker._trace = True  # force A5 instrument on regardless of config.yaml

    stop = threading.Event()
    frame_counter = {"worker": 0, "movenet": 0}

    # Thread A: mimics CentralInferenceManager.movenet_executor (max_workers=1)
    movenet_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="movenet-exec")

    def movenet_update(frame_number):
        # update #1 — ai_engine._run_movenet_logic:531
        tracker.update(make_persons(frame_number, jitter=0.001), frame_number)
        frame_counter["movenet"] += 1

    def movenet_submitter():
        fn = 0
        while not stop.is_set():
            fn += 2  # movenet_skip=2 cadence
            movenet_executor.submit(movenet_update, fn)
            time.sleep(1.0 / MOVENET_HZ)

    # Thread B: mimics _worker_loop -> BehaviorEngine.analyze_packet
    def worker_loop():
        fn = 0
        while not stop.is_set():
            fn += 1
            # update #2 — behaviors/engine.py:36
            tracker.update(make_persons(fn, jitter=0.002), fn)
            frame_counter["worker"] += 1
            time.sleep(1.0 / WORKER_FPS)

    t_sub = threading.Thread(target=movenet_submitter, name="movenet-submitter")
    t_wrk = threading.Thread(target=worker_loop, name="worker")
    t_sub.start()
    t_wrk.start()
    time.sleep(DURATION_S)
    stop.set()
    t_sub.join()
    t_wrk.join()
    movenet_executor.shutdown(wait=True)

    print("\n===== RC-1 EVIDENCE VERDICT =====")
    print(f"worker updates:   {frame_counter['worker']}")
    print(f"movenet updates:  {frame_counter['movenet']}")
    print(f"observed overlaps (two threads inside update() concurrently): "
          f"{tracker._overlap_count}")
    if tracker._overlap_count > 0:
        print("VERDICT: CONFIRMED — StableIDTracker.update() is entered concurrently "
              "by two distinct threads. RC-1 lock fix is justified.")
        return 0
    print("VERDICT: NOT OBSERVED in this run — RC-1 remains unconfirmed; "
          "do not proceed with the lock fix on this evidence alone.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
