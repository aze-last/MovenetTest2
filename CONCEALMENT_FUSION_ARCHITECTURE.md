# Concealment Detection — Multi-Evidence Fusion Architecture

**Status:** Planning (no implementation yet)  
**Date:** 2026-07-02  
**Authority:** GEMINI.md, Architecture Guardian principles  
**Verdict:** Fuse multiple evidence sources. Do not replace MoveNet with YOLO.

---

## Executive Summary

The current concealment pipeline relies primarily on MoveNet wrist keypoint visibility within a single camera. That approach cannot reliably distinguish **camera-angle occlusion** from **intentional concealment**.

The correct architecture is a **three-tier evidence stack**:

1. **Per-camera observation** — combine MoveNet + YOLO into structured hand states
2. **Multi-camera fusion** — resolve Unknown vs Concealed vs Visible before alerting
3. **Temporal behavior + decision** — sustained fused state before incident trigger

MoveNet stays. A dedicated YOLO concealed-hand detector is added later as a **secondary semantic channel**, not a replacement.

---

## 0. Task Definition

### Problem Statement

CellWatch currently infers suspicious hand concealment from **MoveNet wrist keypoint visibility on a single camera**. Side-view occlusion, motion blur, and benign poses are indistinguishable from intentional concealment. The Decision Engine can alert without corroboration from other cameras.

### Task

Design and implement a **multi-evidence, multi-camera concealment pipeline** that:

1. Keeps the existing MoveNet pipeline intact
2. Adds per-camera hand states: **Visible**, **Concealed**, **Occluded/Unknown**
3. Fuses observations across all cameras in a zone **before** concealment reaches the Behavior Engine and Decision Engine
4. Never confirms concealment from a single side-view camera alone
5. Makes all confidence thresholds configurable via `config.yaml`
6. Preserves the event-driven, loosely coupled CellWatch architecture

### Success Criteria

| Criterion | Measurable outcome |
|-----------|-------------------|
| False positive reduction | Side-profile walking no longer triggers concealment alerts |
| Multi-camera veto | If any camera shows wrist Visible, fused state is Visible (no alert) |
| Multi-camera support | Concealment alert requires ≥ `min_supporting_cameras` (default 2) frontal/supporting views |
| Single side camera | Side-view-only Concealed → fused Unknown, never incident |
| Config-driven | Zero hardcoded thresholds in detector/fusion code |
| Architecture compliance | No UI blocking, no direct DB writes from detectors, event bus preserved |
| Regression safety | Existing aggression, fast movement, knife, cellphone detection unchanged |
| Real-time budget | Pipeline remains usable on RTX 2050 / 4 cameras / 20–30 FPS target |

### Scope

**In scope**

- Per-camera `HandObservation` classifier (MoveNet first, YOLO later)
- `ConcealmentFusionEngine` for zone-level multi-camera fusion
- Refactor `ConcealmentDetector` to consume fused state
- Decision Engine gate for fusion-confirmed concealment
- `config.yaml` schema for all concealment/fusion/behavior params
- Unit and integration tests for fusion logic
- Throttled logging on state transitions

**Out of scope (this task)**

- Full cross-camera ReID
- Replacing MoveNet with YOLO
- Modifying aggression / fast movement detectors
- UI redesign
- Training the YOLO concealed-hand model (Phase 5 integrates inference only; dataset/training is separate)

### Agent Ownership

| Agent | Owns |
|-------|------|
| Architecture Guardian | Pipeline order, module boundaries, fusion placement |
| MoveNet Specialist | `hand_observation.py`, MoveNet signal extraction |
| YOLO Specialist | Phase 5 — `concealed_hand.pt` loading and inference |
| Behavior Architect | `behaviors/concealment_detector.py` refactor |
| Logic Reviewer | `central_inference.py` reorder, `decision.py` gating |
| Testing & Validation Engineer | Test suite, regression checks |
| Performance Engineer | GPU budget, motion gating for hand YOLO |

### Default Design Assumptions (Pending Approval)

Until operator confirms otherwise, implementation assumes:

- All 4 cameras belong to **one zone** (`zones.default`)
- Ship **Phases 0–4 first** (MoveNet-only fusion skeleton)
- `min_supporting_cameras: 2` (conservative)
- `single_camera_insufficient: true`
- Feature flag `concealment.enabled: true` with ability to disable and fall back to legacy path during rollout

---

## Table of Contents

