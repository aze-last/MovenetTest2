# Suspicious Concealment Feature
## Revised Capstone-Safe Implementation Plan

**Status:** Ready for implementation  
**Scope:** Minimal-risk extension to the existing pipeline  
**Principles:**
- Keep aggression and fast movement unchanged for now
- Introduce a simple TrackedPerson object for future behavior modules
- Keep StableID in the perception layer under tracking/
- Implement concealment as a single new detector module
- Do not introduce a BehaviorDetector framework yet

---

## Phase 0: StableID Infrastructure
**Purpose:** Extract the existing hip-centroid tracking logic from ai_engine into a reusable subsystem.  
**Risk:** Low  
**Output:** monitor_app/tracking/stable_id.py

### What to implement
- Create the tracking package and init file
- Move the current nearest-neighbor hip-centroid matching logic into StableIDTracker
- Keep the behavior unchanged from the current implementation
- Make max-distance and grace period configurable from config.yaml

### Important constraint
- StableID is infrastructure, not a concealment feature
- It should be usable by future detectors later, such as loitering or collapse detection

---

## Phase 1: TrackedPerson Model
**Purpose:** Preserve MoveNet keypoints and metadata as a single object that flows through the pipeline.  
**Risk:** Low  
**Output:** TrackedPerson dataclass in evidence.py or a small shared model module

### TrackedPerson fields
- stable_id
- raw_person_id
- camera_id
- keypoints
- bbox
- hip_centroid
- confidence
- frame_number
- timestamp

### Why this is needed
- Today the pipeline drops the most valuable part of MoveNet output
- A single TrackedPerson object keeps the pipeline behavior-centric instead of alert-only

---

## Phase 2: Wire MoveNet → StableID → TrackedPerson
**Purpose:** Preserve the pose output as a first-class object after MoveNet.  
**Risk:** Medium  
**Output:** TrackedPerson objects created immediately after MoveNet inference

### Pipeline shape
Camera
↓
MoveNet
↓
StableID
↓
TrackedPerson[]
↓
YOLO
↓
Behavior modules
↓
Decision Engine

### Important constraint
- Keep StableID close to perception, immediately after MoveNet
- Do not move StableID ownership into central_inference
- Do not add a framework layer around detectors yet

---

## Phase 3: Implement One-Hand Occlusion Detector
**Purpose:** Add a dedicated module for the new feature while avoiding any refactor of the existing aggression or fast movement logic.  
**Risk:** Medium  
**Output:** monitor_app/one_hand_occlusion_detector.py or monitor_app/concealment_detector.py

### Internal naming
- Internal engineering name: Sustained One-Hand Occlusion
- Operator-facing label: Suspicious Concealment

### Detector responsibilities
- Monitor left and right wrist independently
- Ignore both-wrists-missing frames
- Reject side-profile false positives with a shoulder-width yaw gate
- Accumulate consecutive frames before evidence is emitted
- Apply a cooldown to suppress repeated alerts
- Return BehaviorEvidence only; never create incidents directly

### Input
- One TrackedPerson

### Output
- BehaviorEvidence with:
  - behavior_type
  - stable_id
  - confidence
  - frame_number
  - timestamp
  - metadata

---

## Phase 4: BehaviorEvidence Integration
**Purpose:** Feed the detector output into the existing decision process without introducing a parallel event pipeline.  
**Risk:** Low  
**Output:** BehaviorEvidence attached to EvidencePacket and consumed by decision.py

### Approach
- Extend EvidencePacket with a behavior_evidence list
- Keep the existing detections structure intact for backward compatibility
- Decision Engine converts BehaviorEvidence into alert labels and confidence scores

### Non-goals
- No separate behavior event bus
- No new incident-writing path in the detector
- No UI side effects from the detector

---

## Phase 5: Alert flow and validation
**Purpose:** Ensure the new evidence reaches alerting and incident recording end-to-end.  
**Risk:** Low  

### Validation focus
- Existing aggression detection still works
- Existing fast movement detection still works
- Concealment evidence triggers only after threshold frames
- Cooldown suppresses repeated alerts
- Side-profile walking does not trigger false positives

---

## What will not be changed in this pass
- Aggression and fast movement remain in the existing implementation
- No BehaviorDetector base class yet
- No extraction of aggression or movement into separate modules yet
- No new coordinator layer beyond the existing inference flow

---

## Definition of Done
- StableID exists as a reusable tracking module
- MoveNet output is preserved as TrackedPerson objects
- Concealment produces BehaviorEvidence
- Decision Engine consumes that evidence
- Existing alerts remain intact and the new feature is validated

- [ ] Existing aggression/fast movement still triggers (no regression)
- [ ] Concealment evidence triggers when present
- [ ] Confidence scores properly extracted
- [ ] Event labels properly formatted

