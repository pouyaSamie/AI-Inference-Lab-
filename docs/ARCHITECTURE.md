# Architecture — Phases 0–7: foundation, worker, adapters, workloads, finalization, desktop UI and release intelligence

Status: Phase 1 is complete and verified. Phase 2 adds a production Linux worker
with observed engine/model discovery, native process execution, GPU UUID leases,
journals, sandboxes and a real executor. Phase 3 productionizes the two adapters
against the installed llama.cpp and Strata builds and adds offline conformance
tests. Phase 4 adds tokenizer-backed workloads and Strata source-shard identity.
Phase 5 adds paired baselines, retained primary samples and deterministic
statistical finalization. Phase 6 adds the local Electron/React operator UI
through a narrow, validated main-process bridge. Phase 7 adds offline release
metadata import, deterministic impact classification, durable pin/defer
decisions and frozen paired A/B records that never approve or install an update.
The simulated lane remains separate and its evidence can never qualify a recipe.

## 1. Process topology

```text
operator / Electron renderer / optional browser companion
        │  HTTP + Bearer + SSE (loopback in local mode)
        │  Electron: renderer → validated IPC → main-process proxy
        ▼
┌──────────────────────────────────────────────┐
│ FastAPI controller (lab_api)                 │
│ auth, planning, lifecycle, outbox/inbox,     │
│ leases, SSE, recipe validation, migrations   │
│ controller SQLite WAL                        │
└───────┬───────────────────────────┬──────────┘
        │ authenticated internal    │ outbound worker polling
        │ HTTP (optimizer token)     │ (worker token)
        ▼                           ▼
┌───────────────────────┐   ┌──────────────────────────┐
│ lab_optimizer         │   │ lab_worker / sim worker  │
│ Optuna RDBStorage     │   │ command ack/complete     │
│ optuna SQLite WAL     │   │ real process ownership   │
│ TPE ask/tell          │   │ or simulated fixtures    │
└───────────────────────┘   └──────────────────────────┘
```

The real worker has no inbound listener. It probes only configured engine
paths, reads model metadata under configured roots, writes only beneath its
state root, and launches argv-only subprocesses in dedicated process groups.
The pure adapters still translate typed plans; they never spawn processes or
touch files.

The controller never imports Optuna, never starts a worker process and never
spawns an engine. The optimizer is a separate deployable process. The worker
is a separate process that initiates every connection to the controller; the
controller needs no inbound route to a worker.

## 2. Package responsibilities

| Package | Responsibility | Must not |
|---|---|---|
| `lab_core` | frozen Pydantic models, canonical JSON/hash, enums, state transitions, objective scoring, paired bootstrap and finalization | perform I/O, import FastAPI/Optuna, hold process handles |
| `lab_bench` | deterministic context/workload matrix and normalization | launch engines or read prompt corpora |
| `lab_adapters` | pure CLI/JSON translation, capability parsing, candidate validation, execution-plan construction | subprocess, network, filesystem, hardware probe |
| `lab_updates` | release metadata contracts, deterministic impact classification, capability diff and paired A/B evaluation | network, subprocess, filesystem, installed-binary access, upgrade approval |
| `lab_api` | FastAPI, auth, persistence, planning, lifecycle, command queue, optimizer outbox, release notices, SSE, migrations | import Optuna, run benchmark work on the event loop |
| `lab_optimizer` | supervised Optuna process, durable request client, study reconciliation | touch the controller DB directly or execute engines |
| `lab_worker` | enrollment, hardware/engine/model discovery, heartbeat/inventory, polling, lease ack/renew/complete, sandboxed process runner, GPU UUID leases, journal recovery, real or simulated executor | trust inbound commands, fabricate real metrics, modify installed models/engines, kill unowned processes |

Contract source of truth: `lab_core` modules and FastAPI routes. Committed
generated artifacts: `contracts/openapi.json`, `contracts/contracts.schema.json`,
`contracts/manifest.json`, `packages/client-contracts/src/openapi-types.ts`.

## 3. Persistence

Standalone mode uses two independent SQLite files in WAL mode:

- `var/controller.sqlite3` — controller-owned durable state;
- `var/optuna.sqlite3` — Optuna `RDBStorage`, owned only by the optimizer.

