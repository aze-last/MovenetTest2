# Implementation Plan — Bounding-Box Flicker Remediation

**Created:** 2026-07-14
**Status:** IMPLEMENTED (2026-07-14) — user gave final green light after both pre-implementation
conditions were RESOLVED with real measured data (§0a): Condition 1 (A5, ONNX exonerated) and
Condition 2 (B1 VRAM, Option (a) chosen). Phase A instrumentation, Phase B (YOLO), and Phase C
(MoveNet) are all landed; see §4 "Implementation status" for the per-item outcome and the
verify-on-device checklist. All 28 tests pass (21 pre-existing + 7 new flicker regressions).
**Owners:** YOLO Specialist (Part A), MoveNet Specialist (Part B). These are two independent
render paths with independent root causes — do NOT bundle them into one change.

---

## 0. Investigation summary (evidence base)

Two separate box types flicker; they render independently and have independent causes.

| | YOLO contraband boxes | MoveNet person boxes |
|---|---|---|
| Root cause | Shared global ByteTracker across interleaved multi-camera frames → track_id churn | Hard confidence gates (esp. the 0.25 ghost-filter) oscillating on MoveNet outputs near threshold during motion |
| Regression from today's ONNX migration? | **No** — zero YOLO lines changed today | **No** — gates/box math unchanged; today's tracker change *reduced* churn |
| Verdict | **PRE-EXISTING** (~2026-07-08, commit `800f5d70d`/`007349e80`) | **PRE-EXISTING** (bbox introduced `7a896c3e1`, gates unchanged) |

Cross-check (Part C): offline Findings 1 & 2 (video-time dt, frame_index unification) never
touched the live render path. `classify_behavior` (ai_engine.py:660-680) uses
`custom_time or time.time()`; live builds `res` with no `"timestamp"` key so live keeps
`time.time()` unchanged. Live already had a per-camera monotonic frame counter, and today's
ONNX commit changed the live tracker line from global `self.stats["total"]` to per-camera
`frame_number` — verified in git diff — which *reduces* cross-camera ID churn.

**Measured MoveNet flicker (real ONNX inference on sample video, CPU):**
normal.mp4 = 0 on/off transitions / 150 frames; rodtang.mp4 = 8; aggressive.mp4 = 14.
Flicker is motion/pose-dependent, confirming gate-oscillation mechanism.

---

## 0a. Condition resolutions — real measured data (2026-07-14)

Both pre-implementation conditions are now closed with actual measurements (not predictions).
Measurement scripts were throwaway; no `monitor_app` source, no `requirements.txt`, and no app
venv was modified.

### CONDITION 1 — A5 TF-vs-ONNX keypoint-confidence diff → **ONNX EXONERATED**

Ran the old TF `saved_model` (TensorFlow 2.10, numpy pinned <2 in a throwaway `.venv_tfcmp`)
against `movenet_multipose.onnx` (onnxruntime CPU), feeding **identical** app-preprocessed pixels
(BGR2RGB → resize 256×256 → int32) across 20 sampled frames from normal/rodtang/aggressive.mp4.
**901 per-keypoint comparisons.** Real output:

| Metric | Value |
|---|---|
| Boundary crossings within [0.20,0.30] band (TF>0.25 xor ONNX>0.25) | **0 / 77** |
| Total boundary crossings, all keypoints | **0 / 901 (0.00%)** |
| Ghost-filter keypoints (5 l_sh, 6 r_sh, 11 l_hip, 12 r_hip) | 53 samples each; **0 crossings** |

**Precision caveat (verified `verify_a5.py`, 2026-07-14):** the 5-decimal summary rounded the
deltas to `0.00000`, which looked suspiciously perfect. Re-checked at 8+ decimals on raw values:
deltas are **genuinely non-zero but tiny** — max\|Δ\| = **2.83e-06**, mean\|Δ\| = **1.95e-07**
(294/336 array elements non-zero, 19 elements >1e-6, **0 elements >1e-4**). These are the expected
floating-point differences between TF and ONNX-Runtime CPU conv kernels on the same graph — not an
artifact. Anti-artifact checks all passed: TF object = `_UserObject` (TF 2.10) vs ONNX =
`onnxruntime.InferenceSession` with providers `['CPUExecutionProvider']` (no TF fallback),
`infer is sess` = False, `np.array_equal(tf,onnx)` = **False** (not the same model vs itself);
identical input to both (input SHA256 `5b8a7e52…`, `tf.constant bytes == inp bytes` = True, dtype
int32) — so no preprocessing mismatch masking a real difference.