---

## Phase 5: Central Inference Pipeline Integration
**Purpose:** Wire concealment detector into main AI loop  
**Risk Level:** MEDIUM (touches central orchestration)  
**Duration:** 1-2 hours

### 5.1 Modify `monitor_app/central_inference.py`

**Current Flow (PHASE 2 AI Processing):**
```python
if self.engine and not self.inference_paused:
    res = self.engine.process_frame(packet.frame, packet.camera_id)
    # res contains poses, alerts, detections
    packet.num_people = res.get("num_people", 0)
    packet.alert_triggered = bool(res.get("alert_triggered", False))
    packet.detections = res.get("detections", {...})
```

**New Flow (Insert StableID + Behavior Detectors):**
```python
if self.engine and not self.inference_paused:
    res = self.engine.process_frame(packet.frame, packet.camera_id)
    packet.num_people = res.get("num_people", 0)
    packet.alert_triggered = bool(res.get("alert_triggered", False))
    packet.detections = res.get("detections", {...})
    
    # NEW: StableID + Behavior Detectors
    poses = res.get("poses", [])  # Extract from engine output
    frame_number = res.get("frame_number", 0)
    
    # Update StableID tracker
    stable_persons = self.stable_id_tracker.update(poses, frame_number)
    
    # Run concealment detector
    behavior_evidence = []
    for stable_id, person_track in stable_persons.items():
        evidence = self.concealment_detector.analyze(
            person_track, 
            frame_number,
            sensitivity_profile
        )
        if evidence:
            behavior_evidence.append(evidence)
    
    packet.behavior_evidence = behavior_evidence
```

**New Attributes to CentralInferenceManager:**
```python
def __init__(self, ...):
    # ... existing ...
    from monitor_app.tracking.stable_id import StableIDTracker
    from monitor_app.concealment_detector import ConcealmentDetector
    
    self.stable_id_tracker = StableIDTracker(
        max_distance=get_config("behavior_modules", "stable_id", {}).get("max_tracking_distance", 120),
        grace_period=get_config("behavior_modules", "stable_id", {}).get("grace_period_frames", 30)
    )
    
    self.concealment_detector = ConcealmentDetector(
        config=get_config("behavior_modules", {})
    )
```

**Validation Checklist:**
- [ ] Poses are extracted from engine output (check ai_engine.py return structure)
- [ ] StableID tracker initializes with config values
- [ ] Concealment detector receives valid PersonTrack objects
- [ ] behavior_evidence field populated in EvidencePacket
- [ ] Existing inference latency unchanged (no performance regression)

---

## Phase 6: Configuration Extension
**Purpose:** Add tuning parameters to config.yaml  
**Risk Level:** LOW (configuration only)  
**Duration:** 30 minutes

### 6.1 Modify `config.yaml`

**Add behavior_modules section:**
```yaml
behavior_modules:
  stable_id:
    max_tracking_distance: 120      # pixels, for hip-centroid matching
    grace_period_frames: 30         # frames to survive occlusion
  
  concealment:
    frame_threshold: 27             # ~1.5s at 18 FPS
    cooldown_frames: 60             # prevent alert spam
    yaw_gate_threshold: 30          # degrees (suppress side-view)
    wrist_confidence_threshold: 0.3 # MoveNet keypoint confidence
```

**Validation Checklist:**
- [ ] `get_config("behavior_modules", "stable_id", "max_tracking_distance", 120)` works
- [ ] `get_config("behavior_modules", "concealment", "frame_threshold", 27)` works
- [ ] Defaults are sensible if config.yaml is missing

---

## Phase 7: Alert Manager & Incident Recording
**Purpose:** Verify event flow from BehaviorEvidence to incident  
**Risk Level:** LOW (events already work)  
**Duration:** 1 hour

### 7.1 Verify Alert Flow (No Code Changes Expected)

**Flow:**
```
central_inference.py
    └─ Populates packet.behavior_evidence
    
    → PHASE 5: Fusion, Decision & Routing
    
decision.py::evaluate_trigger()
    └─ Checks packet.behavior_evidence
    
decision.py::get_event_details()
    └─ Extracts "Suspicious Concealment" label
    
EventBus.publish("DECISION_TRIGGER", event_type="Suspicious Concealment", ...)
    
alert_manager.py::handle_decision()
    └─ Creates/updates IncidentState
    └─ Publishes "INCIDENT_START"
    
incident_record.py::handle_incident_start()
    └─ Starts video recording + buffering
    └─ Writes to incidents.db
```