`Settings` rejects equal URLs and equal SQLite paths. Controller migrations are
Alembic-managed (`python/lab_api/migrations`). The current schema creates 23
tables, including:

- identity/inventory: `workers`, `worker_snapshots`, `gpu_devices`, engine/model
  registry rows;
- experiments: `experiments`, `studies`, `candidates`, `observations`,
  `recipe_rows`/recipes and contexts;
- release intelligence: `release_notices`, `release_assessments`,
  `engine_comparisons`;
- durability: `worker_commands`, `optimizer_requests`, `idempotency_records`,
  `job_events`, `system_events`, `replay_floors`, `feasibility_observations`,
  `store_reconciliation`, `audit_events`.

Controller writes are short transactions. No controller transaction spans a
worker or optimizer network call. SQLite connections set `journal_mode=WAL`,
`busy_timeout`, and `synchronous=FULL` by default.

## 4. Planning is snapshot-only

`POST /api/v1/experiments/plan`:

1. loads the registered worker and its latest cached snapshot;
2. checks worker heartbeat freshness, snapshot age and revision match;
3. resolves engine/model identity from the cached snapshot;
4. builds an immutable `ExperimentSpec`/`ExperimentPlan` and a pure adapter
   search space;
5. returns `200 READY`, or `202 PREFLIGHT_REQUIRED` with a typed reason and a
   queued durable `SCAN` command.

No synchronous worker RPC, binary probe or model read occurs in this route.
Staleness reasons include `NO_WORKER_HEARTBEAT`, `WORKER_OFFLINE`, `NO_SNAPSHOT`,
`SNAPSHOT_STALE`, `SNAPSHOT_REVISION_MISMATCH` and `WORKER_DISABLED`.
The plan response carries a `PHASE_1_SIMULATED_EXECUTION` warning in simulated
mode and `MODEL_HASHES_INCOMPLETE` when the snapshot lacks strong model hashes.
Real-mode planning still reads cached inventory only.

## 5. Worker command protocol

Worker endpoints (all authenticated with the issued worker token):

```text
POST /api/v1/workers/register                  enrollment token
POST /api/v1/workers/{id}/snapshot             inventory revision
POST /api/v1/workers/{id}/heartbeat
POST /api/v1/workers/{id}/commands/poll
POST /api/v1/workers/{id}/commands/{cid}/ack
POST /api/v1/workers/{id}/commands/{cid}/renew
POST /api/v1/workers/{id}/commands/{cid}/complete
```

Commands are `SCAN`, `PREFLIGHT`, `CLAIM_TRIAL`, `PAUSE`, `CANCEL`,
`VERIFY_RECIPE`, `PROMOTE`. A poll returns a `WorkerCommandLease` with a random
lease token, generation, expiry and the typed command. The controller stores
only a hash of the lease token.

State machine:

```text
pending ──poll──▶ leased ──ack──▶ acknowledged ──complete──▶ completed
   ▲                 │                     │                    │
   └──expiry/retry───┘                     └──terminal failure──┘
```

- Completion requires the same worker, lease token and generation.
- A terminal completion replayed with the identical result returns
  `idempotent_replay=true`; a different result is a `409`.
- Expired leases are returned to `pending` with an incremented generation until
  the attempt limit. A worker cannot complete a command it does not own.
- Controller-side lease expiry is reconciled by the runtime scheduler; a lease
  timeout alone does not authorize taking over a live engine.
- A running worker renews its lease with the same token and generation. The
  controller caps the expiry at `worker_lease_max_seconds`; renewal never changes
  the lease generation.

The simulated executor handles all command types and emits deterministic
observations with `simulated=true`. The real executor handles `SCAN`,
`PREFLIGHT`, `CLAIM_TRIAL`, `PAUSE`, `CANCEL`, `VERIFY_RECIPE` and dry-run
`PROMOTE`; promotion remains operator-owned.

## 6. Optimizer protocol

FastAPI writes `optimizer_requests` rows with kind `CREATE_STUDY`, `ASK`,
`TELL`, `RECONCILE` or `PING`, a stable request ID and an idempotency key. The
optimizer polls authenticated internal endpoints:

