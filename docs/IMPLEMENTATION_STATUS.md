# Implementation status

Last updated: 2026-10-21.

This document records what is actually implemented and what was actually run.
It is not a roadmap and does not upgrade reconnaissance into benchmark evidence.

## 1. Scope status

| Area | Status | Evidence / boundary |
|---|---|---|
| Phase 0 engine reconnaissance | Partial | llama.cpp and Strata version/help are captured as sanitized fixtures. The installed builds were also probed live in Phase 2. No 4K/32K benchmark or second-GPU comparison exists. See `docs/PHASE_0_FINDINGS.md`. |
| Python `uv` workspace | Implemented | Six workspace packages resolve with `uv sync --all-packages`. |
| Frozen contracts | Implemented | Pydantic v2 frozen models in `lab_core`; canonical JSON/SHA-256 in `lab_core.ids`. Execution plans include `generated_files`. |
| Controller persistence | Implemented | FastAPI + SQLAlchemy 2.x + SQLite WAL + Alembic; initial revision `b151f9870480`. |
| Separate optimizer process | Implemented | `lab_optimizer` owns Optuna and a distinct SQLite URL. FastAPI imports no Optuna. |
| Durable worker protocol | Implemented | Poll, lease, ack, renewal, complete, idempotent replay, conflict `409`, lease expiry/requeue. |
| Engine adapters | Implemented, pure | llama.cpp and Strata help/JSON parsers, typed validation and plan builders, productionized against the installed builds. No subprocess/network/filesystem I/O; a test enforces imports. |
| Adapter conformance | Implemented, offline | Golden server/bench/status fixtures, option-line capability parsing, strict candidate types, split llama.cpp help checks, Strata profile de-duplication and generated-file digest tests. |
| Planning | Implemented, snapshot-only | Cached snapshots; stale/missing inventory returns `202 PREFLIGHT_REQUIRED` plus a queued `SCAN`. |
| Real Linux worker | Implemented | Observed engine/model discovery, hardware/GPU telemetry, SHA-256 cache, sandboxes, journal, GPU UUID `flock` leases, argv-only runner, crash recovery, cancellation. |
| Real command handlers | Implemented | `SCAN`, `PREFLIGHT`, `CLAIM_TRIAL`, `PAUSE`, `CANCEL`, `VERIFY_RECIPE`; `PROMOTE` is dry-run/idempotent only. |
| Phase 1 execution lane | Explicitly simulated | `lab-worker-sim` emits `simulated=true` and `measurement_status=simulated` only. |
| Real execution lane | Implemented, not fully exercised | `lab-worker` emits only `simulated=false`. Live inventory/scan smoke passed; no real preflight or trial was run yet. |
| Recipe validation | Implemented, rejects simulation | Simulated evidence returns `409`; incomplete/screening-only real evidence cannot qualify. |
| SSE | Implemented | Initial `snapshot`, sequenced events, `event.gap` for stale `Last-Event-ID`, bounded page endpoint. |
| Generated contracts | Implemented, checked in | OpenAPI, JSON Schema/manifest and strict TypeScript declarations; offline generation and drift gate. |
| systemd packaging | Authored, not installed | Three service units plus an environment template and security notes under `packaging/systemd/`. |
| Electron/React UI | Not implemented | Phase 6. |
| Benchmark corpus / statistical finalization | Not implemented | Phase 4/5. No validated real recipe exists. |
| Update intelligence / release qualification | Not implemented | Phase 7/8. |

## 2. Runtime components

- **`lab-api`** — controller entry point on `127.0.0.1:8787` by default.
  Persistent sessions, auth, planning, experiment lifecycle, command queue,
  optimizer outbox/inbox, SSE and runtime lease reconciliation.
- **`lab-optimizer`** — independent poller/worker for Optuna `ask/tell` work.
  It owns the Optuna database and never touches controller tables.
- **`lab-worker`** — real Linux worker. It enrolls, discovers configured engines
  and model roots, uploads snapshots, heartbeats, polls commands, leases GPU
  UUIDs, runs verified argv-only processes and completes typed evidence.
- **`lab-worker-sim`** — explicit simulated worker with deterministic inventory
  and observations; it never launches an engine or leases a GPU.

