# Phase 2 backlog — real worker execution and evidence

Status: planning only. Nothing in this file is implemented in the Phase 1 tree.

Phase 2 must preserve the Phase 1 contract boundary:

- FastAPI never runs Optuna or engine work.
- Controllers never receive inbound worker connections.
- Adapters remain pure; the worker runner owns all I/O.
- Simulated evidence remains distinguishable and cannot validate a recipe.
- Controller and optimizer stores remain separate.

## P0 — prerequisites and evidence closure

### 2.0 Re-run Phase 0 measurements

- Execute the PRD's minimal real 4K/32K measurement on the installed RTX 3060
  and on a second supported GPU when available (for example L40S).
- Capture exact binary hashes, model file hashes, command lines, timings,
  startup memory and post-context memory.
- Record failures and OOM stage explicitly; never convert an OOM into a
  successful measurement.
- Add a quality/correctness corpus and acceptance threshold before treating an
  optimization result as a candidate.
- Keep fixtures sanitized; no prompts, private paths or user data.

Exit: real evidence artifacts exist and are reproducible by a second run.

### 2.1 Engine/version conformance expansion

- Extend llama.cpp fixtures when the installed build changes.
- Add llama-server readiness, health, structured request and shutdown handling.
- Define supported Strata pack/profile semantics from the installed build.
- Keep unobserved flags unsupported; fail closed with typed errors.
- Add property tests for argv quoting, path handling and JSON parsing.

Exit: conformance suite passes for every supported engine build/profile.

## P1 — real worker runner

### 2.2 Worker-owned process supervisor

- Add an engine runner only in `lab_worker`, never in `lab_adapters`.
- Launch with typed `ExecutionPlan` argv plus explicit environment and working
  directory.
- Create a process group/session; terminate the whole group on cancel/timeout.
- Enforce startup, load, prefill and generation timeouts.
- Capture bounded stdout/stderr, exit code, signal and readiness timeline.
- Never log prompts, tokens or complete environment dumps.

Exit: start/cancel/timeout/crash tests pass without leaking child processes.

### 2.3 GPU lease ownership

- Introduce a worker-local GPU lease record with exclusive allocation per device.
- Bind lease to worker, experiment, candidate, command generation and process
  group.
- Reconcile stale leases on worker restart before accepting new work.
- Preserve a “lease expiry is not process death” rule; a live orphan must be
  detected and reaped, not double-claimed.
- Add a controlled fake-GPU backend for CI; no test requires physical hardware.

Exit: no two live candidates own one GPU lease; restart recovery is tested.

### 2.4 Real command handlers

- `SCAN` / `PREFLIGHT`: collect hardware, engine and model facts with bounded
  probes and produce a revisioned inventory snapshot.
- `CLAIM_TRIAL`: execute the real benchmark/request plan, preserve raw evidence,
  and return typed observations.
- `PAUSE` / `CANCEL`: signal the process group and report stage.
- `VERIFY_RECIPE`: run the PRD verification protocol against real evidence.
- `PROMOTE`: promote only after verification gates.
- Preserve Phase 1 idempotency semantics for every terminal completion.

Exit: all handlers are replay-safe; conflicting completions return `409`.

## P1 — measurement correctness

### 2.5 Workload and tokenizer corpus

- Implement tokenizer-backed prompt construction in `lab_bench` or a new pure
  planning package.
- Record tokenizer ID, token counts, workload digest and seed.
- Cover 4K and 32K plus the full-context boundary contexts from the PRD.
- Keep corpora immutable and versioned.

Exit: the same case/seed produces the same workload digest across runs.

### 2.6 Benchmark protocol

- Measure warm-up separately from retained repetitions.
- Record input/output tokens, throughput, TTFT, inter-token latency, peak and
  steady memory, and measurement validity.
- Detect server readiness before timing.
- Mark contaminated, truncated or partial runs explicitly.
- Add quality gates for deterministic correctness samples where supported.

Exit: evidence parser rejects incomplete or contaminated evidence.