```text
POST /api/v1/internal/optimizer/heartbeat
POST /api/v1/internal/optimizer/requests/poll
POST /api/v1/internal/optimizer/requests/{id}/complete
GET  /api/v1/internal/optimizer/health
```

The optimizer uses its own SQLite database for Optuna studies. Study creation is
idempotent by study name. `ask` is bounded by `max_proposals`/attempt limits.
`tell` records a final trial outcome; replaying the same tell is
`already_finalized` with the original value. The controller applies result side
effects (candidate creation, observations, stage transitions) only after a
durable completion. Cross-store reconciliation is explicit and must not invent
scores.

Every optimizer request carries `schema_version`, `protocol_version`,
`request_id`, `study_id` and `idempotency_key`. `study_id` and candidate IDs are
stable identifiers; canonical digests bind parameters and workload identity.

## 7. Events and SSE

Every durable experiment transition appends a `job_events` row with a
monotonically increasing per-experiment sequence. `replay_floors` records the
oldest retained sequence for an experiment.

`GET /api/v1/experiments/{id}/events` streams:

1. a `snapshot` event containing current status and recent events;
2. subsequent durable events with `id: <sequence>`;
3. keepalive comments when idle.

If `Last-Event-ID` (header or query) is below the replay floor, the stream emits
`event.gap` followed by a fresh `snapshot`, so a UI can reset rather than apply a
non-contiguous history. `GET /events/page` provides bounded replay with
`replay_floor`, `last_event_id` and `has_more`. Duplicate suppression is by
sequence. The stream uses a stateless operator credential check and does not hold
a DB session between events.

## 8. IDs, digests and models

Boundary models are frozen Pydantic v2 models. `lab_core.ids` provides:

- canonical JSON (sorted keys, compact separators, stable scalar encoding);
- SHA-256 helpers;
- stable prefixed IDs derived from canonical content.

Stable IDs are derived from immutable content (worker/snapshot identity,
experiment spec/plan digest, command idempotency key, candidate/workload
identity). Timestamps are UTC. Candidate fingerprints bind engine hash, model
hash, worker profile, context, workload digest and parameters.

## 9. Authentication and authorization

- Operator token: control plane and status; required for planning, experiments,
  recipes and operator views.
- Enrollment token: only worker registration.
- Worker token: issued once, stored as a peppered hash, scoped to that worker.
- Optimizer token: only internal optimizer heartbeat/poll/complete.

All tokens are compared with constant-time comparison. SSE uses a separate
stateless operator dependency. The controller never exposes the optimizer DB or
worker state files.

## 10. Runtime scheduler and recovery

The controller runtime scheduler periodically expires worker and optimizer
leases, marks offline workers, reconciles job state and emits durable events.
It runs in the FastAPI lifespan task, but never performs benchmark or Optuna
work. Worker and optimizer clients retry transient transport errors with
bounded exponential backoff and stable idempotency keys.

Recovery rules:

- a worker restart re-registers/loads its state token and uploads a higher
  inventory revision;
- an expired command lease is requeued with a new generation and new token;
- an authoritative terminal completion is replay-safe;
- an optimizer restart reconciles pending requests against Optuna study state
  before issuing new suggestions;
- no silent double trial issuance, no fabricated zero-throughput OOM value.

## 11. Real worker discovery and execution (Phase 2)

- **Engine discovery** executes only the configured `--version`/`--help` probes,
  records SHA-256 for every binary, and parses capabilities through the pure
  adapter. A changed binary invalidates a command plan instead of silently
  running it.
- **Model discovery** reads GGUF headers and Strata pack manifests under
  operator-approved roots. SHA-256 hashing uses a persistent `(size, mtime_ns)`
  cache; nothing under a model root is written.
- **Hardware discovery** uses `/proc`, `psutil` and `nvidia-smi`; it records GPU
  UUID, PCI bus, driver, VRAM, utilization, temperature and external contaminant
  processes. It never terminates a process it does not own.
- **Execution** uses argv arrays, a sanitized environment, a per-command
  sandbox, an owned process group and verified executable hashes. Server
  readiness can be an HTTP check; cancellation and timeout terminate only the
  recorded process group.
