# Phase 1 completion report — protocol and simulation foundation

Date: 2026-10-21.

Result: **Phase 1 foundation is implemented for the simulated lane.** The
controller, supervised optimizer, durable worker protocol, pure adapters,
snapshot-only planner, SSE replay and deterministic contracts work together in
automated tests. This is not a claim of real engine execution, benchmark
validity, or product-wide completion.

## 1. Delivered

### Contracts and durable identity

- Frozen Pydantic v2 boundary models in `lab_core`.
- Canonical JSON, SHA-256 and stable prefixed IDs in `lab_core.ids`.
- Typed commands, observations, job/experiment state, optimizer protocol,
  adapter interfaces and error envelopes.
- Explicit provenance fields, including `simulated`, `measurement_status`,
  engine binary hash, model digest, worker profile and attempt/generation.

### Controller (`lab_api`)

- App factory with typed error envelopes, request IDs, auth and lifespan runtime.
- SQLAlchemy 2.x ORM and Alembic initial migration (20 tables) on SQLite WAL.
- Operator, enrollment, worker and optimizer credentials separated.
- Worker registration, inventory snapshot, heartbeat, summary and command
  endpoints.
- Durable `worker_commands` queue with poll/lease/ack/complete, hashed lease
  tokens, generations, expiry and replay-safe terminal results.
- Experiment planning from cached snapshots only. Stale/missing inventory
  produces typed `202 PREFLIGHT_REQUIRED` plus a durable `SCAN` command.
- Experiment create, list, detail, pause/resume/cancel, preflight retry, command
  listing, event page, SSE stream and results/recipe endpoints.
- Durable `optimizer_requests` outbox/inbox. The controller issues typed
  requests and applies validated completions without importing Optuna.
- SSE with initial `snapshot`, per-experiment sequence IDs, keepalives, bounded
  page replay, `event.gap` when the requested ID is below the replay floor.
- Runtime scheduler for lease expiry, offline marking and reconciliation.

### Optimizer (`lab_optimizer`)

- Independent process with its own Optuna `RDBStorage` SQLite database.
- Authenticated poll/heartbeat/complete client with retries and stable request
  identity.
- Idempotent study creation, bounded `ask`, `tell`, replay detection, trial
  reconciliation and health.
- Controller/optimizer URL separation validated at startup.

### Worker (`lab_worker`)

- Enrollment and state-token persistence, snapshot upload, heartbeat, poll,
  ack and complete.
- Bounded exponential retry and command lease handling.
- Explicit deterministic simulated executor for `SCAN`, `PREFLIGHT`,
  `CLAIM_TRIAL`, `PAUSE`, `CANCEL`, `VERIFY_RECIPE`, `PROMOTE`.
- Every simulated observation carries `simulated=true` and
  `measurement_status=simulated`.
- `lab-worker` logs that only simulation exists and delegates to
  `lab-worker-sim`. No engine subprocess is started.

### Adapters and benchmark planning

- Pure llama.cpp adapter: help/version parsing, scoped capability descriptors,
  model inspection and compatibility, candidate validation, benchmark/server
  command plans and evidence parsing.
- Pure Strata adapter: conservative capture of the installed `generate` surface
  and known Python serving path; Lab Custom Protocol plan; no invented native
  benchmark or score command.
- Static tests reject forbidden adapter imports (`subprocess`, network,
  filesystem, hardware probing).
- Deterministic workload/context planning in `lab_bench`.

### Generated contracts

- In-process FastAPI OpenAPI export, selected JSON Schema export with a SHA-256
  manifest, and strict TypeScript declarations.
- No HTTP listener, no network and no external schema generator required.
- `scripts/check_contracts.py` regenerates in memory and fails on any drift.
- Committed artifacts are consumed by `@lab/client-contracts` and checked with
  `tsc --noEmit`.

## 2. Verified end-to-end behavior

The integration test suite starts real loopback processes for the controller,
simulated worker and optimizer using temporary databases. It verifies the
following sequence:

1. Operator plans an experiment against a fresh simulated inventory.
2. Experiment creation returns durable IDs and candidate/study intent.
3. Preflight and Optuna study creation are queued durably.
4. The optimizer polls, creates the study, and returns suggestions.
5. Candidates become worker `CLAIM_TRIAL` commands.
6. The simulated worker leases, acks and completes with simulated observations.
7. Results are persisted and the experiment reaches a terminal state.
8. A recipe request using simulated evidence is rejected with HTTP `409`.
9. Replaying the same create request is idempotent; a conflicting key returns
   `409`.
10. Event pages and SSE replay return a snapshot; a stale `Last-Event-ID`
    produces `event.gap` followed by a fresh snapshot.

Resilience tests additionally cover lease ownership, replay-safe completion,
conflicting terminal results and expired-lease requeue behavior.

## 3. Commands and observed results

Executed on 2026-10-21 in this workspace:

```bash
uv sync --all-packages
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm install --frozen-lockfile
pnpm typecheck
```

Observed:

- `uv sync --all-packages`: resolved 54 packages; checked 52 packages.
- `ruff check`: all checks passed.
- `ruff format --check`: 93 files already formatted.
- `mypy python`: success, no issues in 79 source files.
- `pytest -q`: **18 passed in 4.85s (final verification run)**.
- contract check: **contracts are current**.
- `pnpm typecheck`: passed.

Migration command:

```bash
uv run --env-file /tmp/opencode/lab-final.env alembic upgrade head
```

Observed revision `b151f9870480`; 20 controller tables created. The env file
used a quoted worker display name and parsed without warnings.

A quick-start smoke test started `lab-api`, `lab-optimizer` and
`lab-worker-sim` together on a temporary loopback port. `/health` returned
`200`; the status endpoint reported the optimizer online and one worker online;
the worker enrolled, uploaded a snapshot, heartbeated and polled; the optimizer
heartbeated and polled for requests.


No test requires a GPU, downloaded model, live engine or desktop UI.

## 4. Phase 1 exit criteria

| Criterion | Status | Note |
|---|---|---|
| Controller is persistent and independently runnable | Met | FastAPI + SQLite WAL + Alembic. |
| Optuna is isolated from the API event loop | Met | Separate supervised process and database. |
| Worker protocol is durable and outbound-only | Met | Poll/lease/ack/complete with replay safety. |
| Planning uses cached snapshots only | Met | Typed `PREFLIGHT_REQUIRED` path. |
| Adapters are pure and version-scoped | Met | Static import test and sanitized fixtures. |
| Simulated evidence is unmistakable | Met | Provenance flags on every simulated observation. |
| Simulated evidence cannot validate a recipe | Met | HTTP `409` verified. |
| Contracts generate offline and drift is detected | Met | Checked-in Python-generated artifacts + `tsc`. |
| Tests run without GPU/live engine | Met | 18 passing tests. |
| Real engine execution | Not in phase | Phase 2. |
| Validated real benchmark/recipe | Not in phase | Requires Phase 0/4 evidence. |
| Electron/React UI | Not in phase | Deferred. |

## 5. Known limitations

- Command lease expiry is not proof that a real engine process died. Phase 2
  must add worker-owned process supervision and GPU ownership reconciliation.
- The simulated worker does not validate engine argv against live binaries or
  read model files.
- Strata 0.1.44.1 exposes no native benchmark/model-inspection commands in the
  observed build. The adapter and future runner must not pretend otherwise.
- Token storage/rotation, TLS, revocation, backups and systemd packaging are
  development-grade or absent.
- No concurrency/load target such as 1,000 polling workers was measured.
- Controller and Optuna stores can diverge during a crash. Reconciliation is
  explicit and conservative; there is no cross-store transaction.
- Phase 0 reconnaissance did not include real 4K/32K measurements, a second GPU,
  strong production model hashes or a quality corpus.

## 6. Handoff

Phase 2 starts with the real worker runner and process/GPU lease ownership, not
with statistics or release recipes. Required work is sequenced in
`docs/PHASE_2_BACKLOG.md`. Phase 0 evidence gaps must be closed before any real
performance or recipe claim is treated as validated.
