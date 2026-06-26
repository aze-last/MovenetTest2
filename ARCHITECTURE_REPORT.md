# CellWatch Inference & Decision Architecture Report
**Date:** 2026-06-26  
**Scope:** Current pipeline analysis for Suspicious Concealment integration  

---

## 1. Current Inference Pipeline Flow

### Sequence Diagram
```
FRAME CAPTURE
    ↓
camera_view.py (captures frame)
    ↓ creates EvidencePacket(frame, camera_id, timestamp)
    ↓
CentralInferenceManager.submit_task() [Thread Pool Model]
    ↓
central_inference.py::_worker_loop() [PHASE 1-5]
    │
    ├─ PHASE 1: Motion Detection
    │   └─ MotionOptimizedEngine.detect_motion()
    │       └─ MOG2 Background Subtractor + frame diff
    │       └─ Returns: (is_moving: bool, score: float)
    │
    ├─ PHASE 2: Heavy AI (if motion detected)
    │   └─ MotionOptimizedEngine.process_frame()
    │       │
    │       ├─ MoveNet Inference (CPU)
    │       │   └─ Keypoints for each detected person
    │       │
    │       └─ Behavior Classification (HARDCODED HERE)
    │           └─ ai_engine.py::classify_behavior()
    │               └─ Track person velocity → Aggression/Fast Movement
    │
    ├─ PHASE 3: Contraband Detection
    │   └─ YOLO Custom Model (GPU, knife+cellphone)
    │       └─ ByteTrack tracking
    │
    ├─ PHASE 4: Update EvidencePacket
    │   └─ packet.alert_triggered = (aggressive OR fast movement OR knife OR phone)
    │   └─ packet.detections = {behavior: [...], contraband: [...]}
    │
    ├─ PHASE 5: Fusion, Decision & Routing
    │   ├─ CameraFusion.update(packet)  [Latest telemetry cache]
    │   ├─ DecisionEngine.evaluate_trigger(packet)
    │   │   └─ Returns: packet.alert_triggered (binary decision)
    │   ├─ DecisionEngine.get_event_details(packet)
    │   │   └─ Extracts event_type, confidence_scores
    │   └─ EventBus.publish("DECISION_TRIGGER", ...)
    │
    └─ Returns processed EvidencePacket
            ↓
AlertManager::handle_decision() [subscribes to DECISION_TRIGGER]
    │
    ├─ Creates/updates IncidentState (per camera)
    │   └─ State machine: IDLE → PENDING → CONFIRMED → MAINTAINED → COOLDOWN → IDLE
    │
    ├─ On PENDING→CONFIRMED transition:
    │   └─ EventBus.publish("INCIDENT_START", incident_id, event_type, ...)
    │       └─ IncidentRecorder subscribed → Start video recording + buffering
    │
    └─ On evidence added:
        └─ EventBus.publish("EVIDENCE_ADDED", ...)
```

---

## 2. Current Ownership of Decision Logic

### Module Responsibilities (Current)

| Module | Responsibility | Tightly Coupled To |
|--------|---------------|--------------------|
| **central_inference.py** | Queue orchestration, AI pipeline sequencing | ai_engine, decision, fusion |
| **ai_engine.py** | Motion gating, MoveNet inference, **Behavior classification** | config (sensitivity profiles) |
| **decision.py** | Inspect EvidencePacket.alert_triggered, extract event labels | evidence.py |
| **alert_manager.py** | Hysteresis state machine, incident lifecycle | events, incident_record |
| **incident_record.py** | Video buffering, encoding, database writes | events, incidents.db |
| **fusion.py** | Telemetry caching (no ReID, single-camera only) | evidence.py |
| **events.py** | Publish/subscribe event bus | (decoupled) |

### Current Problem: Tightly Coupled Behavior Detection

**Issue:** Behavior detection is hardcoded inside `ai_engine.py::classify_behavior()` as part of MoveNet processing.