- **GPU leases** are advisory `flock` files addressed by GPU UUID plus a JSON
  owner record. `CUDA_VISIBLE_DEVICES` is scoped to the lease; a second worker
  cannot acquire the same UUID.
- **Journals** are append-only, mode 0600, and record command/lease/process
  ownership. Recovery terminates only recorded process groups whose start time
  still matches; interrupted commands wait for lease expiry rather than being
  invented as complete.
- **Preflight** for llama.cpp starts a CPU-offload (`--n-gpu-layers 0`) server at
  the maximum requested context and reads the effective context. It proves
  allocation at that context, not GPU residency. Strata full-context proof is
  produced by the Phase 4 serving harness; it remains `INCONCLUSIVE` until a
  real approved run because the installed build lacks calibration commands.
- **Trials** collect native `llama-bench` evidence where available and a
  streaming OpenAI-compatible serving measurement. The serving harness runs a
  tokenizer-fitted prompt ladder, repeats the primary load and checks the
  near-capacity load against actual usage and effective context. Missing metrics
  remain missing; a native-only run is `screening_only`. Observations always
  carry `simulated=false` on the real lane.
- **Adapter evidence parsing** interprets `/props` or `/v1/status` for context
  identity and engine-specific fields. Client-observed TTFT, latency and usage
  keep precedence; a status document is never used to invent a peak VRAM or
  throughput value.

## 12. Adapter conformance (Phase 3)

- **Observed means observed.** `observed_flags` reads only help lines that begin
  an option. A flag merely mentioned in prose is not a capability. The
  llama.cpp adapter checks the server and `llama-bench` help separately and
  requires the flags used by each plan before the combined manifest is accepted.
- **Typed validation.** Candidate values are validated against the observed
  descriptor kind: booleans are not integers, numeric strings are not numbers,
  enum values must be listed, floats must be finite, and integer/float bounds are
  enforced. Unknown parameters fail instead of reaching argv.
- **llama.cpp plans.** Server flags include `--model`, `--ctx-size`, `--host`,
  `--port`; native `llama-bench` requires `--n-prompt`, `--n-gen`, `--n-depth`,
  `--repetitions` and `--output`. Every emitted server flag is present in server
  help, and every emitted native flag is present in bench help.
- **Strata installed surface.** The adapter models only the observed
  `0.1.44.1` CLI plus the installed Python server/profile JSON. It does not
  synthesize `models list`, `models inspect`, `doctor`, `engine calibrate` or
  `bench run`. `--expert-cache` is an integer defaulting to `0`;
  `--pool-workers=0` means all physical cores; `--kv-resident` is `0` or at
  least `20480`; `--batch` is opt-in.
- **Strata profiles.** Adapter-managed base args are removed before typed values
  are re-emitted, preventing duplicate or conflicting flags. `native: true` in
  model metadata is a discovery marker, not a path: only an explicit
  `native_shard` produces `--native SHARD1`. The unobserved `--mtp` form is not
  emitted.
- **Full-context honesty.** Strata full-context proof remains `INCONCLUSIVE`
  until a real approved Phase 4 harness run. The installed build's missing
  calibration commands are recorded as a boundary, not replaced with a guessed
  command.

## 13. Tokenizer-backed workloads (Phase 4)

- **Frozen corpus.** `lab_bench.corpus` owns the non-secret
  `lab-synthetic-v1` unit and its SHA-256. Fitting iterates against a supplied
  token counter; a character estimate is never called a token count.
- **Controller-owned suite.** `WorkloadSuite` travels in the durable
  `ClaimTrialPayload` and must match `workload_digest`. Fractions, output cap,
  seed and sampling are not invented by the worker.
- **Target-engine tokenization.** llama.cpp uses `/apply-template` +
  `/tokenize`; Strata uses `/v1/messages/count_tokens`. If no endpoint is
  usable, the prompt is labelled `character-fallback` and the observation is
  `screening_only`.
- **Ladder, not an average.** Every level runs once; the primary comparable
  level is repeated and medianed; the near-capacity level is a separate stress
  probe. Different prompt loads are never merged.
