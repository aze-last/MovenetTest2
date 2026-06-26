# Architecture Integration Report
## Canonical Person Representation & StableID Integration

**Date:** 2026-06-26  
**Author:** Architecture Review  
**Status:** CRITICAL DISCOVERY - Blocks Phase 1  

---

## Executive Summary

The current implementation **loses the canonical person representation** after MoveNet inference.

MoveNet produces full keypoint data, but:
1. Keypoints are discarded after behavior classification
2. StableID logic already exists inside ai_engine, but it is coupled to concealment-specific state
3. Downstream modules receive only summary labels and scores
4. New behavior modules would need to re-derive pose details from scratch

The cleanest capstone-safe fix is to introduce a minimal `TrackedPerson` abstraction and a reusable StableID tracker while leaving the existing aggression and fast movement logic intact.

---

## 1. Canonical Pose Representation (Current State)

### Raw Output from MoveNet
```python
# ai_engine.py::_run_movenet_logic() - Line 404
outputs = self.movenet(tensor)
kpts = outputs["output_0"].numpy()[0]  # Shape: (6, 51) for up to 6 people

# Each person (51 values = 17 keypoints × 3 values)
person = kpts[i, :51].reshape(17, 3)  # Shape: (17, 3)
# 17 keypoints: [y, x, confidence] for each
```

### Intermediate Representation (Still in ai_engine.py)
```python
# Lines 410-425: Detected people before stability matching
detected_people = [
    {
        "p_id": i,                    # MoveNet detection index (0-5)
        "hip_centroid": (x, y),       # From keypoints 11 & 12
        "kps": person,                # 17×3 array - FULL KEYPOINTS
        "label": label,               # "Aggressive", "Fast Movement", "Normal"
        "score": score                # Confidence in behavior
    },
    ...
]

# After _match_concealment_ids() - Line 427
detected_people = [
    {
        "p_id": i,
        "hip_centroid": (x, y),
        "kps": person,
        "label": label,
        "score": score,
        "stable_id": stable_id        # ← ADDED HERE
    },
    ...
]
```

### Final Output (Flattened & Keypoints Discarded)
```python
# Lines 431-436: What gets returned to central_inference
res["detections"]["behavior"] = [
    {
        "person_index": dp["p_id"],
        "stable_id": dp["stable_id"],
        "label": dp["label"],
        "score": dp["score"]
        # ⚠️ KEYPOINTS (kps) ARE LOST HERE
    },
    ...
]
```

### Lifecycle Through Pipeline
```
MoveNet                     central_inference           decision            alert_manager
│                            │                          │                   │
└─→ kpts (17×3)    ┌─────────┴─→ res dict              └─→ EvidencePacket ┐
    (17 keypoints) │ _run_movenet_logic()                    (no kpts)    │
    │              │                                                       ├─→ IncidentState
    ├→ person dict │ detected_people [                                   │   (no kpts)
    │  with kpts   │   {kps, stable_id, ...}                             │
    │  + stable_id │ ]                                                   └─→ incident_record
    │              │                                                         (no kpts)
    ├→ draw_skel   │ Flattened to:
    │   res["detections"]["behavior"] [  
    │     {stable_id, label, score}     ← KEYPOINTS LOST
    │   ]
    └→ KEYPOINTS DISCARDED
       after line 431
```

---

## 2. Canonical Person Lifecycle (Current State)

### Point A: MoveNet Inference (ai_engine.py:405)
```
Status: Full keypoint data available
Structure: numpy array (17, 3)
Location: _run_movenet_logic() local scope
Accessibility: Local variable only
```

### Point B: Detected People Assembled (ai_engine.py:418)
```
Status: Full keypoint + metadata + behavior
Structure: Dict with kps, hip_centroid, label, score, p_id
Location: detected_people list (local)
Accessibility: Local variable only
```

### Point C: StableID Assignment (ai_engine.py:427 via _match_concealment_ids)
```
Status: StableID now added to detected_people
Structure: Dict now includes stable_id key
Location: Still in detected_people list (local)
Accessibility: Local variable only
```

### Point D: Flattening to res["detections"] (ai_engine.py:431)
```
Status: ⚠️ CRITICAL - Keypoints discarded
Structure: Only {person_index, stable_id, label, score}
Location: res["detections"]["behavior"]
Accessibility: Passed to central_inference.py via return value
PROBLEM: Keypoints lost, only summary available
```