## 3. Real worker behavior

### Discovery

- Executes only configured `--version`/`--help` probes. Every binary is
  SHA-256 hashed and registered under a trusted ID. A changed engine digest fails
  closed and requires a fresh scan.
- Parses GGUF headers and shards, plus Strata pack manifests, under
  operator-approved roots. Discovery never writes to a model root.
- Hashes files into a persistent `(size, mtime_ns)` cache. The first full scan
  of the ~270 GiB model root is expensive; later scans reuse cached digests.
- A snapshot with missing hashes is still plannable but carries warnings. The
  real executor rejects preflight/trials until all model hashes are complete.

### Execution and ownership

- Commands run in per-command sandboxes beneath `LAB_WORKER_STATE_ROOT`.
- Processes use argv arrays (never a shell), a sanitized environment, a new
  process group/session and verified executable hashes.
- Cancellation and timeout terminate only the recorded process group. The
  worker never terminates an unowned GPU process.
- The append-only journal records command, lease, process group, start ticks and
  log paths. Recovery kills only a still-matching recorded group; interrupted
  commands are not invented as successful.
- GPU access uses per-UUID advisory `flock` files plus a JSON owner record.
  `CUDA_VISIBLE_DEVICES` is scoped to the lease. CPU-only llama candidates
  (`gpu_layers=0`) do not acquire a GPU lease.
- Long trials renew the same lease token/generation. A lease timeout alone does
  not authorize another worker to take over a live engine.

### Evidence boundaries

- llama.cpp trials collect native `llama-bench` metrics where present and a
  streaming `/v1/chat/completions` serving lane. Missing metrics stay missing;
  native-only evidence is `screening_only`.
- The engine adapter parses server `/props` or `/v1/status` for context identity
  and engine fields. Client-observed TTFT/usage keep precedence; a status
  document is not treated as measured peak VRAM or throughput.
- Preflight starts a CPU-offload (`--n-gpu-layers 0`) server at the highest
  supported requested context and records the effective context. This proves
  allocation at that context, **not** GPU residency. Lower requested contexts
  inherit that proof explicitly; GPU fit is measured by trials.
- Strata full-context proof is deferred to the Phase 4 serving harness because
  the installed build lacks calibration commands. The result is
  `inconclusive`, never fabricated.
- Real observations always have `simulated=false`; simulation can never produce
  a validated recipe.

## 4. Verification actually performed

The following commands were run in this workspace on 2026-10-21 and produced the
results shown. They must be re-run after any change.

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 106 files already formatted

uv run mypy python
# Success: no issues found in 90 source files

uv run pytest -q
# 33 passed in 7.59s

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# tsc --noEmit -p tsconfig.json: passed
```

`systemd-analyze verify packaging/systemd/lab-*.service` parsed all three units
and reported only that the deployment paths
(`/opt/ai-inference-lab/.venv/bin/lab-*`) do not exist on this host. The units
were **not** installed, enabled or started.

### Live discovery probe

The installed engines were probed through the real worker discovery code:

```text
ENGINE llamacpp 0.7.0-dev build 701 commit dd002b91f sha256 f0f8a33ee87c...
  26 descriptors; server and bench help hashes recorded separately; no warnings
ENGINE strata   0.1.44.1  build 0.1.44.1 sha256 fa29349e3eaa...
  19 descriptors; version/help read from stderr; no warnings