- **Context proof.** Actual prompt/output usage and effective context are
  checked. Truncation, overflow or a prompt-load miss invalidates the serving
  measurement with `CONTEXT_MISMATCH`.
- **Strata source identity.** Read-only discovery resolves every
  `conversions.json` source shard by exact basename and byte size. All resolved
  shards enter model files and are hashed when enabled. Missing, ambiguous or
  changed shards produce a warning and no `--native` argument. Only the first
  resolved shard becomes `--native SHARD1`; `native: true` is never a path.

## 14. Statistical finalization (Phase 5)

- **Paired baseline first.** The controller asks one fixed-default baseline for
  each selected context before normal TPE proposals. `AskPayload.baseline`
  selects `_defaults()` in the optimizer; the candidate is persisted with
  `role=baseline`. Baselines do not consume the distinct-candidate budget.
- **Comparable samples.** Every completed primary-level repeat is retained as a
  `BenchSample`; prompt loads are never merged. Observations remain the source
  of truth, and finalization is recomputed from stored observations rather than
  trusted from a worker summary.
- **Objective-relative optimisation.** A candidate `tell` value is the PRD
  objective ratio against its paired baseline (balanced geometric mean of
  prefill and decode ratios), so TPE does not confuse different context sizes
  with better configurations.
- **Deterministic confidence.** `paired_ratio_ci` performs a seeded percentile
  bootstrap over paired objective ratios. The default gate requires at least a
  5% score improvement and a 95% interval strictly above 1.0, with no failed
  guardrail.
- **Complete coverage.** Per-context winners are qualified independently.
  Cross-context aggregation uses the geometric mean over exactly the selected
  contexts; a missing context makes the candidate ineligible for a global
  winner. Results explicitly classify `VALIDATED_WINNER`,
  `NO_VALIDATED_WINNER` or `SIMULATED`.
- **Recipe gate.** Recipe creation recomputes finalization. It rejects
  simulated, screening-only, native-only, baseline, unpaired, sample-incomplete
  and non-qualified candidates with `409`. Accepted recipes are stored with
  `status=validated`; approval, verification and promotion remain separate
  guarded actions.
- **Honesty boundary.** No real baseline/candidate pair has been collected, so
  the finalization path is verified offline only. Simulation still produces a
  `SIMULATED` classification and no validated recipe.

## 15. Desktop operator UI (Phase 6)

The desktop application lives in `apps/desktop`. It is a Linux-first Electron
shell with a React/Vite renderer and a narrow preload bridge. It is a **view and
operator-control surface**, not a second controller:

- the renderer never launches an engine, worker, optimizer or benchmark job and
  never owns durable experiment state;
- the controller remains the only planning, scheduling, finalization and recipe
  qualification authority;
- closing the window closes only UI/IPC/SSE connections; durable jobs continue.

### Process and transport boundary

```text
React renderer (sandboxed, no Node, no token)
        │ preload contextBridge
        ▼
Electron main process
  settings (safeStorage; no plaintext token)
  validated /api/v1 HTTP proxy (Bearer attached only here)
  SSE bridge (reconnect + Last-Event-ID)
        │ HTTP + Bearer + SSE
        ▼
FastAPI controller
```

- Packaged renderer assets are served through the privileged `lab://app`
  protocol. The handler serves only files beneath the packaged `dist` directory,
  rejects traversal and unknown hosts, and sends a strict CSP with
  `connect-src 'none'`.
- Development uses only a loopback Vite origin (`127.0.0.1` or `localhost`) with
  a separate CSP that permits HMR. `file://` is never a production path.
- The preload exposes `appInfo`, settings status/storage, validated API request,
  SSE subscribe/unsubscribe and native report save. It does not expose Node,
  filesystem or general network APIs.
- The API proxy accepts only `GET`/`POST` paths under `/api/v1/`, rejects
  traversal and encoded traversal, caps bodies and responses, and uses
  `redirect: "error"`. The bearer token never crosses into the renderer.
- BrowserWindow uses `contextIsolation`, `sandbox`, `webSecurity`, no Node
  integration, no webviews, denied permissions and blocked foreign navigation.
- A system tray, when available, hides/reopens the window or quits the UI. It
  never owns a job; controller-owned work continues while the window is hidden.