### Point E: EvidencePacket Assembly (central_inference.py:180)
```
Status: Keypoints NOT in packet
Structure: packet.detections (from res["detections"])
Location: central_inference.py _worker_loop()
Accessibility: Passed to decision.py + others
PROBLEM: No way to access original poses for new behavior analysis
```

### Point F: Decision Engine (decision.py)
```
Status: Only summary detections available
Structure: packet.detections[behavior/contraband]
Accessibility: Can read labels/scores only
PROBLEM: Cannot perform new behavioral analysis on poses
```

### Point G: Incident Recording (incident_record.py)
```
Status: Only summary stored in incidents.db
Structure: event_type, confidence_scores
Accessibility: Video + metadata in database
PROBLEM: Pose data not available for post-analysis or validation
```

---

## 3. StableID: Discovery of Existing Implementation

### ⚠️ SURPRISE FINDING

StableID is **ALREADY PARTIALLY IMPLEMENTED** in ai_engine.py!

**Location:** Lines 125-130 + 332-391

```python
# ai_engine.py.__init__()
self.concealment_trackers = {}
self.CONCEALMENT_MAX_MATCH_DIST = 120.0
self.CONCEALMENT_GRACE_FRAMES = 30

# ai_engine.py._match_concealment_ids()
def _match_concealment_ids(self, cam_id, detected_people):
    """
    Hip-centroid nearest-neighbor matching.
    Maintains IDs across temporary occlusions.
    """
```

### Existing StableID Capabilities
✓ Hip-centroid calculation (keypoints 11 & 12)  
✓ Nearest-neighbor matching with max distance  
✓ Grace period for temporary occlusions (30 frames)  
✓ Per-camera tracking state  
✓ ID reuse prevention  

### Existing StableID Limitations
✗ Hardcoded max distance (120 pixels)  
✗ Hardcoded grace period (30 frames)  
✗ NOT configurable from config.yaml  
✗ Tightly coupled to concealment tracking state  
✗ Only used internally (not exposed for other detectors)  
✗ State stored in `self.concealment_trackers[cam_id]["people"]` with concealment-specific fields  

### Existing State Tracking
```python
# What ai_engine maintains per stable_id:
existing[stable_id] = {
    "hip_centroid": (x, y),
    "last_seen_frame": frame_num,
    "left_wrist_missing_since": None,       # Concealment-specific
    "right_wrist_missing_since": None,      # Concealment-specific
    "concealment_flagged": False,           # Concealment-specific
    "cooldown_until_frame": 0               # Concealment-specific
}
```

---

## 4. Best Integration Point for StableID

### Current Structure (Suboptimal)
```
MoveNet
    ↓
ai_engine.py::_run_movenet_logic()
    ├─ Extract poses
    ├─ Calculate behavior (classify_behavior)
    ├─ Assign stable IDs (_match_concealment_ids)  ← Tightly coupled
    └─ Flatten to res["detections"]
            ↓
central_inference.py
    └─ Only gets flattened result
```

### Recommended Structure
```
MoveNet
    ↓
StableID
    ↓
TrackedPerson[]
    ↓
YOLO
    ↓
Behavior Modules
    ↓
BehaviorEvidence
    ↓
Decision Engine
```

---

## 5. Behavior Module Input Interface (Approved Scope)

### Required: TrackedPerson Model

```python
@dataclass
class TrackedPerson:
    """Canonical representation of a detected person in a single frame."""
    stable_id: int
    raw_person_id: int
    camera_id: str
    keypoints: np.ndarray
    bbox: Optional[Tuple[int, int, int, int]] = None
    hip_centroid: Optional[Tuple[float, float]] = None
    confidence: float = 0.0
    frame_number: int = 0
    timestamp: float = 0.0
```

### Detector Interface

For this capstone, the detector can simply use a simple function signature:

```python
def analyze(person: TrackedPerson, sensitivity: str) -> Optional[BehaviorEvidence]:
    ...
```

No base-class framework is needed yet. The module is just a function or class with one clear entry point.

---

## 6. Evidence Integration & Final Data Flow

### BehaviorEvidence (Already Approved)
```python
@dataclass
class BehaviorEvidence:
    behavior_type: str              # "concealment", "aggression", etc.
    stable_id: int                  # Link back to person
    confidence: float
    frame_number: int
    timestamp: float
    sustained_frames: int
    metadata: Dict[str, Any]        # Detector-specific data
```

