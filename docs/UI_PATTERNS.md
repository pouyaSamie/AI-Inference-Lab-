# AI Inference Optimization Lab — UX Contracts

The authoritative PRD, generated API contracts and implementation status define actual application capabilities. Never infer a runnable experiment from the mere presence of a planning or simulation API.

## Connectivity/status header

- Show controller endpoint/status, time since last verified response, local/offline state, active worker summary and applicable warnings.
- Differentiate *UI disconnected* from *controller stopped* from *worker unreachable* from *run failed*; don't infer one from the others.
- SSE stream may be interrupted: reflect reconnection and replay/backfill status without marking jobs failed or completed. Never guess terminal state from a closed Electron window.

## Model/engine/worker inventory

- Model: identity/hash, format (GGUF vs Strata pack), quantization, shard integrity, tokenizer/compatibility where known, local worker, available revision.
- Engine: exact executable path, build fingerprint/commit, adapter capability snapshot, last qualified status, supported flags.
- Worker: stable ID/GPU UUID, VRAM/RAM/CPU/kernel/driver, owner/lease status, heartbeat time, idle/contaminated/unavailable distinctions. Never expose a control unsupported by backend.
- Discovery uses permitted roots only; distinguish 'not scanned', 'not found', 'access denied', 'unsupported format', 'snapshot stale' and 'verified'.

## Six-step Optimize wizard (PRD v2.1)

1. **Target:** choose supported Linux worker/GPU, installed `llamacpp` or `strata` engine, compatible model/build/revision; disabled choices explain precise incompatibility.
2. **Objective:** Balanced / Maximum Generation / Maximum Prompt Processing, mapped to contract values `balanced`, `generation_max`, `prefill_max`; show weighting/scoring transparently.
3. **Contexts:** selectable 4K, 8K, 16K, 32K, 64K, 128K. Label predicted feasibility **projection** until measured/preflight verified. An infeasible context may be retained as an analysis target but must never become fictional performance data.
4. **Search depth:** Quick / Standard / Thorough with optional advanced caps (trials/time/GPU-hours, minimum headroom, quality policy, repeats/flags) only if backend accepts them.
5. **Preflight:** immutable snapshot identity/time, binary/model ownership, estimated resource use, worker capability, safety conflicts, candidate limit and warnings. On `PREFLIGHT_REQUIRED`, show queued preflight action ID and **do not** offer a runnable plan from stale/unknown snapshots.
6. **Submit:** review immutable experiment configuration/digest, indicate exact action and risk, submit through idempotent server API, show confirmed job ID and navigate to Live Runs. A controller refusal must retain user inputs with remediation details.

Never simulate submit success in production. If the implementation phase allows only plan/simulation, visually label it **Simulation / Not executable** and disable actual launch.

## Live Runs

- Stage strip and trial grid: phase, candidate, context, repetitions, assigned worker, start/update time, outcome, failure reason, persisted evidence.
- Controls pause/cancel/resume/retry only if verified implemented, safe, authorized; action display distinguishes 'requested' from 'acknowledged'.
- Live telemetry has units, aggregation windows, gap indicators and timestamp; throttle chart updates to avoid disturbing benchmark accuracy.
- Logs use virtualization/line limits and scrubbed output, with copy/export after permission checks. Dangerous or destructive controls carry appropriate confirmation.
- Closing desktop UI does **not** terminate job; wording must reinforce controller-owned durable run semantics.

## Comparison

- Comparable trials must match/declare workload, prompt-processing vs token-generation semantics, model identity/tokenizer/quantization, engine build, hardware, context length, sampling and metric definitions. When not comparable, separate series and label reasons; don't declare a winner across incomparable data.
- Compare per-context prompt processing, generation throughput, TTFT, VRAM, quality and confidence. Show failure/infeasible sample counts.
- Aggregate stats transparently: number of repetitions, confidence interval and normalization method if provided. Surface insufficient evidence.
- Exports must include identity and provenance (build/model fingerprint, hardware, flags and effective context) and no secret material.

## Recipes and promotions

- Recipe is an evidence-backed, reproducible profile with exact command/config, hashes, constraints, measured result summary, confidence, run links and approval/promotion history.
- Make copy/export affordances predictable; show diff vs currently pinned recipe; never edit production configs or restart services from the renderer.
- Promotion/rollback is server-authorized and approval-gated per PRD; do not imply deployment on successful download/export.

## Updates & Settings

- Updates use opt-in connectivity; show last checked/available/qualified vs recommended distinctly. Offline mode is a normal operating mode.
- Settings expose local controller URL, refresh budget, retention and configured proxy/no-egress policy, secrets via secure mechanisms, and authorized directories. Default no internet dependency or silent telemetry.

## Universal states

For every important component: populated; truly empty; loading; stale/offline; partial telemetry; authorization denied; validation failure; server error; cancellation requested; failed/infeasible outcome. Always show meaningful next actions, not decorative blank boxes. Use system terminology consistently. Never invent TTFT or GPU metrics when telemetry is missing.
