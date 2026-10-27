# PLAN.md — Phase 3: Opportunistic Face Binding & Phase 4: Cross-Camera Zone Deduplication

## 1. Spec & Objective
- **Problem:**
  1. **Phase 3:** While single-camera tracking assigns stable IDs locally, subjects lack institutional identities. Running face recognition continuously is computationally prohibitive on CPU and raises privacy concerns if unconstrained.
  2. **Phase 4:** When multiple cameras cover overlapping fields of view in the same jail zone/cell, an altercation or contraband detection triggers duplicate alarm storms, repeated audio beeps, and multiple fragmented incidents in `incidents.db` from each camera independently.
- **Hypothesis:**
  1. **Opportunistic Face Binding (Phase 3):** Gated 1 Hz sampling on unbound tracks with $k$-of-$N$ multi-frame confirmation ($k=3$ of $N=5$, cosine threshold $\ge 0.363$), anti-collision enforcement, and a strict default-off privacy toggle (`face_recognition.enabled: false`) enables biometric identity binding on CPU without degrading 20–30 FPS real-time throughput.
  2. **Cross-Camera Zone Deduplication (Phase 4):** Centralizing decision trigger authority in `CameraFusion` with a 7.0-second cross-camera sliding window per zone suppresses redundant alert storms and merges multi-camera evidence into unified institutional incidents.
- **Invariants & Constraints:**
  - **Rule 8 (Dependency Freeze):** Use standard library + OpenCV's built-in `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`. No new third-party packages.
  - **Data Privacy Act of 2012 (RA 10173):** Default `face_recognition.enabled: false`. No persistent facial biometric feature dumps in git or code.
  - **Anti-Collision Invariant:** One inmate identity cannot be simultaneously bound to two distinct tracks in the same camera view.
  - **Rule 1 (Threading):** Thread safety via `with self.lock:` in `CameraFusion` and `OpportunisticFaceBinder`.

---

## 2. Scoped Tasks

### T1 — Phase 3: Opportunistic Face Binding Engine
- **Surface:** `monitor_app/tracking/face_binder.py`
- **Scope:**
  1. Implement `OpportunisticFaceBinder` wrapping `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF` using CPU execution.
  2. Support enrollment gallery: `enroll_subject(subject_id: str, name: str, face_img_or_embedding: np.ndarray)`.
  3. Gated 1 Hz probe logic: only probes unbound tracks whose bounding box exceeds $60\text{ px}$ height and confidence $> 0.5$.
  4. $k$-of-$N$ confirmation: tracks maintain a buffer of recent matches; identity is confirmed only when $\ge 3$ of the last 5 probes match with cosine similarity $\ge 0.363$.
  5. Anti-collision: if identity $X$ is active on track $A$, track $B$ cannot bind identity $X$.
  6. Privacy compliance: if `get_config("face_recognition", "enabled", False)` is false, immediately returns without running inference.
- **Test:** `tests/test_face_binding.py`
- **Gate:** Tests pass verifying enrollment, $k$-of-$N$ binding, anti-collision prevention, and disabled mode bypass.

### T2 — Phase 4: Cross-Camera Zone Deduplication in `CameraFusion`
- **Surface:** `monitor_app/fusion.py`
- **Scope:**
  1. Upgrade `CameraFusion` with zone alert state tracking:
     `active_zone_events: Dict[Tuple[str, str], Dict[str, Any]]` indexed by `(zone_id, event_type)`.
  2. Implement `resolve_zone(camera_id: str) -> str`: reads `config.yaml: fusion.camera_zones` or defaults to `f"Zone_{camera_id}"`.
  3. Implement `process_decision_trigger(packet, decision_engine, res) -> bool`:
     - Checks if `decision_engine.evaluate_trigger(packet)` is true.
     - Resolves `(zone_id, event_type)`.
     - If no active event exists in `zone_id` for `event_type` within `zone_dedup_window_s` (default 7.0s):
       Publishes `DECISION_TRIGGER` to EventBus and opens active zone event.
     - If an active event already exists in the same zone within the sliding window:
       Suppresses duplicate `DECISION_TRIGGER` (prevents alarm storm / duplicate audio beeps), updates active event's timestamp, and records corroborating camera evidence.
- **Test:** `tests/test_zone_fusion.py`
- **Gate:** Tests pass verifying single-camera pass-through, multi-camera zone alert suppression, and window expiration.

### T3 — Phase 4: Shift Trigger Authority in `central_inference.py`
- **Surface:** `monitor_app/central_inference.py`
- **Scope:**
  Update lines 760–795 to route decision trigger evaluation through `get_camera_fusion().process_decision_trigger(packet, decision_engine, res)` while keeping `FRAME_TICK` publishing intact.
- **Test:** `tests/test_zone_fusion.py` integration check.
- **Gate:** System regression tests pass.

### T4 — Verification, Pre-Flight Gate & Documentation
- **Surface:** `capstone_progress_report.md`, `CHECKLIST_AND_REMEDIES.md`, `changes_today.zip`
- **Scope:**
  1. Run `pytest tests/` (100% passing).
  2. Run `.agents/team/diff-scan.ps1` (GREEN).
  3. Verify diff with `agy-verifier`.
  4. Document changes in `capstone_progress_report.md` and bundle into `changes_today.zip`.

---

## 3. Edge Cases & Safety
1. **Model Missing Fallback:** If YuNet/SFace ONNX files are missing from disk, `OpportunisticFaceBinder` logs a graceful warning and disables face recognition without crashing the main application.
2. **Zone Configuration Fallback:** If a camera has no explicit zone entry in `config.yaml`, it automatically maps to its own isolated zone (`Zone_<camera_id>`), ensuring standard single-camera deployments work without any configuration changes.
3. **Sliding Window Expiration:** Active zone events are cleaned up when idle past `zone_dedup_window_s`, preventing memory accumulation.