### Extended EvidencePacket
```python
@dataclass
class EvidencePacket:
    # ... existing fields ...
    
    # NEW: Raw person data for behavior analysis
    tracked_persons: List[TrackedPerson] = field(default_factory=list)
    
    # NEW: Behavior evidence from detectors
    behavior_evidence: List[BehaviorEvidence] = field(default_factory=list)
```

### Final Data Flow Diagram
```
Camera
    │
    ▼
MoveNet
    │
    ▼
StableID
    │
    ▼
TrackedPerson[]
    ├──────────────► YOLO
    │
    └──────────────► Concealment Detector
                         │
                         ▼
                    BehaviorEvidence
                         │
                         ▼
                  Decision Engine
                         │
                         ▼
                Incident Manager
```

---

## 7. Implementation Sequencing (Revised)

### Phase 0: StableID Extraction
**Purpose:** Extract the existing hip-centroid matching logic into a reusable module  
**Risk:** LOW  
**Changes:** Create monitor_app/tracking/stable_id.py and preserve behavior at first

### Phase 1: TrackedPerson Model
**Purpose:** Define a canonical person representation for pose and behavior analysis  
**Risk:** LOW  
**Changes:** Add TrackedPerson in evidence.py or a small shared model module

### Phase 2: Wire MoveNet → StableID → TrackedPerson
**Purpose:** Create TrackedPerson objects immediately after MoveNet inference and before downstream logic  
**Risk:** MEDIUM  
**Changes:** ai_engine.py to preserve keypoints and pass them into TrackedPerson objects

### Phase 3: Concealment Detector
**Purpose:** Implement the new feature using TrackedPerson  
**Risk:** MEDIUM  
**Changes:** Add monitor_app/concealment_detector.py

### Phase 4: BehaviorEvidence Integration
**Purpose:** Feed detector output into the decision pipeline  
**Risk:** LOW  
**Changes:** Add BehaviorEvidence to evidence.py and consume it in decision.py

---

## 8. Critical Questions Answered

### Q1: Where is canonical person representation?
**A:** Currently in `detected_people` dict in ai_engine.py (lost after line 431).  
**Action:** Create TrackedPerson model in Phase 0, preserve through entire pipeline.

### Q2: Where do MoveNet keypoints first become structured?
**A:** `person = kpts[i, :51].reshape(17, 3)` in ai_engine.py line 404.  
**Action:** Wrap in TrackedPerson immediately, preserve keypoints through EvidencePacket.

### Q3: Pose lifetime - trace complete flow?
**A:** 
```
ai_engine.py (line 404)          ← Keypoints extracted
ai_engine.py (line 418)          ← Placed in detected_people dict
ai_engine.py (line 427)          ← StableID added
ai_engine.py (line 431)          ← LOST (only summary kept)
central_inference.py (line 180)  ← No keypoints
decision.py (evaluate_trigger)   ← No keypoints
alert_manager.py                 ← No keypoints
incident_record.py               ← No keypoints
```

### Q4: Best integration point for StableID?
**A:** Immediately after MoveNet inference, in the perception stage, before behavior analysis begins.  
**Rationale:**
- StableID depends on pose output
- It should be close to the pose extraction stage
- It should be reusable by future detectors
- It should not be owned by central_inference orchestration

### Q5: Cleanest input for behavior detectors?
**A:** `TrackedPerson` object containing all necessary pose data.  
**Avoids:** Multiple arguments, repeated lookups, data duplication.

---

## 9. Refactored Implementation Sequence

### Phase 0: StableID Extraction
- [ ] Create monitor_app/tracking/stable_id.py
- [ ] Extract the current hip-centroid matching logic from ai_engine
- [ ] Make max_distance + grace_period configurable

### Phase 1: TrackedPerson Model
- [ ] Create TrackedPerson dataclass
- [ ] Preserve raw keypoints and metadata

### Phase 2: MoveNet to TrackedPerson Wiring
- [ ] Modify ai_engine.py to create TrackedPerson objects after MoveNet
- [ ] Keep existing behavior classification intact

### Phase 3: Concealment Detector
- [ ] Create concealment_detector.py
- [ ] Implement one-hand occlusion analysis using TrackedPerson

### Phase 4: BehaviorEvidence Integration
- [ ] Add BehaviorEvidence to evidence.py
- [ ] Update decision.py to consume it