```python
# ai_engine.py (line 531-552)
def classify_behavior(self, kps, p_id, cam_id, frame_shape):
    # Tracking uses self.trackers[key] = {'prev': scaled, 'history': []}
    # Single-frame person index (p_id) → NO persistence across frames
    speed = np.linalg.norm(...) / dt
    if avg > self.AGG_THR: return "Aggressive / Fighting", avg
    if avg > self.ACTIVE_THR: return "Fast Movement", avg
    return "Normal", avg
```

**Consequences:**
1. Behavior logic intertwined with pose extraction
2. No reusable behavior evidence model
3. No decoupling for future behavior modules (Fall, Climbing, Concealment)
4. ID is ephemeral (resets if person detection index changes)
5. Cannot sustain evidence across temporary occlusions

---

## 3. Current Alert Flow

### Decision Path
```
EvidencePacket
    ↓
decision.py::evaluate_trigger()
    └─ Returns: packet.alert_triggered (bool)
    
    IF alert_triggered == True:
        ↓
        decision.py::get_event_details()
        └─ Parses packet.detections[behavior/contraband]
        └─ Extracts labels + confidence scores
        └─ EventBus.publish("DECISION_TRIGGER", ...)
            ↓
            alert_manager.py::handle_decision()
            └─ IncidentState.update() [state machine]
            └─ Publishes "INCIDENT_START" → Recorder
            └─ Publishes "EVIDENCE_ADDED" → Recorder
```

### Current Issue: Binary Decision Model
- Decision is **binary** (`alert_triggered: True/False`)
- No accumulation of multiple soft evidence
- No frame-level confidence tracking
- No configurable thresholds per behavior type

---

## 4. Current Evidence Flow

### EvidencePacket Structure (evidence.py)
```python
@dataclass
class EvidencePacket:
    camera_id: str
    timestamp: float
    frame: np.ndarray
    motion_detected: bool
    motion_score: float
    num_people: int
    alert_triggered: bool  # ← BINARY DECISION
    alerts: List[str]      # ← Event labels
    detections: Dict[str, Any]  # behavior: [...], contraband: [...]
    processing_mode: str
```

**Current Structure Issues:**
1. No behavior-specific metadata (stable_id, sustained_frames, confidence)
2. `detections.behavior` is flat list: `[{label, score}]`
3. No connection between behavior events and video evidence
4. No way to track sustained behavioral postures across frames

---

## 5. Existing Coupling That Should Be Reduced

### Coupling Point 1: Behavior Logic in AI Engine
```
ai_engine.py ← TIGHTLY COUPLES
    ├─ MoveNet inference
    ├─ Behavior classification
    ├─ Person tracking (self.trackers)
    ├─ Hard thresholds (AGG_THR, ACTIVE_THR)
    └─ Directly updates EvidencePacket
```

**Decoupling Strategy:**
- Extract behavior classification into separate modules
- Use hip-centroid StableID for persistent person identity
- Publish BehaviorEvidence as independent data structure
- Let decision engine consume BehaviorEvidence + other inputs

### Coupling Point 2: Alert Decision Hardcoded in Packet
```
central_inference.py
    ├─ Sets packet.alert_triggered = (aggressive OR fast OR knife OR phone)
    └─ Decision engine has no say in alert logic
```

**Decoupling Strategy:**
- Decision engine should evaluate all evidence independently
- No hardcoding of alert conditions in inference pipeline
- Config-driven alert thresholds

### Coupling Point 3: Single-Frame Identity
```
ai_engine.py::classify_behavior(kps, p_id, ...)
    └─ p_id is ephemeral (current frame's person index)
    └─ No connection to previous frames if person briefly disappears
```

**Decoupling Strategy:**
- Introduce independent StableID tracker (hip-centroid based)
- Separate from YOLO ByteTrack (which tracks contraband objects)
- Allow 30-frame grace period for occlusions

---

## 6. Missing Abstractions