**VERDICT: ONNX EXONERATED — deltas are real but ~4 orders of magnitude too small to matter
(max\|Δ\| = 2.83e-06 vs the ~1e-3 needed to flip a keypoint across the 0.25 gate; 0 boundary
crossings on 901 keypoints).** The `tf2onnx opset=13` export is numerically faithful. ONNX is
**not** a secondary aggravator on the gate-oscillation cause — it contributes negligibly to
MoveNet box flicker. Phase C therefore does **not** require any ONNX-specific ghost-filter re-tune;
the C1/C2 hysteresis + config-externalization approach is sufficient and correct as scoped.
_(Throwaway artifacts to delete: `.venv_tfcmp/`, `tfcmp_a5.py`, `verify_a5.py`.)_

### CONDITION 2 — B1 VRAM decision → **Option (a) 4 instances CHOSEN**

Real nvidia-smi + TensorRT accounting on the target RTX 2050 (4096 MiB), using the live model
`best.engine` (TensorRT, the path `ai_engine.py:222` loads), imgsz=960, `device=0`,
`.track(persist=True)` — matching `ai_engine.py:550`. Run in the app's real `.venv310`.

| State | nvidia-smi `memory.used` | Δ vs idle |
|---|---|---|
| Idle baseline | 1253 MiB | — |
| 1 instance loaded + track×3 | 1505 MiB | +252 MiB (incl. one-time shared CUDA/torch ctx) |
| 2 instances active | 1628 MiB | +375 |
| 3 instances active | 1757 MiB | +504 |
| **4 instances active (concurrent pass)** | **1919 MiB** | **+666** |

TensorRT's own cumulative GPU alloc was linear/non-shared: 121→243→364→486 MiB (~121 MiB/instance
= 43 MiB engine + ~80 MiB execution context). Marginal cost per extra instance ≈ **120–160 MiB**.

Headroom vs 4096 MiB at 4-camera full load: **1919 used → 2177 MiB (53%) free**; the 85% safe
ceiling is 3481 MiB, so we sit **1562 MiB under** it. MoveNet is CPU-only ONNX (0 VRAM); decode/UI
are CPU. **No OOM at any instance count.**

**DECISION: Option (a) — one YOLO `best.engine` instance per camera (4 total) — CHOSEN.** Fits in
1919 of 4096 MiB with 53% headroom, comfortably under the safe ceiling, giving clean per-camera
ByteTrack isolation at trivial VRAM cost (~120–160 MiB/instance). Option (b) (shared model +
per-camera tracker state, ≈1505 MiB) remains viable and marginally cheaper — its tracker state is
CPU-side Kalman/ID bookkeeping (negligible VRAM) — but its ~400 MiB saving is irrelevant against
2177 MiB of headroom and it costs implementation complexity, so it is **not** chosen.
**Guardrail:** if the contraband model is later swapped for a heavier engine (e.g. yolo11s at high
imgsz) that inflates per-instance cost 3–4×, **re-run this VRAM probe before shipping** — the 53%
margin is healthy but finite.

---

## 1. Guiding constraints (GEMINI.md)

- No hardcoded thresholds/timings — add config keys (`config.yaml`), Rules 4 & 7.
- Do not remove code silently — any deletion documented here with line + purpose.
- Respect ownership: YOLO Specialist never edits MoveNet logic and vice-versa (GEMINI agent roster).
- Thread-safe, event-driven, fail-safe. Do not block the UI thread (Rule 1).
- Definition of Done: architecture respected, tests executed, logging updated, docs updated
  (`capstone_progress_report.md`), changes bundled into `changes_today.zip`.

**Recommended sequencing:** Phase A (instrumentation) BEFORE any fix, to capture real
2-camera / TF-vs-ONNX baseline data and prove each fix. Then Phase B (YOLO) and Phase C
(MoveNet) can proceed in parallel — they touch disjoint files.

---

## Phase A — Instrumentation to capture real baseline data (do first)

Goal: replace static predictions with logged numbers before/after each fix. All prints are
temporary DEBUG, throttled, and removed after diagnosis (GEMINI logging rules: never log every
frame in production — these are diagnostic-only, gated behind a debug flag).

Add config key `debug.flicker_trace: false` in `config.yaml`; guard every diagnostic print.