### UI truthfulness

- Demo mode is an explicit offline fixture client selected by `?demo=1` or a
  stored UI preference. Every screen remains labelled `OFFLINE DEMO MODE`; the
  fixtures cannot create, cancel or qualify real evidence.
- Compare renders `VALIDATED_WINNER`, `NO_VALIDATED_WINNER` and `SIMULATED`
  directly from controller data, including paired intervals, per-context
  winners, incomplete coverage and ineligibility reasons. Highest throughput is
  never shown as a winner by itself.
- Optimize renders fresh/stale inventory, preflight blockers, the six-step
  immutable plan and the selected worker/GPU/contexts. It submits through the
  existing planning/experiment endpoints.
- Updates imports offline release metadata, shows P0/P1/P2 impact and reasons,
  supports pin/defer decisions and requests a frozen A/B proposal. It displays
  comparison intervals and non-approving recommendations. It never downloads,
  replaces, installs or launches an engine or model.
- Hardware acceleration is disabled before ready by default.
  `LAB_DESKTOP_ENABLE_GPU=1` is an explicit operator override; it requires a
  restart and any shared-GPU qualification then requires contamination
  verification.

### Packaging boundary

`apps/desktop/scripts/package-linux.mjs` builds a Debian package from the
installed Electron distribution and compiled renderer/main assets without
downloading anything. It sets `chrome-sandbox` to root-owned mode 4755 and
installs an application launcher, desktop entry and icon. Building the `.deb`
is verified; installation, signing, upgrade/rollback and AppImage packaging
remain Phase 8 release-hardening work requiring approval. A packaged build is
not benchmark evidence.

## 16. Release intelligence (Phase 7)

Release intelligence is an offline review workflow, not an updater:

1. an operator imports a `ReleaseMetadata` document through
   `POST /api/v1/releases/check`;
2. `lab_updates` classifies changed paths and explicit areas deterministically,
   compares optional capability schemas and applies cached freshness/identity
   rules;
3. the controller stores a durable notice and an immutable assessment keyed by
   release metadata, worker/model identity, installed executable hash, inventory
   revision and policy version;
4. the operator may pin, defer or request a paired A/B proposal;
5. creating a proposal requires a complete verified model identity digest and
   freezes baseline/candidate engine identities, worker, workload suite,
   contexts, margin and confidence threshold;
6. measured paired samples can be submitted later; evidence is immutable and a
   terminal comparison rejects different evidence with `409`;
7. results are `IMPROVED`, `REGRESSED`, `INCONCLUSIVE` or `INCOMPATIBLE`, with
   `upgrade_approved=false` always.

Classification is conservative: CUDA/backend/MoE/KV/context/model-loader changes
are P0; scheduling/threading/batching/server API are P1; docs/tests are P2.
Unknown paths are P1 and force smoke testing. Stale inventory can raise a P2
result to P1. A missing installed engine makes the release non-applicable. A
comparison requires the candidate executable SHA-256 and complete model hashes,
and missing/extra contexts, mismatched identity, simulation, non-measured status
or baseline guardrail failure is incompatible. A candidate guardrail failure or significant regression
retains the current engine.

No endpoint fetches upstream metadata, downloads an artifact, starts a candidate
binary or writes under an engine/model root. The Electron Updates screen only
imports JSON, records decisions and displays assessments/comparisons; it cannot
install or approve an engine. Remote polling, artifact download and installation
remain deferred and approval-gated.

## 17. Phase boundary

Phases 0/1 prove protocol, persistence, planning, lifecycle, recovery and
pure-adapter behavior. Phase 2 proves the worker-owned process, discovery, GPU
lease and command execution machinery. Phase 3 proves adapter conformance
against the installed help/version/evidence fixtures and the observed live
surface. Phase 4 adds tokenizer-backed workload lanes and read-only Strata
source-shard identity. Phase 5 adds paired baselines, retained samples,
statistical finalization and the recipe qualification gate. Phase 6 adds the
secure desktop operator UI and a locally built `.deb`. Phase 7 adds offline
release impact assessment and frozen A/B records without installing anything.
None of these offline checks prove real llama.cpp/Strata performance or create a
real validated recipe without an approved live run.