**Validation Checklist:**
- [ ] Concealment evidence triggers incident recording
- [ ] Incident type correctly labeled "Suspicious Concealment"
- [ ] Confidence score from BehaviorEvidence stored in incidents.db
- [ ] Operator can review incident in dashboard
- [ ] Cooldown prevents duplicate incidents within 60 frames

---

## Phase 8: Testing & Validation
**Purpose:** Regression testing + concealment-specific validation  
**Risk Level:** MEDIUM (must not break existing detectors)  
**Duration:** 2-4 hours

### 8.1 Regression Tests (Existing Behavior Unaffected)

**Test 1: Aggression Detection Unchanged**
- Capture footage of aggressive posture (MoveNet tracked)
- Verify `packet.detections.behavior` still contains "Aggressive / Fighting"
- Verify incident is recorded with correct label
- Verify aggression detector FPS unchanged

**Test 2: Fast Movement Detection Unchanged**
- Capture footage of fast arm movement
- Verify `packet.detections.behavior` still contains "Fast Movement"
- Verify incident recorded with correct label

**Test 3: Contraband Detection Unchanged**
- Capture footage with knife/phone in view
- Verify YOLO still detects contraband
- Verify incident recorded with correct label

**Test 4: Multi-Alert Fusion Unchanged**
- Trigger multiple alerts simultaneously (aggressive + knife)
- Verify incident labels both behaviors
- Verify event_type = "Aggressive + knife" or similar

### 8.2 Concealment-Specific Tests

**Test 5: StableID Single Person Walking**
- One person walks into frame, stands, walks out
- Verify same stable_id throughout
- Verify ID does NOT change when person rotates

**Test 6: StableID Occlusion Recovery**
- Person walks, briefly disappears (behind obstacle), reappears
- Verify same stable_id maintained across occlusion
- Verify NOT a new person spawned

**Test 7: StableID Two People Crossing**
- Two people walk across camera, cross paths
- Verify IDs do NOT swap
- Verify each maintains own trajectory

**Test 8: Yaw Gate Rejects Side Profile**
- Person walks sideways across camera (pure side-profile)
- Verify NO concealment evidence generated
- Verify frontal walking DOES generate evidence (if wrist hidden)

**Test 9: Concealment One Wrist Hidden**
- Person faces camera with left hand hidden (in pocket, etc.)
- Right hand visible
- Count frames: Should trigger after ~27 frames
- Verify BehaviorEvidence generated
- Verify confidence ~0.9

**Test 10: Concealment Wrist Flicker**
- Wrist appears/disappears rapidly (confidence noise)
- Verify counter resets on appearance
- Verify NO false positive

**Test 11: Concealment Cooldown**
- Generate one concealment alert
- Within 60 frames, evidence resets but still present
- Verify NO duplicate incident created during cooldown
- Verify new incident AFTER cooldown expires

**Test 12: Concealment Both Wrists Missing**
- Both hands disappear simultaneously
- Verify NO evidence generated
- (Ignore this as "both hands in lap" not suspicious)

### 8.3 Performance Validation

**Test 13: FPS Baseline**
- Run without any new detectors
- Measure average FPS on target hardware (ASUS TUF RTX 2050)
- Record baseline

**Test 14: FPS with StableID Only**
- Enable StableID, disable concealment detector
- Measure FPS delta
- Should be < 1 FPS drop (lightweight tracking)

**Test 15: FPS with Concealment Detector**
- Enable both StableID and concealment detector
- Measure FPS delta
- Should be < 2 FPS total impact
- Verify 4 cameras still run stably at 18-30 FPS

### 8.4 Scientific Integrity Check

**Test 16: Documentation Audit**
- Verify concealment_detector.py describes as "Sustained One-Hand Occlusion"
- Verify UI labels as "Suspicious Concealment"
- Verify no claims of "concealed object detection"
- Verify manuscript clarifies RGB-only limitation

**Test 17: Operator UX**
- Verify incident dashboard shows:
  - Event type: "Suspicious Concealment"
  - Confidence score
  - Timestamp
  - Video evidence
- Verify operator can review video evidence

---

## Implementation Checklist (Full Project)

### Phase 1: StableID
- [ ] Directory created
- [ ] `PersonTrack` dataclass defined
- [ ] `StableIDTracker.update()` implemented
- [ ] Hip-centroid extraction working
- [ ] Nearest-neighbor matching working
- [ ] Grace period implemented
- [ ] Unit tests passing

### Phase 2: BehaviorEvidence
- [ ] `BehaviorEvidence` dataclass added to evidence.py
- [ ] `EvidencePacket.behavior_evidence` field added
- [ ] to_dict() / from_dict() updated
- [ ] Backward compatibility verified

