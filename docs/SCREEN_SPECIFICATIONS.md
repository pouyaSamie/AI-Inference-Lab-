# AI Inference Optimization Lab — PRD v2.1 Screen Blueprint

This document intentionally maps to the PRD v2.1 primary navigation. Read `docs/IMPLEMENTATION_STATUS.md` and adapt to phases actually implemented; do not introduce decorative inert routes.

| Navigation | Key content | Primary decisions |
|---|---|---|
| Overview | worker connectivity, GPU memory, active jobs, recent recipes, engine notices | investigate/reconnect/open study |
| Models | scoped inventory, model format/quant/shards/hashes, compatibility | inspect/select/verify |
| Engines | installed binaries, build fingerprint, capability differences | register/pin/inspect |
| Workers | GPU/device/driver, leases, contamination, last seen, health | choose/authorize preflight |
| Optimize | PRD six-step wizard, immutable plan review | start safely when implemented |
| Live Runs | stage timeline, trials, metrics, logs and control state | inspect and authorized controls |
| Compare | context curves, TTFT, throughput, VRAM, confidence, Pareto | interpret competing candidates |
| Recipes | effective profile/command, provenance, confidence, promotion | export, approve/pin if supported |
| Updates | release/build news, pin/defer/qualify and targeted reruns | change management |
| Settings | controller/service, no-egress/proxy, retention, secrets, refresh | safe configuration |

## Reference vertical slice — implement first

**Experiment run detail (Live Runs)**, *if backend is implemented*: capture status, metadata, recent trials, selected candidate metrics, per-context chart and contextual logs in one functional, resizable workspace:
- Title: experiment name or ID, objective, engine/model fingerprint, worker, created time, current authoritative state.
- Toolbar: refresh, view definition, copy ID; pause/cancel/resume only if supported by verified API and current status.
- Tab/panel A: stage & event timeline with replay gap/stale status.
- Tab/panel B: compact trial table with metric columns and failure/infeasible reasons.
- Main chart: per-context tokens/s (separate prompt/decode or explicit axes) with confidence, time window, unit and provenance.
- Right detail inspector: selected trial's effective args/config, memory, evidence, log, artifacts and note about comparability.
- Bottom/side connectivity: controller status, worker last heartbeat, SSE reconnect state.

If Phase 0/1 has no runnable experiment execution, choose the **Experiment Plan/Preflight** screen instead, label all fixtures/simulations, and do not fake a successful running job.

## Optimize wizard screen contract

Layout: left vertical step navigator (or compact stepper), central form, slim right **Validation and resource constraints** summary. Prevent navigation from silently dropping committed selections. Show every disabling reason.

1. Target: worker → engine/build → model; display exact mismatch explanation.
2. Objective: only supported three objective modes; concise explanation of what is optimized.
3. Context matrix: 4K/8K/16K/32K/64K/128K; predicted feasible/uncertain/infeasible distinct from measured outcomes.
4. Search strategy: Quick/Standard/Thorough, advanced caps collapsed unless requested.
5. Preflight: cached snapshot version and last verified time, blockers and warnings. `PREFLIGHT_REQUIRED` workflow/command ID if supported; stop submit.
6. Review/Submit: persisted digest, idempotency, confirmed run ID; never optimistic status.

Target PRD user outcome: an operator can start a valid experiment in <=10 UI interactions after initial registration/preflight, excluding system-level installation. Measure rather than claim.

## Compare detail

- Filter by compatible trials, engine/build, model, worker, objective, context and date.
- Chart + sortable data table of PP/TG/TTFT/VRAM with source and confidence; label non-comparable conditions before claiming leader.
- Show Pareto frontier where defined, measured failure/infeasibility and per-context winner; export reproducible report with no credentials.

## Service lifecycle and setup UX

- Initial setup explains that controller, optimizer and worker are persistent Linux **system services** (`systemd`) separate from Electron.
- UI may guide enrollment/connection but must not call privileged install scripts without explicit authorized operator action and PRD-compliant backend.
- Closing Electron terminates UI only, not benchmarking. A service restart has explicit recovery/reconciliation conditions; do not mark a lease transfer safe merely because heartbeat stopped.

## Screen state examples

- `controller_offline`: reconnect, timestamp of last known state, no speculative run outcomes.
- `worker_snapshot_stale`: preflight required, disable submit, show scan/command state when available.
- `insufficient_vram`: infeasible context with reason, no synthetic tokens/s.
- `engine_incompatible`: disabled model or engine selection with capability/version explanation.
- `run_simulated`: explicit Simulation banner; no 'real benchmark completed' claims.
- `trial_oom`: failed sample and associated evidence visible; no average fabricated from that sample.

## Prioritization

1. Audited app shell/theme/typography and existing screen fidelity.
2. Optimize target + context + preflight (phase-safe), plus exact status.
3. Experiment/run detail or phase-appropriate simulation summary.
4. Models, Engines and Workers inventory; Compare and Recipes as capabilities mature.
5. Updates/promotions and advanced operations only in validated phases.
