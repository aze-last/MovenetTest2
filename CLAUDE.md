# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CellWatch AI is an undergraduate capstone project: a real-time institutional monitoring system for jail cells (target deployment: Philippine BJMP facilities). One Windows laptop processes up to 4 CCTV camera feeds through an AI pipeline (MoveNet pose estimation + YOLO26s contraband detection) to detect aggression, fast movement, contraband (knife/cellphone), and hand concealment, then records evidence and raises operator alerts. It is an event-driven monitoring system, not a frame-by-frame object detector — see `GEMINI.md` for the full engineering constitution this project is built against.

**Read `GEMINI.md` before any non-trivial change.** It defines architectural rules, module ownership boundaries, and the definition of done for this repo, and takes precedence over generic conventions.

## Commands

The project uses two virtual environments — always use `.venv310` (Python 3.10) for running/testing the app; it matches `requirements.txt` (ONNX Runtime, TensorRT, CUDA torch). `.venv` (Python 3.13) is a legacy/alternate environment.

```powershell
# Run the app (GUI)
.\run_app.ps1
# equivalent to: .venv310\Scripts\python.exe monitor_app\main.py

# Run the MoveNet model download/verification script
.\run_test.ps1
# equivalent to: .venv310\Scripts\python.exe monitor_app\test.py

# Run the pytest suite
.venv310\Scripts\python.exe -m pytest tests/

# Run a single test file / test
.venv310\Scripts\python.exe -m pytest tests/test_concealment_fusion.py
.venv310\Scripts\python.exe -m pytest tests/test_concealment_fusion.py::test_name -v

# Benchmark CLI (session recording / comparison / reporting)
.venv310\Scripts\python.exe -m monitor_app.benchmark
```

If `.venv310` is missing, create it with `py -3.10 -m venv .venv310` then `pip install -r requirements.txt`.

There is no lint/format command configured in this repo; match existing style in the file you're editing.

## Core Architecture

### Pipeline (see `GEMINI.md` "Core Architecture" for the canonical diagram)

```
Camera Threads → Motion Gate → Central Inference (MoveNet + YOLO, parallel)
    → Behavior Engine (StableID tracking + per-person metrics)
    → Hand Observation → Camera Fusion → Concealment Fusion Engine
    → Decision Engine → EventBus("DECISION_TRIGGER")
    → AlertManager (hysteresis state machine) → EventBus("INCIDENT_START"/"EVIDENCE_ADDED")
    → IncidentRecorder (video buffering) → incidents.db → UI
```

The entire per-frame flow is orchestrated in `monitor_app/central_inference.py::CentralInferenceManager._worker_loop()` — this is the single best place to trace how a frame moves through the system end to end.

### Key modules and ownership

| Module | Responsibility |
|---|---|
| `camera_view.py` | Frame capture, builds `EvidencePacket` per frame |
| `central_inference.py` | Thread-pool worker loop orchestrating MoveNet + YOLO + behavior + fusion + decision |
| `ai_engine.py` (`MotionOptimizedEngine`) | Raw MoveNet (CPU) + YOLO (GPU/TensorRT) inference, motion gating, legacy aggression/fast-movement classification |
| `behaviors/engine.py` (`BehaviorEngine`) | Per-camera `StableIDTracker`, precomputes shoulder/torso metrics, runs registered `behaviors/registry.py` detectors |
| `tracking/stable_id.py` | Hip-centroid nearest-neighbor person tracking with grace period for occlusion (not full ReID — see GEMINI Rule 6) |
| `hand_observation.py` | Per-camera, per-hand classification: Visible / Concealed / Unknown (MoveNet wrist confidence + yaw gate) |
| `fusion.py` (`CameraFusion`) | Caches latest `EvidencePacket`/hand observations per camera; also the multi-camera telemetry cache |
| `concealment_fusion.py` (`ConcealmentFusionEngine`) | Zone-level fusion of per-camera hand observations — a single side-view "Concealed" is never sufficient; any "Visible" vetoes; requires `min_supporting_cameras` frontal agreement |
| `behaviors/concealment_detector.py` | Temporal sustain/cooldown on top of fused concealment state → emits `BehaviorEvidence` |
| `decision.py` | Consumes `EvidencePacket`/`BehaviorEvidence`, decides `alert_triggered`, extracts event type + confidence |
| `alert_manager.py` | `HysteresisState` machine per camera: `IDLE → PENDING → CONFIRMED → MAINTAINED → COOLDOWN → IDLE` |
| `incident_record.py` | Video buffering/encoding, writes to `incidents.db` |
| `evidence.py` | Core dataclasses: `EvidencePacket`, `TrackedPerson`, `BehaviorEvidence`, `HandObservation`, `FusedConcealmentObservation` |
| `events.py` | Thread-safe pub/sub `EventBus` — the primary decoupling mechanism between subsystems |
| `config.py` | Loads `config.yaml`; `get_config()`, `get_concealment_config()` |
| `profile_store.py` | Reads/writes `app_state.db` (operator-tunable settings, sensitivity profiles) |
| `telemetry/` | Frame-lifecycle timing/instrumentation, benchmark session tracking |
| `benchmark/` | Offline benchmarking CLI: session comparison, diagnostics, PDF/markdown reporting |
| `exporters/` | Session export to CSV/JSON/Markdown/PDF (see `exports/Session_*` for sample output layout) |