```

The adapter conformance suite parses the committed installed-build fixtures and
checks that every emitted server flag appears in server help, every emitted
native flag appears in `llama-bench` help, invalid candidate types fail, Strata
profiles contain no duplicated managed flags and generated-file digests match.
It does not launch an engine.

The configured model root produced 8 artifacts without hashing: 6 GGUF models
(GLM-4.7-Flash-Q4_K_M, Qwen3.8-27B-UD-IQ4_XS,
Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp, gemma-4-12B-it-QAT-Q4_0,
Qwen3.6-35B-A3B-UD-Q4_K_M, Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M)
and 2 Strata packs. All were correctly reported `verified=false` because
hashing was disabled for the probe. No weights were modified.

### Live controller/worker smoke

A temporary controller (loopback port 8790, temporary SQLite stores under
`/tmp/opencode/lab-phase2`) was migrated and started in `LAB_EXECUTION_MODE=real`.
A real `lab-worker` with a separate state root:

- registered with the enrollment credential;
- uploaded a real hardware/engine/model snapshot;
- sent heartbeats;
- polled, acked and completed a durable `SCAN` command
  (`cmd_3e8f46b022ff472a9d6a7c8ea97b7772`) in about 1.5 s with hashing disabled;
- returned snapshot revision 5 to the controller.

This proves the outbound command path, lease/ack/complete flow and real
inventory upload. It does **not** prove a real preflight, trial or recipe.

### Automated suite

The suite starts a live loopback controller, simulated worker and optimizer with
temporary stores. It covers planning and `PREFLIGHT_REQUIRED`, experiment and
Optuna lifecycle, simulated trials, recipe rejection for simulation, idempotency
conflicts, SSE gap replay, and command lease/ack/completion resilience. Phase 2
unit coverage uses a synthetic GGUF file, the trusted Python interpreter, fake
probe scripts, GPU lease exclusivity, runner success/timeout/cancel and journal
crash recovery. Phase 3 adds offline golden conformance tests for installed
llama.cpp server/bench output, Strata stderr help/status output, typed candidate
rejection, profile de-duplication and generated-file digest checks. No test
requires a GPU, downloaded weights or a live engine.

## 5. What is not proven

These are intentional boundaries, not hidden gaps:

- No real `PREFLIGHT` or `CLAIM_TRIAL` has been executed end-to-end. The model
  root has not been fully hashed (about 270 GiB).
- No real 4K/32K/128K latency, VRAM, quality or thermal measurement exists.
- No second GPU (for example L40S) comparison exists; only the RTX 3060 is
  installed.
- Strata full-context proof is `INCONCLUSIVE` pending the Phase 4 serving
  harness. Its native benchmark command is not exposed by the installed build.
- Model discovery records the Strata pack and a `native: true` marker but does
  not yet resolve the source GGUF shard path. The adapter therefore refuses to
  stringify that marker into `--native True`; it emits `--native SHARD1` only
  when an explicit `native_shard` is present. The unobserved `--mtp` form is not
  emitted.
- `PAUSE` currently stops the active trial at the process-group boundary; it is
  not a resumable checkpoint. Safe-boundary pause is a Phase 5/lifecycle item.
- Simulated throughput, VRAM/telemetry and OOM values are deterministic test
  data, not measurements.
- No load test at 1,000 concurrent polling workers is claimed.
- TLS termination, remote authentication, the Electron UI, update intelligence
  and release qualification do not exist yet.
- Optuna and controller writes are not atomic; recovery is deterministic and
  conservative rather than a two-phase commit.
- The systemd units are authored and syntax-checked only; they are not installed
  or enabled.

## 6. Generated artifacts

Committed and regenerable:

```text
contracts/openapi.json
contracts/contracts.schema.json
contracts/manifest.json
packages/client-contracts/src/openapi-types.ts
packages/client-contracts/src/index.ts
```

Generation source is Pydantic/FastAPI. Do not hand-edit generated files. Run:

```bash
pnpm generate:contracts
pnpm contracts:check
```

## 7. Quick start status

The documented quick start is in `README.md` and `AGENTS.md`:

```bash
cp .env.example .env
# replace every CHANGE_ME secret with a 16+ character random value
uv run --env-file .env alembic upgrade head
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
uv run --env-file .env lab-worker        # real lane
# uv run --env-file .env lab-worker-sim # explicit simulation lane
```

`/health` is public. Operator, enrollment, worker and optimizer
routes require the corresponding bearer token. The real worker needs readable
engines/models and GPU access; the simulated lane needs neither.

## 8. Next gate

Phase 3 is complete at the adapter/contract boundary and committed locally.
Phase 4 adds the benchmark corpora, real serving/full-context work and evidence
collection. The open Phase 2/3 evidence items (full model hashing, a real
preflight, one real low-impact trial and Strata native-shard resolution) must be
executed before any Phase 5 recipe can be considered. See `docs/NEXT_STEPS.md`,
`docs/progress/PHASE_2_REPORT.md` and `docs/progress/PHASE_3_REPORT.md`.
