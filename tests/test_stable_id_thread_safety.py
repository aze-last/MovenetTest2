"""RC-1 regression: StableIDTracker must be safe under concurrent update() calls
from two threads (MoveNet executor + central worker), which is the production
topology (ai_engine._run_movenet_logic and behaviors/engine.analyze_packet share
the same per-camera tracker singleton).

Evidence base: tests/diag_rc1_concurrency.py observed 103 concurrent entries in
10s before the lock was added.
"""

import threading
import time

import numpy as np

from monitor_app.evidence import TrackedPerson
from monitor_app.tracking.stable_id import StableIDTracker


def _make_persons(camera_id, frame_number, n=6, jitter=0.0):
    persons = []
    for i in range(n):
        cx = 0.1 + i * 0.15 + jitter
        cy = 0.55 + jitter
        kps = np.zeros((17, 3), dtype=np.float32)
        kps[5] = [0.35, cx - 0.03, 0.9]
        kps[6] = [0.35, cx + 0.03, 0.9]
        kps[11] = [cy, cx - 0.02, 0.9]
        kps[12] = [cy, cx + 0.02, 0.9]
        persons.append(TrackedPerson(
            stable_id=-1, raw_person_id=i, camera_id=camera_id,
            keypoints=kps, hip_centroid=(cx, cy),
            confidence=0.8, frame_number=frame_number, timestamp=time.time(),
        ))
    return persons


def test_concurrent_updates_do_not_overlap_or_explode_ids():
    tracker = StableIDTracker(max_distance=120.0, grace_period=30)
    n_threads = 4
    iterations = 200
    errors = []
    barrier = threading.Barrier(n_threads)

    def hammer(thread_idx):
        try:
            barrier.wait()
            for it in range(iterations):
                frame = it + 1
                tracker.update(
                    _make_persons("cam_x", frame, jitter=0.001 * thread_idx), frame
                )
        except Exception as e:  # dict-mutation races surface as RuntimeError/KeyError
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent update() raised: {errors}"
    # 6 near-stationary persons must not fragment into a flood of new IDs.
    # Allow slack for first-frame creation and jitter-boundary churn, but a race
    # (pre-lock) produced dozens of spurious IDs under this load.
    assert tracker._next_id < 6 * 3, (
        f"ID churn detected: {tracker._next_id} IDs allocated for 6 persons"
    )


def test_update_serialization_via_inside_counter():
    """The A5 diagnostic counter must never observe a second thread inside update()."""
    tracker = StableIDTracker(max_distance=120.0, grace_period=30)
    tracker._trace = False  # keep output quiet; we assert on the counter directly

    overlaps = []
    orig = tracker._update_locked

    def probed(persons, frame_number):
        tracker._inside += 1
        if tracker._inside > 1:
            overlaps.append(tracker._inside)
        try:
            time.sleep(0.001)  # widen the window a race would need
            return orig(persons, frame_number)
        finally:
            tracker._inside -= 1

    tracker._update_locked = probed

    def worker(idx):
        for it in range(100):
            tracker.update(_make_persons("cam_y", it + 1, jitter=0.001 * idx), it + 1)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert overlaps == [], f"threads overlapped inside update(): {overlaps}"