0. [Task Definition](#0-task-definition)
1. [Current State](#1-current-state)
2. [Computer Vision Analysis](#2-computer-vision-analysis)
3. [Architecture Decision](#3-architecture-decision)
4. [Proposed Pipeline](#4-proposed-pipeline)
5. [Per-Camera Observation Layer](#5-per-camera-observation-layer)
6. [Multi-Camera Fusion Layer](#6-multi-camera-fusion-layer)
7. [Behavior & Decision Integration](#7-behavior--decision-integration)
8. [Configuration Schema](#8-configuration-schema)
9. [Performance Strategy](#9-performance-strategy)
10. [Risks & Mitigations](#10-risks--mitigations)
11. [Implementation Plan (Summary)](#11-implementation-plan-summary)
12. [Implementation Plan (Detailed)](#12-implementation-plan-detailed)
13. [Definition of Done](#13-definition-of-done)
14. [Explicit Non-Goals](#14-explicit-non-goals)
15. [Open Design Choices](#15-open-design-choices)

---

## 1. Current State

### Pipeline Today

```
Camera Thread
    ↓
Motion Gate
    ↓
Central Inference Worker
    ├─ MoveNet (CPU)
    └─ YOLO (GPU — knife/cellphone only)
    ↓
Behavior Engine (per camera)
    └─ ConcealmentDetector — wrist occlusion + yaw gate
    ↓
EvidencePacket + behavior_evidence
    ↓
CameraFusion — telemetry cache only (no fusion logic)
    ↓
DecisionEngine — per-camera packet
    ↓
EventBus → DECISION_TRIGGER
    ↓
AlertManager — per-camera IncidentState
```

### Active Modules

| Module | Role | Multi-camera? |
|--------|------|---------------|
| `monitor_app/behaviors/concealment_detector.py` | Sustained one-wrist-missing + yaw gate | No — per `(camera_id, stable_id)` |
| `monitor_app/concealment_detector.py` | Legacy simple detector | Unused in active registry |
| `monitor_app/fusion.py` | Stores latest `EvidencePacket` per camera | No fusion logic, no ReID |
| `monitor_app/decision.py` | Triggers on `packet.behavior_evidence` | Single-camera packet |
| `monitor_app/alert_manager.py` | Hysteresis state machine | Per-camera incidents |

### Current Concealment Logic

The active detector (`behaviors/concealment_detector.py`):

- Monitors left/right wrist confidence independently
- Requires exactly one wrist below `wrist_confidence_threshold`
- Applies a yaw gate (`shoulder_width / torso_height`) to suppress side-profile views
- Accumulates `duration_frames` before emitting `BehaviorEvidence`
- Applies `cooldown_frames` after alert

Configurable via `get_config("behavior", "concealment", {})` — but `config.yaml` does not yet define these keys.

### Architectural Gaps

1. **Single-camera sufficiency** — concealment can fire from one camera with no cross-camera veto
2. **Fusion is a placeholder** — `CameraFusion` explicitly does not perform ReID or cross-camera reasoning
3. **YOLO is contraband-only** — `best.pt` maps `{knife, cellphone}`; no concealed-hand class
4. **Pipeline order mismatch** — GEMINI.md specifies `Heavy AI → Fusion → Decision (via Behavior Engine)`; code runs `Behavior Engine → Fusion → Decision`, and fusion does not influence concealment
5. **Yaw gate is a single-camera proxy** — cannot distinguish viewpoint occlusion from intentional concealment

---

## 2. Computer Vision Analysis

### MoveNet Wrist Reasoning

**Strengths**

- Cheap (CPU), already in pipeline
- Temporal sustain (`duration_frames`, cooldown) reduces single-frame noise
- Yaw gate suppresses many side-profile false positives
- "Exactly one wrist missing" is a reasonable suspiciousness heuristic

**Limits**

| Phenomenon | MoveNet signal | True state |
|------------|----------------|------------|
| Side-view camera | Wrist below confidence | Occluded by viewpoint |
| Hand in pocket (frontal) | Wrist missing | Concealed |
| Hand behind back | Wrist missing | Concealed or benign |
| Motion blur / low resolution | Wrist missing | Unknown |
| Arms crossed | One wrist occluded | Often benign |
| Person at frame edge | Keypoints drop | Unknown |

**Core principle:** Missing keypoints measure **observability**, not **intent**. Wrist confidence is a visibility proxy, not a concealment classifier.

### Dedicated YOLO Concealed-Hand Detector

**Adds**

- Semantic classes: `hand_in_pocket`, `hand_waistband`, `hand_behind_clothing`, etc.
- Spatial localization (bbox) for evidence snapshots
- Signal when pose fails but appearance is discriminative

**Risks**

- Jail-domain poses (sitting, leaning, blankets, uniform folds) → false positives
- Extra GPU cost on RTX 2050 4GB (4 cameras × 20–30 FPS target)
- Requires curated dataset from actual cell layouts and lighting
- Must not duplicate MoveNet (pose) or contraband YOLO (objects)

**Role:** MoveNet answers *"can we see the wrist?"*; YOLO answers *"does the visible region look like concealment?"*

---

## 3. Architecture Decision

| Approach | False positives | Real-time fit | Architecture fit |
|----------|-----------------|---------------|------------------|
| MoveNet only (current) | High on single-cam occlusion | Good | Partial |
| YOLO only | High on benign adjustments | Moderate GPU | Violates ownership split |
| **Fused multi-evidence + multi-camera** | Lowest | Moderate (with gating) | **Best** |

**Decision:** Fuse evidence sources. Do not replace MoveNet. Add YOLO concealed-hand as optional secondary evidence in a later phase.

---

## 4. Proposed Pipeline

Aligned with GEMINI.md event-driven, loosely coupled CellWatch architecture.

```
Camera Capture
    ↓
Motion Gate
    ↓
Central Inference Queue
    ├─ MoveNet (CPU)
    ├─ YOLO Contraband (existing)
    └─ YOLO Concealed-Hand (NEW, optional, phased)
    ↓
StableID Tracker
    ↓
Hand Observation Classifier (NEW)
    → HandObservation per (camera, person, hand)
    ↓
CameraFusion — extended to store observations
    ↓
ConcealmentFusionEngine (NEW)
    → FusedConcealmentObservation per (zone, subject, hand)
    ↓
Behavior Engine
    → Concealment uses fused state; other behaviors unchanged
    ↓
Decision Engine
    → Concealment gated on fusion-confirmed evidence
    ↓
EventBus → AlertManager / Recorder
```

### Module Ownership

| Module | Owner | Responsibility |
|--------|-------|----------------|
| `ai_engine.py` | MoveNet + YOLO specialists | Raw inference only; emit detections, not concealment decisions |
| `hand_observation.py` *(new)* | MoveNet specialist + fusion | Per-camera state: Visible / Concealed / Unknown |
| `fusion/concealment_fusion.py` *(new)* | Architecture reviewer | Multi-camera evidence fusion |
| `behaviors/concealment_detector.py` | Behavior architect | Temporal sustain on **fused** state only |
| `decision.py` | Logic reviewer | Gate concealment on `fusion_confirmed` |
| `config.yaml` | Config separation | All thresholds (engineering params) |

---

## 5. Per-Camera Observation Layer

Each camera independently produces one of three states **before** fusion:

| State | Meaning |
|-------|---------|
| **Visible** | Wrist observable; concealment disproven for this viewpoint |
| **Concealed** | Supported evidence of intentional hiding from this viewpoint |
| **Unknown** | Occluded by camera angle, low confidence, or ambiguous — not evidence |

### Proposed Data Model

```python
class HandSide(Enum):
    LEFT = "left"
    RIGHT = "right"

class HandObservationState(Enum):
    VISIBLE = "visible"
    CONCEALED = "concealed"
    UNKNOWN = "unknown"

@dataclass
class HandObservation:
    camera_id: str
    stable_id: int
    hand: HandSide
    state: HandObservationState
    confidence: float
    timestamp: float
    frame_index: int
    sources: dict            # movenet, yolo, yaw_angle, etc.
    view_quality: float      # frontalness / observability score
```

### Per-Camera Classification Rules

| State | Conditions (all thresholds configurable) |
|-------|----------------------------------------|
| **Visible** | Wrist conf ≥ `wrist_visible_threshold` OR YOLO shows no concealment class in hand ROI |
| **Concealed** | Frontal view (`view_quality` ≥ `min_frontal_quality`) AND (wrist conf < `wrist_missing_threshold` OR YOLO concealment conf ≥ `yolo_concealed_threshold`) AND not both-wrists-missing |
| **Unknown** | Side/high-yaw view, both wrists missing, low pose confidence, edge-of-frame, or conflicting MoveNet vs YOLO |

### Local Score Fusion (per camera, per hand)

```
local_score_concealed = (
    movenet_weight * movenet_conceal_signal +
    yolo_weight       * yolo_conceal_signal
) / (movenet_weight + yolo_weight)
```

- `movenet_conceal_signal` — sustained one-wrist-missing under frontal gate (normalized 0–1)
- `yolo_conceal_signal` — max confidence across concealment classes in person ROI

Side-view cameras should output **Unknown**, not Concealed, even if YOLO fires (down-weight via `view_quality`).

---

## 6. Multi-Camera Fusion Layer

### Core Rule

> The Decision Engine must never treat a single side-view camera as sufficient evidence.

A hand may simply be occluded from that viewpoint. Side cameras contribute **Unknown**, not **Concealed**.

### Fusion Logic

| Camera observations | Fused result |
|---------------------|--------------|
| Cam A: Concealed, Cam B: **Visible** | **Visible** (veto — disproves concealment) |
| Cam A: Concealed, Cam B: Unknown, Cam C: Unknown | **Unknown** (insufficient support) |
| Cam A: Concealed (frontal), Cam B: Concealed (frontal) | **Concealed** (supported) |
| Cam A: Concealed, Cam B: Concealed, Cam C: Visible | **Visible** (one veto sufficient) |
| Only side camera: Concealed | **Unknown** (side view never confirms) |
| Single frontal: Concealed, no other cameras | **Unknown** if `single_camera_insufficient: true` |

### Cross-Camera Association (Lightweight, No Full ReID)

Per GEMINI.md Rule 6, full ReID is out of scope. Use **cell-zone fusion**:

```yaml
zones:
  cell_01:
    cameras: ["cam_front", "cam_side_a", "cam_side_b", "cam_overhead"]
    max_occupancy_for_auto_merge: 2
```

Association strategy:

1. Group observations by `zone_id` from config
2. If total persons across zone cameras ≤ `max_occupancy_for_auto_merge`, merge using normalized hip-position buckets + temporal continuity
3. If occupancy is ambiguous → conservative: do not emit fused Concealed

### Fused Output

```python
@dataclass
class FusedConcealmentObservation:
    zone_id: str
    subject_slot: int
    hand: HandSide
    fused_state: HandObservationState
    fused_confidence: float
    supporting_cameras: list[str]
    vetoing_cameras: list[str]
    unknown_cameras: list[str]
```

Only `fused_state == CONCEALED` with `fused_confidence >= min_fused_confidence` feeds the Behavior Engine sustain counter.

---

## 7. Behavior & Decision Integration

### Behavior Engine

- **Aggression / fast movement** — remain per-camera (single view often sufficient)
- **Concealment** — refactor to consume `FusedConcealmentObservation`, not raw wrist keypoints
- Sustain counter runs on fused state (`duration_frames` / `cooldown_frames` from config)
- Emit `BehaviorEvidence` only when fused concealment is sustained across time

### Decision Engine

- Concealment incidents require `BehaviorEvidence` with `metadata["fusion_confirmed"] = true`
- Contraband (knife/phone) remains single-camera — object visibility is local
- `evaluate_trigger()` unchanged for non-concealment paths

### Event Bus (Loose Coupling Preserved)

New diagnostic events (throttled):

| Event | Level | When |
|-------|-------|------|
| `HAND_OBSERVATION` | DEBUG | Per-camera observation emitted |
| `CONCEALMENT_FUSED` | INFO | Fused state transition |
| `DECISION_TRIGGER` | INFO | Existing — unchanged |
| `INCIDENT_START` | INFO | Existing — unchanged |

---

## 8. Configuration Schema

All engineering thresholds in `config.yaml` under `concealment:` (GEMINI Rule 4 — no hardcoded values).

```yaml
concealment:
  enabled: true

  per_camera:
    wrist_visible_threshold: 0.35
    wrist_missing_threshold: 0.20
    yaw_gate_threshold: 30.0
    min_pose_confidence: 0.25
    movenet_weight: 0.45
    yolo_weight: 0.55
    yolo_concealed_threshold: 0.40
    yolo_inference_interval: 2        # run every N motion frames for GPU budget

  fusion:
    single_camera_insufficient: true
    side_view_never_confirms: true
    min_supporting_cameras: 2
    min_frontal_supporting_cameras: 1
    min_frontal_quality: 0.60
    min_fused_confidence: 0.75
    veto_visible_threshold: 0.70
    unknown_is_neutral: true          # Unknown does not support OR deny
    association_max_hip_distance_norm: 0.15
    fusion_stale_ms: 500

  behavior:
    duration_frames: 27
    cooldown_frames: 60
    decay_frames: 1

  zones:
    default:
      cameras: ["0", "1", "2", "3"]
      max_occupancy_for_auto_merge: 2
```

Operator sensitivity profiles (`app_state.db`) map to preset bundles of these values.

---

## 9. Performance Strategy

Target hardware: ASUS TUF, RTX 2050 4GB, 4 cameras, 20–30 FPS.

| Technique | Purpose |
|-----------|---------|
| Motion gate on YOLO hand model | Skip when scene is static |
| `yolo_inference_interval` | Run hand YOLO every Nth AI frame |
| ROI crop from person bbox | Smaller input → faster inference |
| Separate small model (`concealed_hand.pt`) | Do not bloat contraband `best.pt` |
| Fusion on CPU | Lightweight dict logic, no GPU |
| Stale observation expiry | `fusion_stale_ms` prevents ghost evidence |

Target budget: MoveNet + contraband YOLO unchanged; hand YOLO adds ~5–15 ms per active frame when gated.

---

## 10. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Cross-camera identity mismatch | High | Zone-level fusion + occupancy cap; conservative default |
| YOLO false positives (adjusting clothes) | High | Multi-camera + temporal sustain + veto |
| GPU VRAM pressure | Medium | Motion gate, interval inference, ROI crops |
| Pipeline order change breaks tests | Medium | Phased rollout; feature flag `concealment.enabled` |
| Legacy `concealment_detector.py` confusion | Low | Deprecate in implementation phase |
| Single frontal camera in small cells | Medium | Config override with `require_yolo_confirmation: true` |

---

## 11. Implementation Plan (Summary)

| Phase | Name | Deliverable | Risk | YOLO? | Est. effort |
|-------|------|-------------|------|-------|-------------|
| **0** | Foundation | Config + data models | Low | No | 0.5 day |
| **1** | Per-camera observations | `hand_observation.py` | Low | No | 1 day |
| **2** | Multi-camera fusion | `ConcealmentFusionEngine` | Medium | No | 1.5 days |
| **3** | Pipeline reorder | `central_inference.py` wiring | Medium | No | 1 day |
| **4** | Behavior refactor | Fused `ConcealmentDetector` | Medium | No | 1 day |
| **5** | Decision gating | `decision.py` fusion check | Low | No | 0.5 day |
| **6** | YOLO integration | Hand model in `ai_engine.py` | High | Yes | 2 days |
| **7** | Tests & validation | Full regression suite | Medium | Partial | 1.5 days |
| **8** | Field validation | Recorded session review | — | — | 1 day |

**Milestone A (Phases 0–5):** MoveNet-only multi-camera fusion — shippable, fewer false positives.  
**Milestone B (Phases 6–8):** YOLO concealed-hand channel + field tuning.

---

## 12. Implementation Plan (Detailed)

### Phase 0 — Foundation (Config + Data Models)

**Goal:** Establish shared types and configuration before any pipeline changes.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 0.1 | Add `HandSide`, `HandObservationState` enums | `monitor_app/evidence.py` | Logic Reviewer |
| 0.2 | Add `HandObservation` dataclass | `monitor_app/evidence.py` | Logic Reviewer |
| 0.3 | Add `FusedConcealmentObservation` dataclass | `monitor_app/evidence.py` | Logic Reviewer |
| 0.4 | Add `concealment:` block to config | `config.yaml` | Architecture Guardian |
| 0.5 | Migrate existing concealment keys from `behavior.concealment` to `concealment.behavior` | `config.yaml`, `concealment_detector.py` | Behavior Architect |
| 0.6 | Add `get_concealment_config()` helper | `monitor_app/config.py` | Logic Reviewer |

**Validation**

- [ ] Config loads without error
- [ ] All thresholds read from config; no magic numbers in new code
- [ ] Existing tests still pass (no pipeline change yet)

---

### Phase 1 — Per-Camera Hand Observation Classifier

**Goal:** Each camera independently classifies each tracked person's left/right hand as Visible, Concealed, or Unknown.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 1.1 | Create `HandObservationClassifier` class | `monitor_app/hand_observation.py` *(new)* | MoveNet Specialist |
| 1.2 | Port yaw-angle / view-quality logic from `ConcealmentDetector` | `hand_observation.py` | MoveNet Specialist |
| 1.3 | Implement per-hand state rules (Visible / Concealed / Unknown) | `hand_observation.py` | MoveNet Specialist |
| 1.4 | Accept optional YOLO concealment detections (stub empty until Phase 6) | `hand_observation.py` | MoveNet Specialist |
| 1.5 | Add `classify_person(person) -> list[HandObservation]` | `hand_observation.py` | MoveNet Specialist |
| 1.6 | Unit tests: frontal concealed, side unknown, both wrists missing, visible veto | `tests/test_hand_observation.py` *(new)* | Testing Engineer |

**Key logic (MoveNet-only path)**

```
for each hand (left, right):
  if yaw_angle >= yaw_gate_threshold:
    state = UNKNOWN  (side view — never CONCEALED)
  elif wrist_conf >= wrist_visible_threshold:
    state = VISIBLE
  elif other_wrist also missing:
    state = UNKNOWN  (ambiguous)
  elif view_quality >= min_frontal_quality:
    state = CONCEALED
  else:
    state = UNKNOWN
```

**Validation**

- [ ] Side-profile person → both hands Unknown
- [ ] Frontal, one wrist missing → that hand Concealed, other Visible
- [ ] Frontal, both wrists visible → both Visible
- [ ] All thresholds driven by config

---

### Phase 2 — Multi-Camera Concealment Fusion Engine

**Goal:** Combine per-camera observations into zone-level fused states with veto and support rules.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 2.1 | Create `ConcealmentFusionEngine` | `monitor_app/fusion/concealment_fusion.py` *(new)* | Architecture Guardian |
| 2.2 | Add `fusion/__init__.py` package | `monitor_app/fusion/` | Architecture Guardian |
| 2.3 | Extend `CameraFusion` to store latest `HandObservation[]` per camera | `monitor_app/fusion.py` | Logic Reviewer |
| 2.4 | Implement zone grouping from `concealment.zones` config | `concealment_fusion.py` | Architecture Guardian |
| 2.5 | Implement lightweight cross-camera subject association (hip bucket + occupancy cap) | `concealment_fusion.py` | Architecture Guardian |
| 2.6 | Implement fusion rules: veto (Visible wins), support count, side-never-confirms | `concealment_fusion.py` | Architecture Guardian |
| 2.7 | Expire stale observations via `fusion_stale_ms` | `concealment_fusion.py` | Logic Reviewer |
| 2.8 | Thread-safe singleton `get_concealment_fusion()` | `concealment_fusion.py` | Logic Reviewer |
| 2.9 | Unit tests: veto, insufficient support, side-only suppression, 2-cam confirm | `tests/test_concealment_fusion.py` *(new)* | Testing Engineer |

**Fusion algorithm (pseudocode)**

```
for each zone:
  observations = collect fresh HandObservation from all zone cameras
  subjects = associate_by_hip_bucket(observations)

  for each subject, each hand:
    visible_cams = [cam where state == VISIBLE]
    concealed_cams = [cam where state == CONCEALED and view_quality >= min_frontal_quality]
    unknown_cams = [cam where state == UNKNOWN]

    if visible_cams:
      fused = VISIBLE  # veto
    elif len(concealed_cams) >= min_supporting_cameras:
      fused = CONCEALED
    elif single_camera_insufficient and len(concealed_cams) < min_supporting_cameras:
      fused = UNKNOWN
    else:
      fused = UNKNOWN
```

**Validation**

- [ ] Cam A Concealed + Cam B Visible → fused Visible
- [ ] Cam A Concealed + Cam B Unknown → fused Unknown (insufficient)
- [ ] Cam A Concealed (frontal) + Cam B Concealed (frontal) → fused Concealed
- [ ] Only side camera reports Concealed → fused Unknown
- [ ] Stale observations ignored after `fusion_stale_ms`

---

### Phase 3 — Pipeline Reorder in Central Inference

**Goal:** Align runtime order with GEMINI.md: observations → fusion → behavior → decision.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 3.1 | After StableID + body metrics: run `HandObservationClassifier` per person | `monitor_app/central_inference.py` | Logic Reviewer |
| 3.2 | Push observations to `CameraFusion.update_observations()` | `central_inference.py`, `fusion.py` | Logic Reviewer |
| 3.3 | Run `ConcealmentFusionEngine.fuse()` and attach results to packet | `central_inference.py` | Logic Reviewer |
| 3.4 | Add `fused_concealment: list[FusedConcealmentObservation]` to `EvidencePacket` | `monitor_app/evidence.py` | Logic Reviewer |
| 3.5 | Move concealment out of pre-fusion `BehaviorEngine` path (keep StableID + metrics in BehaviorEngine) | `monitor_app/behaviors/engine.py` | Behavior Architect |
| 3.6 | Publish throttled `HAND_OBSERVATION` / `CONCEALMENT_FUSED` events | `monitor_app/events.py` | Logic Reviewer |
| 3.7 | Guard entire new path behind `concealment.enabled` flag | `central_inference.py` | Logic Reviewer |

**New pipeline order in `_worker_loop`**

```
1. ai_engine.process_frame()          # MoveNet + YOLO contraband
2. BehaviorEngine (StableID + metrics)  # no concealment yet
3. HandObservationClassifier          # per-camera states
4. CameraFusion.update_observations()
5. ConcealmentFusionEngine.fuse()       # multi-camera
6. ConcealmentDetector (fused input)  # temporal sustain
7. CameraFusion.update(packet)          # existing telemetry cache
8. DecisionEngine.evaluate_trigger()
9. EventBus.publish(DECISION_TRIGGER)
```

**Validation**

- [ ] Pipeline order matches diagram
- [ ] `concealment.enabled: false` restores legacy single-camera path
- [ ] No UI thread blocking
- [ ] Thread safety on fusion singleton

---

### Phase 4 — Refactor ConcealmentDetector (Fused Input)

**Goal:** Concealment behavior operates on fused multi-camera state, not raw keypoints.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 4.1 | Change `ConcealmentDetector.detect()` to accept `FusedConcealmentObservation` | `behaviors/concealment_detector.py` | Behavior Architect |
| 4.2 | Sustain counter increments only when `fused_state == CONCEALED` | `concealment_detector.py` | Behavior Architect |
| 4.3 | Reset/decay counter when fused Visible or Unknown | `concealment_detector.py` | Behavior Architect |
| 4.4 | Emit `BehaviorEvidence` with `metadata["fusion_confirmed"] = True` and supporting camera list | `concealment_detector.py` | Behavior Architect |
| 4.5 | Remove direct wrist/yaw logic from detector (moved to `hand_observation.py`) | `concealment_detector.py` | Behavior Architect |
| 4.6 | Update `behaviors/registry.py` if detector interface changes | `behaviors/registry.py` | Behavior Architect |
| 4.7 | Update existing concealment tests for fused input | `tests/test_concealment_tracking.py` | Testing Engineer |
| 4.8 | Mark `monitor_app/concealment_detector.py` as deprecated | `concealment_detector.py` | Behavior Architect |

**Validation**

- [ ] No alert until fused Concealed sustained for `duration_frames`
- [ ] Cooldown still works
- [ ] `BehaviorEvidence.supporting_metrics` includes fusion metadata
- [ ] Existing yaw/occlusion unit tests moved to `test_hand_observation.py`

---

### Phase 5 — Decision Engine Gating

**Goal:** Decision Engine rejects unconcealed-fusion evidence; contraband path unchanged.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 5.1 | In `evaluate_trigger()`, require `fusion_confirmed` for concealment evidence | `monitor_app/decision.py` | Logic Reviewer |
| 5.2 | In `generate_incident_record()`, include fusion metadata in notes | `decision.py` | Incident Analyst |
| 5.3 | Filter concealment from `behavior_evidence` if fusion flag missing | `decision.py` | Logic Reviewer |
| 5.4 | Integration test: end-to-end packet → DECISION_TRIGGER for fused concealment | `tests/test_concealment_fusion_e2e.py` *(new)* | Testing Engineer |

**Validation**

- [ ] Single-camera unconcealed-fusion evidence does not trigger incident
- [ ] Knife/cellphone/aggression still trigger normally
- [ ] Incident notes list supporting cameras

---

### Phase 6 — YOLO Concealed-Hand Integration (Milestone B)

**Goal:** Add semantic concealment signal without replacing MoveNet.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 6.1 | Add `concealed_hand.pt` model path to config | `config.yaml` | YOLO Specialist |
| 6.2 | Load second YOLO model in `ai_engine.py` (separate from contraband `best.pt`) | `ai_engine.py` | YOLO Specialist |
| 6.3 | Run hand YOLO on person ROI crop, gated by motion + `yolo_inference_interval` | `ai_engine.py` | YOLO Specialist + Performance |
| 6.4 | Emit `detections.concealed_hand: [...]` in frame result dict | `ai_engine.py` | YOLO Specialist |
| 6.5 | Wire YOLO output into `HandObservationClassifier` | `hand_observation.py` | MoveNet Specialist |
| 6.6 | Apply `movenet_weight` / `yolo_weight` local score fusion | `hand_observation.py` | MoveNet Specialist |
| 6.7 | Benchmark GPU memory and FPS on target laptop | manual / `performance.py` | Performance Engineer |

**Validation**

- [ ] Hand YOLO does not break contraband YOLO
- [ ] VRAM stays within 4 GB budget
- [ ] Motion gate + interval keeps FPS acceptable
- [ ] YOLO-only signal on side view still produces Unknown at fusion layer

---

### Phase 7 — Tests & Regression

**Goal:** Prove correctness and no regression across the full system.

**Tasks**

| # | Task | File(s) | Owner |
|---|------|---------|-------|
| 7.1 | `test_hand_observation.py` — per-camera state matrix | tests | Testing Engineer |
| 7.2 | `test_concealment_fusion.py` — multi-camera rules | tests | Testing Engineer |
| 7.3 | `test_concealment_tracking.py` — update for fused detector | tests | Testing Engineer |
| 7.4 | `test_concealment_fusion_e2e.py` — pipeline integration | tests | Testing Engineer |
| 7.5 | Config sweep test — verify no hardcoded thresholds | tests | Testing Engineer |
| 7.6 | Run full `pytest` suite | — | Testing Engineer |
| 7.7 | Manual smoke test: 4-camera live feed, verify no alert spam | — | Testing Engineer |

**Test matrix (minimum)**

| Scenario | Expected fused state | Alert? |
|----------|---------------------|--------|
| Side view, one wrist missing | Unknown | No |
| Frontal, one wrist missing, single cam | Unknown | No |
| Frontal, one wrist missing, 2 cams agree | Concealed (sustained) | Yes |
| Cam A concealed, Cam B wrist visible | Visible | No |
| Both wrists missing frontal | Unknown | No |
| Adjusting clothes (YOLO FP), 1 cam | Unknown or Visible | No |
| YOLO + MoveNet agree, 2 frontal cams | Concealed (sustained) | Yes |

---

### Phase 8 — Field Validation

**Goal:** Tune thresholds against real jail cell recordings.

**Tasks**

| # | Task | Owner |
|---|------|-------|
| 8.1 | Record labeled test sessions (concealment / benign / side-view) | Operator |
| 8.2 | Run offline replay through new pipeline | Testing Engineer |
| 8.3 | Measure FP rate vs current single-camera baseline | Testing Engineer |
| 8.4 | Tune `config.yaml` thresholds based on results | MoveNet + YOLO Specialists |
| 8.5 | Document final recommended profile in config comments | Architecture Guardian |

---

### File Change Summary

| File | Action | Phase |
|------|--------|-------|
| `config.yaml` | Add `concealment:` block | 0 |
| `monitor_app/evidence.py` | Add enums + dataclasses + packet field | 0, 3 |
| `monitor_app/config.py` | Add config helper | 0 |
| `monitor_app/hand_observation.py` | **New** — per-camera classifier | 1, 6 |
| `monitor_app/fusion/concealment_fusion.py` | **New** — fusion engine | 2 |
| `monitor_app/fusion/__init__.py` | **New** | 2 |
| `monitor_app/fusion.py` | Extend observation storage | 2 |
| `monitor_app/central_inference.py` | Pipeline reorder | 3 |
| `monitor_app/behaviors/concealment_detector.py` | Refactor to fused input | 4 |
| `monitor_app/behaviors/engine.py` | Remove concealment from generic loop | 3, 4 |
| `monitor_app/decision.py` | Fusion gating | 5 |
| `monitor_app/events.py` | New event types | 3 |
| `monitor_app/ai_engine.py` | Hand YOLO inference | 6 |
| `monitor_app/concealment_detector.py` | Deprecate | 4 |
| `tests/test_hand_observation.py` | **New** | 1, 7 |
| `tests/test_concealment_fusion.py` | **New** | 2, 7 |
| `tests/test_concealment_fusion_e2e.py` | **New** | 5, 7 |
| `tests/test_concealment_tracking.py` | Update | 4, 7 |

---

### Dependency Graph

```
Phase 0 (config + models)
    ↓
Phase 1 (hand_observation)
    ↓
Phase 2 (concealment_fusion)
    ↓
Phase 3 (pipeline reorder) ──→ Phase 5 (decision gating)
    ↓
Phase 4 (detector refactor)
    ↓
Phase 7 (tests) ←──────────────── Phase 6 (YOLO, optional parallel after Phase 5)
    ↓
Phase 8 (field validation)
```

**Critical path:** 0 → 1 → 2 → 3 → 4 → 5 → 7 → 8  
**Parallel track:** Phase 6 (YOLO) can begin after Phase 1; integrates at Phase 6 tasks 6.5–6.6.

---

## 13. Definition of Done

A task is complete only when all of the following are true:

- [ ] Architecture respected (GEMINI.md pipeline order, event bus, loose coupling)
- [ ] Thread safety maintained on all new shared state
- [ ] No hardcoded thresholds in Python
- [ ] All new logic covered by unit tests
- [ ] Full `pytest` suite passes
- [ ] Manual 4-camera smoke test completed
- [ ] Logging added for state transitions (throttled, not per-frame)
- [ ] `CONCEALMENT_FUSION_ARCHITECTURE.md` updated if design deviates
- [ ] Legacy `monitor_app/concealment_detector.py` deprecated or removed
- [ ] No regression in aggression, fast movement, knife, cellphone detection

---

## 14. Explicit Non-Goals

- Replace MoveNet with YOLO for concealment
- Hardcode thresholds in Python
- Block the UI thread
- Add full ReID (out of scope per GEMINI.md Rule 6)
- Let detectors write directly to `incidents.db`
- Bypass the event bus for incident lifecycle
- Modify aggression or fast movement detection in this pass

---

## 15. Open Design Choices

Decisions needed before implementation:

| # | Question | Options |
|---|----------|---------|
| 1 | Zone config | Do 4 cameras map to one cell zone, or multiple? |
| 2 | Phase 5 timing | Ship fusion with MoveNet-only first, or wait for YOLO hand model? |
| 3 | `min_supporting_cameras` | Default `2` (conservative) vs `1` with `require_yolo_confirmation: true` (moderate) |
| 4 | Single-camera override | Allow in very small cells with explicit operator config? |

---

## Related Documents

- [GEMINI.md](GEMINI.md) — Engineering constitution
- [ARCHITECTURE_REPORT.md](ARCHITECTURE_REPORT.md) — Inference & decision pipeline analysis
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — Original concealment feature plan (Phases 0–5)

---

### Approval Checklist

Before starting Phase 0, confirm:

- [ ] Zone config: one zone for all 4 cameras (or provide mapping)
- [ ] `min_supporting_cameras` default (recommended: 2)
- [ ] Milestone A first (MoveNet fusion) vs wait for YOLO model
- [ ] Approve pipeline reorder in `central_inference.py`

---

**Awaiting approval before implementation.**
