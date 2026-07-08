> **Local council** — these perspectives all come from Claude playing different roles, not from different AI vendors. Treat agreement as a shared starting point to pressure-test, not as independent confirmation.

## 🗳️ Performance Optimizer

**Position on #3 (MoveNet Execution Provider):**
Keep MoveNet strictly on the CPU. An RTX 2050 with 4GB VRAM is severely constrained for a 4-camera real-time pipeline. YOLO models (especially if not heavily quantized) consume significant VRAM. If MoveNet is moved to the GPU, we risk VRAM fragmentation and out-of-memory (OOM) errors, or worse, silent memory swapping to system RAM which will exponentially worsen the queue overflow. MoveNet is specifically designed to be lightweight enough for CPU execution.

**Position on #4 (Flickering Fix):**
Option B (N-frame hold) is the superior choice for performance and stability. Lowering the threshold (Option A) will introduce false positives, which triggers downstream disk I/O (incident recording, database writes), effectively creating a different kind of performance bottleneck. An N-frame visual hold in memory is computationally free and stabilizes the pipeline.

## 🗳️ Maintainability Advocate

**Position on #3 (MoveNet Execution Provider):**
I agree with keeping MoveNet on the CPU based on the hardware constraints, but we must address *how* it's implemented. Hardcoding `tf.config.set_visible_devices([], 'GPU')` deep in `ai_engine.py` is an anti-pattern. This should be exposed in `config.yaml` as an execution provider preference (e.g., `movenet_device: "cpu"`), making the intentional tradeoff obvious to future maintainers.

**Position on #4 (Flickering Fix):**
Option B introduces new stateful logic. We must be careful not to reinvent tracking. If we implement an N-frame hold, it should be a clean, generalized `debounce_frames` parameter in the `config.yaml` under the UI/Alerting section. However, Option A (lowering the threshold) is purely a configuration tweak and requires zero code changes. From a strict maintainability standpoint, tweaking configuration is always preferable to adding state machine complexity, unless the configuration change drastically breaks accuracy.

## 🗳️ Devil's Advocate

**Position on #3 (MoveNet Execution Provider):**
Everyone is assuming YOLO is the bottleneck or that VRAM will instantly run out, but look at the metrics! "25% CPU / 15% GPU". If YOLO is only using 15% of the GPU, the GPU is practically sleeping! If the CPU is the actual bottleneck causing the 15-frame queue backlog (because it's struggling to run 4 concurrent MoveNet inferences), keeping MoveNet on the CPU is exactly what is killing our FPS. We should test running MoveNet on the GPU. If it OOMs, we roll it back. If it fits, our queue backlog disappears. Don't let fear of VRAM limits prevent testing the obvious solution to CPU throttling.

**Position on #4 (Flickering Fix):**
Why are we choosing between A and B when the actual solution was to fix ByteTrack? We bypassed ByteTrack because it assigned the wrong IDs, and now we're forced to write our own rudimentary tracker (an N-frame hold is just a primitive tracker!). If we must choose, Option B is safer. Lowering the threshold (Option A) on an institutional security system to catch a flickering knife will absolutely result in phantom alerts, flooding the operator dashboard.

***

# Synthesis

**Shared starting points:**
All roles recognize that the 4GB VRAM limit on the RTX 2050 is the primary constraint defining the architecture.

**Genuine tensions:**
- **The Bottleneck Paradox:** The Performance Optimizer fears moving MoveNet to the GPU will crash the system due to VRAM exhaustion. The Devil's Advocate points out that if the GPU is only at 15% utilization and the CPU is saturated, refusing to use the GPU is precisely why the queue is full.
- **Tracking vs. Debouncing:** The Maintainability Advocate wants to avoid adding custom state logic to replace ByteTrack, while the others acknowledge that lowering the threshold (Option A) will likely flood the system with false positives.

**Blind spots:**
If we implement Option B (N-frame hold), we are effectively building a custom tracker. We must ensure this N-frame hold applies *only* to visual rendering and maintained incident states, without accidentally triggering *new* incidents if the box reappears.

**Suggested direction:**
1. **For #4 (Flickering):** Implement **Option B** (N-frame hold). It is the consensus pick because false positives on contraband detection are unacceptable in a jail monitoring system. We will add a small `hysteresis_frames` variable to the `MAINTAINED` state logic rather than lowering the threshold.
2. **For #3 (MoveNet GPU/CPU):** Treat this as an empirical test. We should move the hardcoded `tf.config` setting into `config.yaml` as requested by Maintainability. Then, we can run one test with it enabled on GPU to settle the Devil's Advocate's theory. If it OOMs, we revert to CPU permanently knowing we made the right call.
