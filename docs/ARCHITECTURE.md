# Architecture — Phase 0/1 foundation plus Phase 2 worker

Status: Phase 1 is complete and verified. Phase 2 adds a production Linux worker
with observed engine/model discovery, native process execution, GPU UUID leases,
journals, sandboxes and a real executor. The simulated lane remains separate and
its evidence can never qualify a recipe.

## 1. Process topology

```text
operator / browser / future Electron UI
        │  HTTP + Bearer + SSE (loopback in local mode)
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
| `lab_core` | frozen Pydantic models, canonical JSON/hash, enums, state transitions, scoring primitives | perform I/O, import FastAPI/Optuna, hold process handles |
| `lab_bench` | deterministic context/workload matrix and normalization | launch engines or read prompt corpora |
| `lab_adapters` | pure CLI/JSON translation, capability parsing, candidate validation, execution-plan construction | subprocess, network, filesystem, hardware probe |
| `lab_api` | FastAPI, auth, persistence, planning, lifecycle, command queue, optimizer outbox, SSE, migrations | import Optuna, run benchmark work on the event loop |
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
Alembic-managed (`python/lab_api/migrations`). The initial migration creates 20
tables, including:

- identity/inventory: `workers`, `worker_snapshots`, `gpu_devices`, engine/model
  registry rows;
- experiments: `experiments`, `studies`, `candidates`, `observations`,
  `recipe_rows`/recipes and contexts;
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
  deferred until the Phase 4 serving harness; the installed build lacks
  calibration commands, so the result is explicitly `inconclusive`, never
  fabricated.
- **Trials** collect native `llama-bench` evidence where available and a
  streaming OpenAI-compatible serving measurement. Missing metrics remain
  missing; a native-only run is `screening_only`. Observations always carry
  `simulated=false` on the real lane.

## 12. Phase boundary

Phases 0/1 prove protocol, persistence, planning, lifecycle, recovery and
pure-adapter behavior. Phase 2 proves the worker-owned process, discovery, GPU
lease and command execution machinery. It does **not** yet prove real
llama.cpp/Strata performance, quality, statistical finalization or validated
recipes. Phase 3 productionizes both adapters; Phase 4 adds benchmark lanes and
evidence; Phase 5 adds search/finalization; Phase 6 adds the UI.