### No Behavior Module Framework
Currently: **Aggression & Fast Movement hardcoded in ai_engine.py**

Needed for Suspicious Concealment:
1. **Generic BehaviorModule interface**
   - Input: StableID, keypoints, frame_index, sensitivity_profile
   - Output: BehaviorEvidence (or None)
   - No dependency on incident recording

2. **Reusable StableID Tracker**
   - Hip-centroid nearest-neighbor matching
   - Grace period for temporary occlusions
   - Configurable max distance

3. **Evidence Accumulation Model**
   - Frame-count based (not wall-clock)
   - Sustained detections (threshold of consecutive frames)
   - Cooldown to prevent spam

---

## 7. Recommended Architecture

### Directory Structure (Proposed)
```
monitor_app/
├── tracking/
│   └── stable_id.py          [NEW] Independent StableID tracker
├── behaviors/                 [NEW] Behavior module framework
│   ├── __init__.py
│   ├── base_detector.py       [NEW] Abstract BehaviorModule
│   ├── aggression_detector.py [EXTRACTED from ai_engine]
│   ├── movement_detector.py   [EXTRACTED from ai_engine]
│   └── concealment_detector.py [NEW] One-hand occlusion
├── evidence.py               [MODIFIED] Add BehaviorEvidence class
├── ai_engine.py              [REFACTORED] Remove behavior logic
├── central_inference.py       [MODIFIED] Call behavior modules
├── decision.py               [MODIFIED] Consume BehaviorEvidence
└── config.yaml               [MODIFIED] Add behavior params
```

---

## 8. Integration Point: Where Concealment Fits

### Phase 5 of central_inference._worker_loop() [CURRENT]
```python
# After MoveNet + YOLO in process_frame()
packet.alert_triggered = bool(res.get("alert_triggered", False))
get_event_bus().publish("DECISION_TRIGGER", ...)
```

### Phase 5 REFACTORED [PROPOSED]
```python
# After MoveNet + YOLO in process_frame()

# 1. Extract StableID from MoveNet keypoints
stable_persons = self.stable_id_tracker.update(
    keypoints=res["poses"],
    frame_index=frame_index
)

# 2. Run behavior modules
behavior_evidence = []
for detector in self.behavior_detectors:
    evidence = detector.analyze(
        stable_persons=stable_persons,
        frame_index=frame_index,
        sensitivity=active_sensitivity
    )
    if evidence:
        behavior_evidence.append(evidence)

# 3. Decision engine consumes evidence
decision_engine.evaluate_behavior_evidence(behavior_evidence)
```

---

## Summary: Architecture Readiness for Concealment

| Component | Status | Impact |
|-----------|--------|--------|
| **Event Bus** | ✓ Exists | Can publish BehaviorEvidence events |
| **Evidence Model** | ⚠ Needs Extension | Must add BehaviorEvidence class |
| **Orchestration** | ⚠ Hardcoded | central_inference needs behavior module loop |
| **StableID** | ✗ Missing | Must implement hip-centroid tracker |
| **Behavior Framework** | ✗ Missing | Must extract from ai_engine, generalize |
| **Decision Integration** | ⚠ Partial | evaluate_trigger() works, but needs BehaviorEvidence parsing |
| **Config** | ✓ Exists | Can extend with behavior params |
| **Database** | ✓ Exists | incidents.db ready for behavior evidence |

---

## Recommendations Before Implementation

1. **DO extract behavior logic** from ai_engine.py into behaviors/ modules
2. **DO create StableID** as independent tracking/stable_id.py module
3. **DO extend EvidencePacket** with BehaviorEvidence list field (backward compatible)
4. **DO refactor central_inference.py** to orchestrate behavior detectors
5. **DO NOT** modify decision.py's alert thresholds yet (work on evidence accumulation first)
6. **DO NOT** hardcode concealment logic into ai_engine.py
7. **DO NOT** create a new database; reuse incidents.db with behavior_evidence table

---

**Report Complete.** Ready for implementation planning.
