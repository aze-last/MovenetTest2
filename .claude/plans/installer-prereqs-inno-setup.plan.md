
# Plan — Installer Prerequisites + Standard Inno Setup (handoff)

Scope: make the app install and run cleanly from an Inno Setup installer on a
non-dev Windows 11 laptop. Implementer: a separate AI session. This repo's
active track (self-updating-desktop-workflow) is NOT in scope here.

## Evidence (measured 2026-10-08, local workspace)
- No `.iss` exists repo-wide (`**/*.iss` → 0 hits). `dist\CellWatch` is raw
  PyInstaller one-dir output (6,658 files), not an installer source.
- Payload 7.8 GB: `_internal` = torch 4.3 GB + tensorrt_libs 2.2 GB +
  onnxruntime 267 MB + paddle/polars/cv2/scipy remainder. GitHub releases cap
  files at 2 GB → unshippable as one Setup EXE today.
- `app_state.db` is baked into `dist\CellWatch\` root (operator DB ships in the
  image; reinstall wipes it; Program Files isn't user-writable).
- `monitor_app/utils.py:23-36` `data_path()` writes next to the EXE when frozen
  → Access Denied under Program Files for standard users.
- `hooks/` holds only stale `hook-tensorflow.py` (pre-ONNX-migration leftover);
  spec `excludes` still reference tensorflow/tf2onnx.
- Build is `console=True` (`CellWatch.spec:51`) → target-side diagnosis via cmd.

## User journeys
1. As field installer, I run one Setup EXE on a clean jail laptop and get a
   working app or a plain-language blocker message (never a traceback).
2. As operator, my logins/settings survive a reinstall/update.

## Task list (thin slices, in order)
- T1 Diagnose: run `CellWatch.exe` from cmd on the failing target, capture the
  FIRST error (names the missing DLL/driver). Record it; it picks T2 vs T3.
- T2 VC++ Redist: bundle `vc_redist.x64.exe`; `[Run]` gated by registry check
  (`HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64`), `/quiet`.
- T3 GPU pre-check: `[Code]` WMI `Win32_VideoController` → NVIDIA present +
  driver ≥ R545, else friendly abort with driver link. App-side: catch
  torch-GPU/engine init failure → dialog naming the missing piece.
- T4 Engine fallback: ship `best.pt` (20 MB) next to `best.engine`; try engine
  → on version/arch mismatch fall back to PyTorch weights (log + UI notice).
- T5 Writable data: `data_path()` → `%LocalAppData%\CellWatchAI\` when frozen
  (platformdirs or env fallback); migrate `app_state.db`, `incidents.db`,
  recordings, exports, updates/pending. Exclude `*.db,*.log` from `[Files]`.
- T6 The `.iss`: `installer/CellWatch.iss` — `PrivilegesRequired=admin`,
  disk-space check (~10 GB), `[Files]` from `dist\CellWatch\*` with excludes,
  `AppVersion` stamped from `monitor_app.__version__` (`/DMyAppVersion`),
  `[Icons]`, VC-redist `[Run]`, desktop-icon task.
- T7 Verify: clean Win11 VM (no dev tools) × with/without NVIDIA GPU → install,
  launch, login, record 60 s, reinstall (settings survive). Checklist results
  recorded, not automated.

## Constraints (GEMINI.md)
- Rule 4/7: new keys (`update.*` already in config.yaml; installer-side timeouts
  etc. as config, never hardcoded). Version single source stays
  `monitor_app.__version__` — `.iss` reads it, never duplicates it.
- Rule 1: prereq checks run in Inno `[Code]`/installer context, never on the app
  UI thread. Rule 5: no direct DB writes from installer.
- No silent deletions: stale `hook-tensorflow.py` removal (if done) documented
  with line + purpose. Session docs → `capstone_progress_report.md`.

## Out of scope / follow-up track
- Payload slimming (torch CUDA redundancy, paddle/polars/mcp stowaways) — REQUIRED
  before GitHub-release distribution but a separate plan; do not bundle into T1–T7.
- Self-update Milestones 2–3 (active track here) — this plan only guarantees the
  `.iss` emits a versioned, hashed EXE they can consume.

## TBD (decide before T6)
- Per-machine (admin, Program Files) vs per-user (LocalAppData, no admin)?
- Exact target GPU/driver matrix (which machines must work offline?).
- vc_redist source version + where it is vendored.
- `installer/` output path + `version.json` publish flow owner (M2/M3 boundary).