### Phase 3: Concealment Detector
- [ ] `ConcealmentDetector` class implemented
- [ ] Wrist visibility logic working
- [ ] Yaw gate implemented and tuned
- [ ] Frame accumulation logic working
- [ ] Cooldown logic working
- [ ] BehaviorEvidence generation working

### Phase 4: Decision Engine
- [ ] `evaluate_trigger()` checks behavior_evidence
- [ ] `get_event_details()` extracts "Suspicious Concealment" label
- [ ] Confidence scores properly combined

### Phase 5: Central Inference
- [ ] StableIDTracker initialized
- [ ] ConcealmentDetector initialized
- [ ] Poses extracted from engine output
- [ ] StableID update called
- [ ] Concealment detector called
- [ ] EvidencePacket.behavior_evidence populated

### Phase 6: Configuration
- [ ] config.yaml extended with behavior_modules section
- [ ] All parameters configurable and used

### Phase 7: Alert Manager
- [ ] Event flow verified end-to-end
- [ ] Incident recording triggered by concealment evidence
- [ ] Dashboard displays "Suspicious Concealment"

### Phase 8: Testing
- [ ] Regression tests: aggression, fast movement, contraband unchanged
- [ ] StableID tests: walking, occlusion, crossing
- [ ] Yaw gate tests: side-profile, frontal
- [ ] Concealment tests: single wrist, flicker, cooldown, both missing
- [ ] FPS tests: baseline, StableID only, full impact
- [ ] Scientific integrity: documentation audit, operator UX

---

## Known Dependencies & Integration Points

### ai_engine.py
- Must export `poses` (MoveNet keypoints) in `process_frame()` return dict
- Must include `frame_number` in output
- **Status:** ⚠️ Verify structure before Phase 5

### central_inference.py
- Must have access to active sensitivity profile
- Must initialize StableIDTracker and ConcealmentDetector
- **Status:** ⚠️ Check current profile_store integration

### evidence.py
- Current structure is dataclass-based ✓
- **Status:** ✓ Ready

### decision.py
- Current `evaluate_trigger()` is simple binary ✓
- Must extend to check `packet.behavior_evidence` length
- **Status:** ✓ Ready

### config.yaml
- Already has alert_cooldowns section ✓
- Can extend with behavior_modules ✓
- **Status:** ✓ Ready

---

## Risk Mitigation

**Risk 1: Regression in existing detectors**
- *Mitigation:* Run full regression tests before marking complete
- *Fallback:* Revert behavior_evidence field if issues found

**Risk 2: StableID matches people incorrectly**
- *Mitigation:* Conservative max_distance + grace_period tuning
- *Fallback:* Increase max_distance if people get confused

**Risk 3: Concealment detector generates too much noise**
- *Mitigation:* High frame_threshold (27) + long cooldown (60)
- *Fallback:* Increase frame_threshold, add operator sensitivity tuning

**Risk 4: Performance degradation on 4 cameras**
- *Mitigation:* Phase 8 FPS tests to catch regressions
- *Fallback:* Optimize StableID matching algorithm or disable concealment on low-spec runs

**Risk 5: ai_engine.py output format unknown**
- *Mitigation:* Read ai_engine process_frame() return carefully before Phase 5
- *Fallback:* Extract poses manually if not in output dict

---

## Definition of Done (Per Phase)

### Phase 1 Complete When:
- StableID module importable
- StableID tracker maintains IDs across occlusions
- Unit tests pass

### Phase 2 Complete When:
- BehaviorEvidence dataclass created
- EvidencePacket extended
- No breaking changes to existing code

### Phase 3 Complete When:
- Concealment detector runs without crashes
- Generates BehaviorEvidence objects with valid fields
- Cooldown logic prevents spam

### Phase 4 Complete When:
- Decision engine parses behavior_evidence without crashing
- Event labels include "Suspicious Concealment"
- Confidence scores extracted correctly

### Phase 5 Complete When:
- central_inference calls StableID and concealment detector
- BehaviorEvidence populated in EvidencePacket
- No new exceptions in inference loop

### Phase 6 Complete When:
- config.yaml has behavior_modules section
- All hardcoded values in detectors read from config

### Phase 7 Complete When:
- Concealment evidence triggers incident recording
- Dashboard displays incident
- Video evidence captured

### Phase 8 Complete When:
- All 17 tests pass
- No regression in existing detectors
- FPS impact < 2 FPS on target hardware
- Documentation audit passed

---

## Ready to Begin Implementation 🚀

This plan is capstone-safe:
- Minimizes changes to existing ai_engine.py
- Preserves working aggression/fast movement detectors
- Introduces concealment as isolated, new module
- Maintains backward compatibility throughout
- Provides clear success criteria for each phase

**Proceed to Phase 1 implementation on approval.**