- **A1 — YOLO track_id/conf/box trace.** In `ai_engine.py` after line 596 (`track_id = ...`),
  log `cam_id, frame_index, cls_id, track_id, conf, box, box.id is None`. After line 638, log
  hysteresis snapshot (`current_det_keys`, cache keys, emitted sources).
- **A2 — YOLO call-order trace.** At top of `_run_yolo_logic` (ai_engine.py:541), log
  `cam_id, thread_ident` to prove one shared tracker sees interleaved cameras.
- **A3 — MoveNet gate trace.** In `_run_movenet_logic` (ai_engine.py:423-431), per slot log
  `mean_conf, n_valid(>0.25), has_shoulders, has_hips, L/R shoulder conf`, and each gate
  pass/fail. Run 10 s stationary subject → shows which gate oscillates.
- **A4 — StableID trace.** In `tracking/stable_id.py::update`, log
  `camera_id, frame_number, {raw_id→stable_id, match_dist}` + every create/stale-delete, and
  `frame_number` deltas (detect motion-gate-skip leaps past grace_frames).
- **A5 — TF-vs-ONNX confidence diff — ✅ DONE + VERIFIED (2026-07-14).** Executed; full results in
  §0a Condition 1. Verdict: **ONNX EXONERATED** — real deltas max|Δ| = 2.83e-06, mean|Δ| = 1.95e-07
  (verified at 8+ decimals in `verify_a5.py`; the 5-decimal summary had rounded these to 0.00000),
  0/77 boundary crossings in the [0.20,0.30] band. TF run in a throwaway `.venv_tfcmp` (TF 2.10 +
  numpy<2); `requirements.txt` untouched. Throwaway `.venv_tfcmp/`, `tfcmp_a5.py`, `verify_a5.py`
  to be deleted. Remaining Phase A items (A1–A4) are still TODO before Phase B/C.

**Exit criterion:** A5 done (above). Remaining: logged 2-camera capture showing YOLO track_id
churn (A1/A2), and a 10 s MoveNet capture showing gate oscillation vs a stable stable_id (A3/A4).

---

## Phase B — YOLO contraband box flicker (Owner: YOLO Specialist)

Root cause ranking (from investigation):
1. **[PRIMARY]** Shared global ByteTracker across interleaved multi-camera frames.
2. **[SECONDARY]** Untracked `cache_key` embeds jittering `x1,y1` → hysteresis no-op.
3. **[TERTIARY]** Conf-gate oscillation at 0.30 + dead `TRACKER_CFG` (intended track_thresh=0.2
   never took effect).

### B1 — Per-camera ByteTrack isolation (fixes primary cause)
- **Problem:** `ai_engine.py:550` `self.yolo_custom.track(..., persist=True)` with no `tracker=`
  isolation. One global tracker sees cam A/B frames interleaved via the single shared queue
  (`central_inference.py:32`) + single worker (`:78`) → track_id churns every frame with ≥2 cams.
- **Change:** give each camera its own tracker state. **DECISION RESOLVED (see §0a Condition 2):
  Option (a) — one `YOLO` best.engine instance per camera (4 total) — CHOSEN**, based on measured
  VRAM: 4 concurrent instances = **1919 / 4096 MiB (53% headroom)**, no OOM, ~120–160 MiB marginal
  per instance. This was chosen on the real number, not for simplicity. Option (b) (shared model +
  per-camera tracker state, ≈1505 MiB) was viable/cheaper but its ~400 MiB saving is irrelevant
  against 2177 MiB headroom and it adds complexity — **not** chosen.
  - _Rejected/deferred:_ (b) Keep one model + per-camera persistent tracker (Ultralytics `tracker=`
    YAML + per-camera persist state). Kept on record as fallback if a future heavier model inflates
    per-instance VRAM (re-run the §0a probe before shipping such a swap).
- **Config:** no hardcoded tracker params — route through a real, imported tracker config
  (see B3). Add `yolo.tracker_isolation: per_camera` key.
- **VRAM guardrail:** re-run the §0a probe if the contraband engine is swapped for a heavier model
  (yolo11s / higher imgsz) — the 53% margin is healthy but finite.
- **Verify:** re-run A1/A2 — track_id must stay stable per-camera across 10 s, no cross-camera
  interference.

### B2 — Stabilize the untracked cache_key
- **Problem:** `ai_engine.py:600` `cache_key = ... f"untracked_{cls_id}_{x1}_{y1}"` — jittering
  coords generate a new dict key every frame, so hysteresis (`:624-638`) never bridges gaps for
  untracked boxes.
