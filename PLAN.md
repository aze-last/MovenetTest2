# PLAN.md — Phase 1: PyInstaller .spec Excludes & Top-Level Import Hardening

## 1. Spec & Objective
- **Problem:** CellWatch's packaged PyInstaller distribution is excessively large (~7.0 GB uncompressed), packaging unused libraries like `polars` (157.6 MB) and heavyweight TensorFlow/Keras artifacts. Furthermore, unguarded top-level imports of PyTorch and TensorFlow can cause catastrophic runtime crashes on clean machines without full toolchains.
- **Hypothesis:** Excluding `polars`, `keras`, `tensorboard`, and `tensorflow*` in `CellWatch.spec` while keeping `tensorrt` for GPU YOLO reduces the distribution footprint by >160 MB, and broadening top-level imports in telemetry/logging modules guarantees crash-free startup across heterogeneous environments.
- **Invariants & Constraints:**
  - Maintain `tensorrt` in the bundle for RTX 2050 GPU YOLO26s inference.
  - Rule 8 (Dependency Freeze): No new packages or dependencies.
  - Rule 10 (Secrets Hygiene): No tokens, keys, or credentials.
  - Rule 9 (RTK Tooling): Strictly use `rtk` for commands.

---

## 2. Scoped Tasks

### T1 — Update Installer Prerequisites Test (surface: tests/test_installer_prereqs.py)
- **Files:** `tests/test_installer_prereqs.py`
- **Scope:** Update tests to assert that `polars`, `keras`, `tensorboard`, and `tensorflow*` are explicitly listed in `CellWatch.spec`'s `excludes` array, while confirming that `tensorrt` remains included.
- **Test:** Run `pytest tests/test_installer_prereqs.py` to produce a RED failing test prior to `.spec` edits.
- **Gate:** Test fails initially on missing `polars` in `CellWatch.spec` excludes.

### T2 — Add Excludes to `CellWatch.spec` (surface: CellWatch.spec)
- **Files:** `CellWatch.spec`
- **Scope:**
  1. Add `'polars'` to `Analysis.excludes` (0 imports in `monitor_app`, saving 157.6 MB).
  2. Add `'keras'`, `'tensorboard'`, `'tensorflow'`, `'tensorflow-cpu'`, `'tensorflow-hub'` to `Analysis.excludes`.
  3. Ensure `'tensorrt'` is NOT excluded.
- **Test:** Run `pytest tests/test_installer_prereqs.py` to turn GREEN.
- **Gate:** `test_installer_prereqs.py` passes cleanly.

### T3 — Harden Top-Level Torch/TensorFlow Imports (surface: telemetry & logging)
- **Files:**
  - `monitor_app/monitor_logging/performance.py`
  - `monitor_app/telemetry/collectors/system.py`
  - `monitor_app/exporters/session_exporter.py`
  - `monitor_app/telemetry/hardware_profiler.py`
- **Scope:**
  - Expand top-level `except ImportError:` blocks to `except (ImportError, OSError, Exception):` so missing DLLs, CUDA errors, or partial wheels on target machines never crash CellWatch.
- **Test:** Unit test simulating missing/broken torch/tensorflow modules across these 4 files.
- **Gate:** All 4 modules import cleanly without raising unhandled exceptions when torch/tensorflow are uninstalled or broken.

---

## 3. Edge Cases & Safety
- **GPU Inference Safety:** `tensorrt` must NOT be in `Analysis.excludes`, or YOLO GPU inference will fail at runtime.
- **Polars Usage Audit:** Confirmed: `git grep "polars" monitor_app/` returns 0 matches. Safe to exclude.
- **Mechanical Gate:** `.agents/team/diff-scan.ps1` must report `RESULT: GREEN`.
- **Review Gate:** `agy --mode plan` must report `Decision: APPROVE` on `git diff`.
