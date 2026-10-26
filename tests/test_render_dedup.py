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


def test_bbox_overlap_calculation():
    """Verify _bbox_overlap calculates both IoU and IoA (min-area overlap) accurately."""
    b1 = (100, 100, 200, 200)
    b2 = (100, 100, 200, 200)
    iou, ioa = CentralInferenceManager._bbox_overlap(b1, b2)
    assert iou == 1.0 and ioa == 1.0

    # Small box completely inside big box: ioa must be 1.0
    b_big = (100, 100, 300, 300)
    b_small = (120, 120, 180, 180)
    iou, ioa = CentralInferenceManager._bbox_overlap(b_big, b_small)
    assert ioa == 1.0
    assert iou < 0.3  # IoU is low due to large union, but IoA captures total containment

    # Disjoint boxes
    b_disjoint = (500, 500, 600, 600)
    iou, ioa = CentralInferenceManager._bbox_overlap(b_big, b_disjoint)
    assert iou == 0.0 and ioa == 0.0


def test_incident_record_evidence_added_severity_signature():
    """Verify handle_evidence_added accepts severity and arbitrary kwargs without TypeError."""
    from monitor_app.incident_record import IncidentRecorder
    recorder = IncidentRecorder("cam_1")
    # Should execute without raising TypeError
    recorder.handle_evidence_added("cam_1", "inc_123", "cellphone", [0.85], severity="HIGH", extra_meta=True)


def test_decision_engine_ascii_threshold_formatting():
    """Verify decision engine event labels use ASCII '>=' instead of Unicode '≥'."""
    from monitor_app.decision import DecisionEngine
    from monitor_app.evidence import BehaviorEvidence
    class DummyPacket:
        def __init__(self):
            self.camera_id = "0"
            self.frame = None
            self.detections = {"contraband": [{"name": "cellphone", "confidence": 0.85}], "behavior": []}
            self.behavior_evidence = [
                BehaviorEvidence(
                    stable_id=1,
                    behavior_type="concealment",
                    confidence=0.88,
                    camera_id="0",
                    frame_number=10,
                    timestamp=0.0,
                    sustained_frames=5,
                    metadata={"fusion_confirmed": True}
                )
            ]
            self.tracked_persons = []
            self.timestamp = 0.0

    engine = DecisionEngine()
    packet = DummyPacket()
    event_name, confs = engine.get_event_details(packet)
    assert "≥" not in event_name, f"Found non-ASCII glyph in event_name: {event_name}"
    assert ">=" in event_name
    assert "Cellphone" in event_name and "Concealment" in event_name