- **Change:** for the untracked path, key on a quantized/spatial-bucketed location (e.g. grid
  cell) or a short-lived IoU-matched slot, so a stationary object maps to a stable key across
  small jitter. Keep the tracked path (`track_id`) as-is.
- **Note (no deletion):** existing untracked-key line is *modified*, not removed; its original
  purpose (collision-avoidance for id-less detections) is preserved via the bucketed key.
- **Verify:** A1 shows `source` no longer toggling combined↔hysteresis↔absent for a stationary
  untracked object.

### B3 — Resolve dead TRACKER_CFG + conf-gate oscillation
- **Problem:** `tracker_config.py::TRACKER_CFG` is never imported (verified: grep matches only
  the definition + .pyc). Commit `b55207a4f`'s track_thresh=0.2 cellphone fix is inert;
  effective gate is ByteTrack's packaged default 0.25.
- **Change:** either wire `TRACKER_CFG` into the `.track(tracker=...)` call (B1 path b), or
  delete it as confirmed dead — **if deleted, document here:** `tracker_config.py` TRACKER_CFG
  (whole file) removed because it is unreferenced dead code superseded by B1's per-camera config;
  its intended values (track_thresh, track_buffer) migrate into the new `yolo.tracker` config.
- Conf-gate oscillation (`:598`, thresholds 0.30) is tolerable once B1/B2 restore the hysteresis
  safety net; revisit only if A1 shows residual threshold-boundary flicker after B1/B2.

**Phase B Definition of Done:** A1/A2 re-run shows stable per-camera track_id over 10 s with
2 active cameras; no dead config; regression suite green; documented in progress report.

---

## Phase C — MoveNet person box flicker (Owner: MoveNet Specialist)

Root cause ranking (measured):
- **A (box appears/disappears):** (1) 0.25 ghost-filter oscillation [primary, measured],
  (2) mean `CONF_THR` gate, (3) bbox `>0.1` returns None, (4) motion-gate skip > grace_frames.
- **B (color/label flips on a persistent box):** (1) per-frame `is_alert` recompute
  (`central_inference.py:417-426`), (2) stable_id staleness on long motion-gate skips.

**ONNX aggravator ruled OUT (A5, §0a Condition 1):** the migration shifted keypoint confidences by
only max|Δ| = 2.83e-06 (verified 8-decimal) — ~1000× too small to move a keypoint across the 0.25
gate. So Phase C needs **no** ONNX-specific ghost-filter re-tune; C1/C2 below are the complete fix.
Effectively 100% of the MoveNet flicker is the gate-oscillation cause above.

### C1 — Temporal hysteresis on person-detection presence (fixes primary cause)
- **Problem:** the fixed 0.25 ghost-filter (`ai_engine.py:425-431`) — especially the
  shoulder-pair AND-condition — drops a whole detection when one shoulder keypoint dips to ~0.24,
  so the box vanishes while the person is nearly still. Measured: 8–14 on/off / 150 frames on
  moving subjects, 0 on still subjects.
- **Change:** add short temporal persistence on the *presence* of a tracked person (analogous to
  YOLO hysteresis) so a 1–2 frame keypoint dip does not blank the box. Prefer applying this at
  the tracker/behavior level (a person under grace period keeps its last good bbox) rather than
  loosening the raw gate.
