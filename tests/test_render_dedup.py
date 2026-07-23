"""RC-2/RC-3 regression: stacked-box dedup must be RENDER-ONLY.

Safety property under test (jail-monitoring critical): visually suppressing a
duplicate box must never remove a detection from the list the decision path reads.
DecisionEngine reads packet.detections["contraband"] (decision.py:63 and :93) and
packet.tracked_persons/behavior_evidence — the dedup in central_inference.py operates
on a separate draw list built per frame and never mutates those.
"""

import copy

from monitor_app.central_inference import CentralInferenceManager


def _det(name, box, track_id, source="combined", conf=0.9):
    return {"name": name, "confidence": conf, "box": list(box),
            "track_id": track_id, "source": source}


def test_iou_basic():
    iou = CentralInferenceManager._iou
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    # half-overlap: inter 50, union 150
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-9


def test_ghost_overlapping_live_is_skipped_from_draw_list_only():
    live = _det("knife", (100, 100, 200, 200), track_id=7)
    ghost = _det("knife", (102, 101, 199, 202), track_id=3,
                 source="combined_hysteresis")
    detections = [live, ghost]
    before = copy.deepcopy(detections)

    drawable = CentralInferenceManager._contraband_for_render(detections)

    # ghost suppressed from DRAW list
    assert live in drawable
    assert ghost not in drawable
    # decision-path list is byte-identical — nothing removed or mutated
    assert detections == before
    assert len(detections) == 2


def test_non_overlapping_ghost_still_drawn():
    live = _det("knife", (100, 100, 200, 200), track_id=7)
    ghost_far = _det("knife", (400, 400, 500, 500), track_id=3,
                     source="combined_hysteresis")
    drawable = CentralInferenceManager._contraband_for_render([live, ghost_far])
    assert live in drawable and ghost_far in drawable


def test_second_real_object_same_spot_never_suppressed():
    """Two LIVE same-class detections at the same location (a genuine second knife)
    must both be drawn AND both remain visible to the decision path — dedup only
    ever targets source == combined_hysteresis."""
    knife_a = _det("knife", (100, 100, 200, 200), track_id=7)
    knife_b = _det("knife", (105, 103, 205, 203), track_id=8)
    detections = [knife_a, knife_b]
    drawable = CentralInferenceManager._contraband_for_render(detections)
    assert knife_a in drawable and knife_b in drawable
    assert len(detections) == 2


def test_different_class_overlap_not_suppressed():
    knife = _det("knife", (100, 100, 200, 200), track_id=7)
    phone_ghost = _det("cellphone", (102, 101, 199, 202), track_id=3,
                       source="combined_hysteresis")
    drawable = CentralInferenceManager._contraband_for_render([knife, phone_ghost])
    assert phone_ghost in drawable


def test_missing_source_key_treated_as_live():
    """Detections without a source key (older result dicts) must never be dropped."""
    a = {"name": "knife", "confidence": 0.9,
         "box": [100, 100, 200, 200], "track_id": 7}
    b = {"name": "knife", "confidence": 0.8,
         "box": [101, 101, 201, 201], "track_id": 8}
    drawable = CentralInferenceManager._contraband_for_render([a, b])
    assert a in drawable and b in drawable