### Phase 5: Validation
- [ ] Verify existing aggression and fast movement alerts remain intact
- [ ] Validate the new concealment path end-to-end

---

## Key Architectural Insights

### Insight 1: StableID Already Exists (Partially)
The implementation had hip-centroid tracking and stable IDs partially implemented but:
- Hidden inside ai_engine.py
- Not exposed for reuse
- Not configurable
- Coupled to concealment state
- **Should be extracted and made reusable**

### Insight 2: KeyPoint Loss is Critical Bottleneck
MoveNet produces full keypoint data, but:
- Data is discarded after behavior classification
- Future detectors have no access to pose
- This blocks implementation of ANY new behavior module
- **Keypoints must flow through EvidencePacket**

### Insight 3: TrackedPerson is Missing Abstraction
Current pipeline has no unified representation of a detected person:
- Raw tensors → dicts → flattened summaries
- Each behavior detector must parse differently
- No standard interface for future modules
- **TrackedPerson solves this problem**

### Insight 4: Orchestration Should Move to central_inference
Current flow has behavior logic scattered:
- Pose extraction in ai_engine
- Behavior classification in ai_engine
- StableID in ai_engine
- But orchestration and future detectors have nowhere to live
- **central_inference.py should orchestrate all behavior modules**

---

## Revised Risk Assessment

| Phase | Task | OLD Risk | NEW Risk | Why |
|-------|------|----------|----------|-----|
| 0 | TrackedPerson | N/A | LOW | New dataclass, no breaking changes |
| 1 | Extract poses | MEDIUM | LOW | ai_engine still produces same res dict, just adds tracking_persons |
| 1.5 | StableID | MEDIUM | LOW | Extracting existing code, not new logic |
| 2 | Central orchestration | MEDIUM | MEDIUM | Adds behavior loop but isolated |
| 3 | BehaviorEvidence | LOW | LOW | Already approved |
| 4 | Concealment | MEDIUM | LOW | Now has full pose access |
| 5+ | Testing | MEDIUM | MEDIUM | Regression tests essential |

---

## Definition of the Revised First Phase

### Must Complete Before the Concealment Detector

#### 0.1 TrackedPerson Dataclass
```python
@dataclass
class TrackedPerson:
    stable_id: int
    raw_person_id: int
    camera_id: str
    keypoints: np.ndarray
    bbox: Optional[Tuple[int, int, int, int]] = None
    hip_centroid: Optional[Tuple[float, float]] = None
    confidence: float = 0.0
    frame_number: int = 0
    timestamp: float = 0.0
```

#### 0.2 StableID Tracker Module
```python
class StableIDTracker:
    def __init__(self, max_distance: float, grace_period: int):
        ...

    def update(self, persons: List[TrackedPerson], frame_number: int) -> List[TrackedPerson]:
        ...
```

#### 0.3 EvidencePacket Extension
```python
@dataclass
class EvidencePacket:
    # existing fields...
    tracked_persons: List[TrackedPerson] = field(default_factory=list)
    behavior_evidence: List[BehaviorEvidence] = field(default_factory=list)
```

#### 0.4 Validation
- [ ] TrackedPerson importable
- [ ] EvidencePacket backward compatible
- [ ] to_dict()/from_dict() handle new fields
- [ ] StableID tracker returns consistent IDs across short occlusions

---

## Conclusion

The architecture analysis reveals:

1. **MoveNet produces poses, but they're lost** → Phase 0: Define TrackedPerson
2. **StableID exists but is hidden** → Phase 1.5: Extract to reusable module
3. **Behavior modules need unified input** → Phase 0: Define BehaviorDetector interface
4. **Orchestration point missing** → Phase 2: central_inference.py becomes orchestrator
5. **Evidence flow is incomplete** → Phase 3: Add BehaviorEvidence to packet

**DO NOT BEGIN PHASE 1 UNTIL PHASE 0 IS COMPLETE.**

Phase 0 is the foundation that unblocks all future behavior analysis.

---

## Next Steps

1. **Approve Phase 0 requirements**
2. **Implement TrackedPerson + BehaviorDetector + EvidencePacket extension**
3. **Validate no breaking changes**
4. **Then proceed to Phase 1 (Extract Poses from ai_engine)**

**Estimated time for Phase 0:** 1-2 hours  
**Blocking:** Everything else  
**Value:** Enables entire future behavior analysis framework