### 2.7 Feasibility ledger

- Persist context feasibility outcomes per engine/model/GPU/profile:
  feasible, infeasible, unknown, OOM stage, evidence IDs.
- Make infeasible/unknown states durable so they are not retried blindly.
- Support “all contexts infeasible” and “no six-context winner” outcomes.
- Bind outcomes to hashes and probe configuration.

Exit: deterministic feasibility queries and no fabricated winners.

## P2 — optimization and recipes

### 2.8 Optimizer study lifecycle

- Validate conditional search-space behavior and bounded trial budgets.
- Add pruning and constraint-aware rejection in the optimizer process.
- Improve cross-store reconciliation for controller crash/Optuna commit gaps.
- Add retry/backoff telemetry and study closeout rules.
- Preserve one durable trial per candidate intent.

Exit: crash-injection tests show no duplicate or invented trial.

### 2.9 Statistical finalization

- Implement the PRD's repetition requirements, confidence intervals and
  outlier/validity rules.
- Separate exploratory candidates from statistically validated winners.
- Record every excluded sample and its reason.

Exit: a finalist is reproducible from persisted raw evidence.

### 2.10 Recipe validation and promotion

- Build deployment recipes only from `ValidatedEvidence`.
- Reject simulated, stale, missing-hash or contaminated evidence.
- Verify a recipe by launching from the recorded plan and rechecking identity.
- Preserve promotion audit events and rollback metadata.

Exit: at least one real verified recipe in a lab run; simulated input remains
impossible to promote.

## P2 — control plane and UI

### 2.11 Electron/React client

- Add the PRD information architecture: workers, wizard, live experiments,
  results, comparison and recipes.
- Use generated TypeScript contracts; do not hand-maintain API types.
- Drive live state from SSE with snapshot/gap handling.
- Add a secure preload bridge and no direct Node access from the renderer.

Exit: the UI can run a simulated experiment end-to-end; real runs follow only
after the worker runner is stable.

### 2.12 Operational packaging

- Add systemd units for controller, optimizer and worker.
- Add structured logs, metrics, health probes and retention/backup procedures.
- Add TLS or authenticated remote transport for non-loopback deployments.
- Add secret rotation, worker revocation and audit coverage.
- Add migration runbooks for controller and Optuna stores.

Exit: clean-host install/upgrade/rollback runbook is tested.

## P3 — scale and hardening

### 2.13 Load and resilience

- Test many polling workers, large command queues and SSE backpressure.
- Add retained-event pruning policy and replay-floor tests.
- Add fault injection for lost completions, duplicate polls, controller restart,
  optimizer restart, worker restart and disk-full.
- Measure controller latency while optimizer/worker activity is high.

Exit: documented limits with reproducible tests.

### 2.14 Contract and schema evolution

- Add version negotiation and backward-compatibility tests.
- Decide whether to retain the dependency-free TS generator or adopt a
  pinned offline `openapi-typescript` flow.
- Keep drift checks in CI and fail closed on unknown migrations/versions.

Exit: additive schema changes and rejection of incompatible peers are tested.

## Suggested order

1. 2.0 evidence closure.
2. 2.1 conformance and 2.2 process runner.
3. 2.3 GPU leases and 2.4 real handlers.
4. 2.5/2.6 workload and benchmark protocol.
5. 2.7 feasibility ledger.
6. 2.8 optimizer hardening and 2.9 statistics.
7. 2.10 recipes.
8. 2.11 UI and 2.12 packaging.
9. 2.13/2.14 hardening.

Do not start with recipes or UI claims: real measurement and process ownership
are the load-bearing dependencies.

## Non-goals for Phase 2 entry

- Treating simulated values as performance evidence.
- Running Optuna inside FastAPI.
- Sharing one SQLite file between controller and optimizer.
- Adding engine execution to `lab_adapters`.
- Claiming 128K feasibility from headers or a short benchmark.
- Shipping a benchmark winner without quality gates.