- **Config:** add `movenet.detection_hysteresis_frames` (Rule 7 — no hardcode).
- **Do NOT** simply lower 0.25 globally — that risks ghost detections; the ghost-filter exists
  for a reason. Soften only the shoulder-pair AND-brittleness if A3 data shows it dominates
  (e.g. allow shoulders OR hips already present — verify it doesn't reintroduce ghosts).

### C2 — Make MoveNet gates config-driven
- **Problem:** `0.1` (bbox, :390), `0.25` (ghost filter, :425-431) are hardcoded, violating
  Rule 7.
- **Change:** promote to `config.yaml` keys (`movenet.bbox_kp_conf`, `movenet.ghost_kp_conf`,
  `movenet.ghost_min_keypoints`). No behavior change at default values — pure externalization,
  enabling A3-driven tuning.

### C3 — Stabilize color/label flips
- **Problem:** `is_alert` recomputed each frame from confidence-gated behavior/evidence
  (`central_inference.py:417-426`) → red↔green flicker on an otherwise-stable box.
- **Change:** apply the same detection hysteresis to `is_alert` (latch alert state across the
  grace window) so color doesn't strobe on single-frame evidence gaps.

### C4 — (Investigate, likely defer) double tracker.update + skip-past-grace
- **Confirmed pre-existing, coordinator-verified:** the same per-camera tracker singleton is
  updated twice per frame — `ai_engine.py:494` and `behaviors/engine.py:30` — both with the same
  `frame_number`. Idempotent for grace math but wasteful/fragile.
- **`frame_index` increments even on motion-gate-skipped frames** (`central_inference.py:269`
  before the `should_run` check at :287); a skip streak > `grace_frames`(30) leaps past the grace
  window → stale tracks → fresh IDs on reacquire → flicker.
- **Change (after A4 data):** collapse to a single authoritative `tracker.update` per frame
  (decide owner: behavior engine vs ai_engine — do NOT remove either without documenting which
  and why here), and/or advance the tracker's frame counter only on frames MoveNet actually
  processed so grace math tracks processed-frame cadence, not raw-frame cadence.

**Phase C Definition of Done:** A3/A4 re-run shows box on/off transitions ≈0 for a stationary
subject and materially reduced for moving subjects, with stable stable_id/color; A5 TF-vs-ONNX
diff logged (ONNX confirmed exonerated or quantified as aggravator); tests green; documented.

---

## 2. Files expected to change (for changes_today.zip scoping)

- `config.yaml` — new keys: `debug.flicker_trace`, `yolo.tracker_isolation`/`yolo.tracker`,
  `movenet.detection_hysteresis_frames`, `movenet.bbox_kp_conf`, `movenet.ghost_kp_conf`,
  `movenet.ghost_min_keypoints`.
- `monitor_app/ai_engine.py` — Phase A traces; B1/B2/B3 YOLO tracker + cache_key; C1/C2 gates.
- `monitor_app/central_inference.py` — C3 is_alert latch; C4 single-update decision.
- `monitor_app/tracking/stable_id.py` — A4 trace; C4 frame-counter cadence.
- `monitor_app/tracker_config.py` — B3 wire-in or documented deletion.
- `tests/` — regression tests for per-camera tracker isolation and detection hysteresis.
- `capstone_progress_report.md` — session documentation (mandatory).

## 3. Explicit non-goals

- No full ReID upgrade to StableIDTracker (GEMINI Rule 6).
- No reintroduction of TensorFlow to `requirements.txt` (A5 uses a throwaway env only).
- No merging of YOLO and MoveNet flicker fixes — separate owners, separate causes, separate PRs.
- No lowering of the 0.25 ghost-filter as a blanket fix (ghost-detection risk).

---

## 4. Implementation status (2026-07-14)

All landed. No default behavior changed except the intended fixes; every new threshold is a
config key defaulting to the prior in-code value (GEMINI Rule 7).

### Phase A — instrumentation (all gated behind `debug.flicker_trace: false`)
- **A1** ✅ `ai_engine._run_yolo_logic`: per-detection `[FLICKER-A1]` (cam/fidx/cls/track_id/
  id_is_none/conf/box) + hysteresis-cache snapshot (live vs cache keys, emitted sources).
- **A2** ✅ `ai_engine._run_yolo_logic`: `[FLICKER-A2]` cam/thread-ident/model-id/isolation.
- **A3** ✅ `ai_engine._run_movenet_logic`: per-slot `[FLICKER-A3]` mean_conf/n_valid/has_sh/
  has_hip/L_sh/R_sh + gate pass/fail.
- **A4** ✅ `tracking/stable_id.update`: `[FLICKER-A4]` matches/new_ids/stale_deleted/live_tracks
  + frame-delta LEAP>grace detection.
- **A5** ✅ DONE + VERIFIED earlier (§0a Condition 1). ONNX exonerated (max|Δ| = 2.83e-06).

### Phase B — YOLO (Owner: YOLO Specialist)
- **B1** ✅ Option (a): `_get_yolo_for_camera(cam_id)` lazily creates one `YOLO` instance per
  camera (`yolo.tracker_isolation: per_camera`) → isolated ByteTrack state. `shared` restores
  legacy. Fallback bg-reload clears `yolo_per_cam` so clones rebuild from the fallback model.
- **B2** ✅ `_untracked_cache_key(...)` quantizes id-less detections to a spatial grid
  (`yolo.untracked_grid_px: 96`) instead of raw `x1,y1` → stable hysteresis key under jitter.
- **B3** ✅ **`tracker_config.py` DELETED** (confirmed dead — grep showed only its own
  definition, never imported). Its intended values migrated to `config.yaml yolo.tracker` and
  are now made *live* via `_get_tracker_yaml()`, which writes a ByteTrack YAML from config and
  passes it to `model.track(tracker=...)`. `track_high_thresh: 0.2` (was the inert
  `TRACKER_CFG['track_thresh']`) now actually takes effect. Ultralytics 8.4.26 schema confirmed
  on-disk before wiring. Falls back to packaged `bytetrack.yaml` if generation ever fails.

### Phase C — MoveNet (Owner: MoveNet Specialist)
- **C1** ✅ Render-side box coasting in `central_inference._render_person_boxes`: a person's box
  persists up to `movenet.detection_hysteresis_frames` (8) frames across a ghost-filter dropout.
  Rendering-only — behavior/fusion/decision untouched, so coasting can never fabricate an incident.
- **C2** ✅ Gates externalized: `movenet.bbox_kp_conf` (0.1), `movenet.ghost_kp_conf` (0.25),
  `movenet.ghost_min_keypoints` (5). Defaults preserve prior behavior exactly.
- **C3** ✅ Alert-colour latch in the same cache: alert red latches for the hysteresis window so
  a single-frame evidence gap doesn't strobe red↔green.
- **C4** ⏸️ **DEFERRED (documented, no removal).** Investigated: the per-camera tracker is updated
  twice/frame — `ai_engine._run_movenet_logic` (async MoveNet thread, assigns the stable_ids
  `classify_behavior` keys on) and `behaviors/engine.analyze_packet` (worker thread, refreshes
  `last_seen_frame` every frame incl. motion-gate skips). Neither can be removed without risk:
  dropping #1 breaks legacy behavior keying; dropping #2 strands tracks during skip streaks and
  forces fresh IDs on reacquire (**more** flicker). C1's render hysteresis already masks the
  reacquire blink, so the structural collapse + processed-frame-cadence change stay deferred
  pending A4 field data. Both call sites now carry an explicit `C4 (deferred)` comment.

### On-device verify checklist (run in `.venv310` on the RTX 2050, 2+ cameras)
1. Set `debug.flicker_trace: true`, run 2 cameras 10 s; confirm A1/A2 show **stable per-camera
   track_id** (no cross-camera churn) — the B1 acceptance criterion.
2. Confirm A3 gate trace + on-screen boxes: stationary subject ≈0 box on/off transitions; boxes
   coast smoothly through brief dips (C1); no red↔green strobing (C3).
3. Reset `debug.flicker_trace: false` for production.
4. **VRAM guardrail:** if the contraband engine is ever swapped for a heavier model, re-run the
   §0a Condition 2 probe before shipping (53% headroom is healthy but finite).

---

## 2026-07-15 — RC-2 draw-loop consolidation (code replaced, documented per no-silent-removal rule)

The two inline contraband draw loops (`central_inference.py`: the "PHASE 2 Render" loop in
`_run_parallel_inference` and the "Re-draw YOLO contraband boxes" loop in the power-saving
branch of `_worker_loop`) were REPLACED by one shared helper `_draw_contraband_boxes()`.
Purpose of the originals: draw red box + "ALERT: NAME (ID: n)" label for every contraband
detection. That exact rendering is preserved verbatim inside the helper; the only behavioral
delta is the RC-2 render dedup (`_contraband_for_render`) that skips a coasting
`combined_hysteresis` ghost overlapping a live same-class box at IoU ≥
`yolo.hysteresis_dedup_iou`. Decision-path data (`packet.detections`) is never modified.

## 2026-07-15 — RC-4 draw_skeleton call in ai_engine (flag-gated, NOT removed)

`_run_movenet_logic`'s `draw_skeleton` call now sits behind a `draw=True` parameter.
Purpose of the original call: render skeleton overlays during inference. On the async
parallel path the target is a discarded `frame.copy()` (dead work on the CPU-bound MoveNet
thread), so `central_inference._movenet_worker` passes `draw=False`; the visible skeleton is
drawn later by `_render_person_boxes` on the real output frame. The synchronous
`process_frame` path keeps `draw=True`, i.e. its original behavior. To restore the old async
behavior, pass `draw=True` at the `run_movenet_only` call site.