### Concealment detection: multi-camera evidence fusion

This is the most architecturally significant subsystem — see `CONCEALMENT_FUSION_ARCHITECTURE.md` and `ARCHITECTURE_INTEGRATION_REPORT.md` for the full design rationale (both are historical design docs; the design they describe has since been implemented in `hand_observation.py`, `concealment_fusion.py`, and `behaviors/concealment_detector.py`).

Core principle: MoveNet wrist-keypoint absence measures *observability*, not *intent*. A side-view camera showing a "missing" wrist is occlusion, not concealment. So:
1. Each camera independently classifies each tracked hand as `VISIBLE` / `CONCEALED` / `UNKNOWN` (`hand_observation.py`), gated by yaw angle (side views can only report `UNKNOWN`, never `CONCEALED`).
2. `ConcealmentFusionEngine` fuses observations per zone (`concealment.zones` in `config.yaml`): any `VISIBLE` observation vetoes the whole subject/hand to `VISIBLE`; `CONCEALED` requires `min_supporting_cameras` frontal agreement; otherwise the fused state is `UNKNOWN` (never treated as evidence).
3. Only sustained fused-`CONCEALED` state (across `duration_frames`, with `cooldown_frames`) becomes `BehaviorEvidence` with `metadata["fusion_confirmed"] = True`, which is what `decision.py` requires to trigger an incident.

The whole feature is gated by `concealment.enabled` in `config.yaml`, which restores the legacy single-camera path when disabled.

### Dual database architecture (do not mix)

- `app_state.db` — authentication, branding, operator/sensitivity settings, AI tuning, profiles (owned by `profile_store.py`, `auth.py`, `settings.py`)
- `incidents.db` — incidents, evidence, timestamps, reports, video metadata (owned by `incident_record.py`, `incidents.py`)

### Non-negotiable architectural rules (from `GEMINI.md`)

1. Never block the UI (Tkinter) thread — heavy AI, disk/DB IO, recording, and camera decoding must run off-thread.
2. Prefer event-bus (`events.py`) communication over direct module-to-module calls.
3. Every module owns its own state; avoid exposing internal mutable objects across modules.
4. Config separation: engineering parameters live in `config.yaml`; operator-tunable parameters live in `app_state.db`. Never hardcode thresholds in Python — add a config key instead.
5. Incident lifecycle is state-driven (`alert_manager.py`'s hysteresis machine) — evidence accumulates before a database record is created; alerts never write directly to `incidents.db`.
6. `StableIDTracker` intentionally survives brief occlusion/pose changes without implementing full ReID — don't "upgrade" this to a full person-reID system.
7. MoveNet owns pose/behavior/motion; YOLO owns contraband object detection — don't duplicate responsibilities across the two engines.

### Target hardware constraints

Development/target machine: RTX 2050 (4GB VRAM), Ryzen 7 7435HS, targeting 20–30 FPS across up to 4 camera feeds, expected to run continuously for 8–12 hours without memory/queue growth. Keep this in mind when adding per-frame work — prefer motion-gating, frame-interval throttling, and ROI cropping over always-on inference.

## Testing notes

- `tests/` uses pytest with plain function-based tests; no custom fixtures/conftest beyond `tests/__init__.py`.
- `tests/test_concealment_fusion.py` imports a helper (`make_test_person`) from `tests/test_concealment_tracking.py` — these two files are coupled, keep them consistent when changing `TrackedPerson`/fusion shapes.
- Tests construct `EvidencePacket`/`TrackedPerson` objects directly and call engine singletons (`get_decision_engine()`, `get_concealment_fusion_engine()`, etc.) rather than mocking the full pipeline.
