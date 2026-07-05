# CellWatch AI: Telemetry & Benchmarking Subsystem Manual

This document details the architecture, workflows, and operations of the Telemetry & Benchmarking subsystem implemented in CellWatch AI.

---

## 1. Subsystem Workflow Overview

The subsystem operates under two distinct workflows: **Live Telemetry** and **Controlled Benchmarking**.

```
                           +----------------------------------+
                           |       EventBus Publisher         |
                           +----------------------------------+
                                             |
                                             v
                           +----------------------------------+
                           |  TelemetryEngine (Async Queue)   |
                           +----------------------------------+
                                             |
                                             v
                           +----------------------------------+
                           |      TelemetryWorker Thread      |
                           +----------------------------------+
                                             |
                   +-------------------------+-------------------------+
                   |                         |                         |
                   v                         v                         v
        +--------------------+     +--------------------+    +--------------------+
        |  Camera Collector  |     |    AI Collector    |    |  System Collector  |
        +--------------------+     +--------------------+    +--------------------+
                   |                         |                         |
                   +-------------------------+-------------------------+
                                             |
                                             v
                           +----------------------------------+
                           |   Live Dashboard / Replay UI     |
                           +----------------------------------+
```

### A. Live Telemetry Workflow (Continuous Operational Monitoring)
1. **Frame Read**: The Camera Thread reads a frame, assigns a unique `Frame UUID` (format: `cam_{id}_frame_{seq}_{timestamp_uuid}`), initializes a `TelemetryContext`, and publishes `TELEM_FRAME_READ`.
2. **Pipeline Checkpoints**: As the frame is processed on the main worker thread, checkpoints are registered on the context (`queue_exit`, `movenet_start`, `movenet_end`, `yolo_start`, `yolo_end`, `behavior_start`, etc.).
3. **Pipeline Completion**: Once decision and alert routing are finished, the context is retired from the active registry and a `TELEM_PIPELINE_COMPLETE` event is dispatched.
4. **Asynchronous Processing**: All `TELEM_*` events are queued in a bounded `TelemetryQueue`. The background `TelemetryWorker` thread consumes them, updates the in-memory **Bounded Ring Buffers** (size-capped at 5,000 frames or 5 minutes), and feeds the live GUI.
5. **Event Drop Policy**: If the queue fills up under heavy load, the `DROP_OLDEST` policy drops the oldest telemetry events to guarantee the main AI pipeline never blocks.

### B. Controlled Benchmarking Workflow (Stress & Regression Testing)
1. **Session Initialization**: The coordinator loads a session profile (Quick, Baseline, Load, Endurance) and queries system properties (CPU/GPU info, CUDA level, OS version, Git commit, config hash) to generate a **Session Manifest**.
2. **Stress Feed Injection**: Multiple simulated camera threads feed high-frequency mock images into the inference manager.
3. **AI Pipeline Validation**: The actual loaded YOLOv8 and MoveNet neural networks process the mock workload.
4. **Metric Logging & Scoring**: Timeline records (CPU, temperatures, clocks, queues) are stored in [benchmark.db](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/benchmark.db). An overall Performance Score (0-100) is calculated based on FPS stability, latency, and drops.
5. **Regression & Exports**: The runner evaluates current performance against the locked **Golden Baseline**. It generates a portable export bundle containing manifests, Markdown reports, CSV time-series, and Matplotlib graphs.

---

## 2. File and Directory Manifest

The subsystem consists of the following components:

### Telemetry Package (`monitor_app/telemetry/`)
* **[\_\_init\_\_.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/telemetry/__init__.py)**: Package init, instantiates and registers default sub-collectors.
* **[context.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/telemetry/context.py)**: Defines `TelemetryContext` carrying Float timestamps and `Frame UUID` tags.
* **[engine.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/telemetry/engine.py)**: Implements asynchronous `TelemetryQueue` and worker threads.
* **[hardware_profiler.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/telemetry/hardware_profiler.py)**: Retreives CUDA, CPU, OS platform specifications, and git revisions.
* **[dashboard.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/telemetry/dashboard.py)**: Live CustomTkinter dashboard panel and historical slider-scrub replay.
* **collectors/**:
  * `camera.py`: Bounded collection of FPS, signal drops, reconnects, and queue delays.
  * `ai.py`: Records fine-grained timing percentiles (P95/P99) for all model stages.
  * `system.py`: Queries CPU percentage, RAM GBs, PyTorch VRAM, thermal temps, and clock speeds.
  * `queue.py`: Tracks backlog depth.
  * `health.py`: Tracks failure-first metrics (inference crashes, database retries, exception counts, memory slopes).

### Benchmarking Package (`monitor_app/benchmark/`)
* **[\_\_init\_\_.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/benchmark/__init__.py)**: Package init.
* **[\_\_main\_\_.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/benchmark/__main__.py)**: Main CLI benchmarking coordinator.
* **[db.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/benchmark/db.py)**: Manages SQLite table initialization, metrics timeline, and golden baseline locks.
* **[benchmark_exporter.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/monitor_app/benchmark/benchmark_exporter.py)**: Packages reports, timeline CSVs, and Matplotlib charts.

### Verification & Rules
* **[test_telemetry.py](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/tests/test_telemetry.py)**: Pytest suite validating collector mathematics and event queues.
* **[benchmark-performance-engineer.md](file:///c:/Users/ASUS/PycharmProjects/MovenetTutorial/.agent-team/templates/benchmark-performance-engineer.md)**: Agent Swarm Specialist template.

---

## 3. How to Operate the Subsystem

### Running CLI Benchmarks
Run a standard Quick (30s) session:
```powershell
.venv310\Scripts\python -m monitor_app.benchmark
```

Run a custom Load Test (30 minutes) profile:
```powershell
.venv310\Scripts\python -m monitor_app.benchmark load
```

### Locking a Golden Baseline
Set a baseline in `benchmark.db` (for instance, a stable release commit):
```python
from monitor_app.benchmark.db import BenchmarkDBManager
db = BenchmarkDBManager()
db.set_golden_baseline("run_1782523137")
```
*Subsequent benchmark runs will automatically perform delta regression comparisons against this locked run.*
