# Implementation status

Last updated: 2026-10-21.

This document records what is actually implemented and what was actually run.
It is not a roadmap and does not upgrade reconnaissance into benchmark evidence.

## 1. Scope status

| Area | Status | Evidence / boundary |
|---|---|---|
| Phase 0 engine reconnaissance | Partial | llama.cpp and Strata version/help captured as sanitized fixtures. No live 4K/32K benchmark, second GPU, live server run or production model hashing was executed. See `docs/PHASE_0_FINDINGS.md`. |
| Python `uv` workspace | Implemented | Six workspace packages resolve with `uv sync --all-packages`. |
| Frozen contracts | Implemented | Pydantic v2 frozen models in `lab_core`; canonical JSON/SHA-256 in `lab_core.ids`. |
| Controller persistence | Implemented | FastAPI + SQLAlchemy 2.x + SQLite WAL + Alembic. Initial controller revision creates 20 tables. |
| Separate optimizer process | Implemented | `lab_optimizer` owns Optuna and a distinct SQLite URL. FastAPI imports no Optuna. |
| Durable worker protocol | Implemented, simulated | Poll, lease, ack, complete, idempotent replay, conflict `409`, lease expiry/requeue. |
| Engine adapters | Implemented, pure | llama.cpp and Strata help/JSON parsers and typed plan builders. No subprocess/network/filesystem I/O. |
| Planning | Implemented, snapshot-only | Cached snapshots; stale/missing inventory returns `202 PREFLIGHT_REQUIRED` plus queued `SCAN`. |
| Phase 1 execution | Explicitly simulated | Every observation has `simulated=true` and `measurement_status=simulated`. |
| Recipe validation | Implemented, rejects simulation | Simulated evidence cannot create a validated recipe; API returns `409`. |
| SSE | Implemented | Initial `snapshot`, sequenced events, `event.gap` for stale `Last-Event-ID`, bounded page endpoint. |
| Generated contracts | Implemented, checked in | OpenAPI, JSON Schema/manifest and strict TypeScript declarations; offline Python generation and drift gate. |
| Electron/React UI | Not implemented | Deferred beyond the Phase 1 foundation. |
| Real engine execution / GPU leases | Not implemented | Deferred to Phase 2. `execution_mode=real` is rejected at startup. |
| Statistical finalization / real recipes | Not implemented | Requires real evidence, corpus and Phase 4 work. |
| systemd packaging / remote TLS | Not implemented | Local loopback development mode only. |

## 2. Runtime components

- **`lab-api`** — controller entry point on `127.0.0.1:8787` by default.
  Persistent sessions, auth, planning, experiment lifecycle, command queue,
  optimizer outbox/inbox, SSE and runtime lease reconciliation.
- **`lab-optimizer`** — independent poller/worker for Optuna `ask/tell` work.
  It owns the Optuna database and never touches controller tables.
- **`lab-worker-sim`** — explicit simulated worker. It enrolls, uploads
  simulated inventory, heartbeats, polls, acks and completes commands.
- **`lab-worker`** — Phase 1 compatibility entry point that logs a warning and
  forwards to the simulated lane.
- **`lab-worker` future runner** — real subprocess/GPU execution is not present.

## 3. Verification actually performed

The following commands were run in this workspace on 2026-10-21 and produced the
results shown. They must be re-run after any change.

```bash
uv sync --all-packages
# Resolved 54 packages; checked 52 packages. No dependency errors.

uv run ruff check
# All checks passed!

uv run ruff format --check
# 93 files already formatted

uv run mypy python
# Success: no issues found in 79 source files

uv run pytest -q
# 18 passed in 4.85s (final verification run)

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# tsc --noEmit -p tsconfig.json: passed
```

Controller migration verification used an isolated temporary database:

```bash
uv run --env-file /tmp/opencode/lab-final.env alembic upgrade head
```

Observed result: upgrade to revision `b151f9870480` succeeded and SQLite
contained 20 tables. `uv --env-file` produced no parse warning after quoting
`LAB_WORKER_WORKER_NAME`.

A quick-start smoke test then started all three entry points against the
migrated temporary stores on a non-default loopback port:

- `GET /health` returned `200` with `status=ok`;
- `GET /api/v1/status` reported `optimizer.online=true`,
  `optimizer.status=online`, `workers_online=1` and only the expected
  `PHASE_1_SIMULATED_EXECUTION` warning;
- `lab-worker-sim` logged enrollment, snapshot upload, heartbeat and polling;
- `lab-optimizer` logged heartbeat and request polling.


The automated suite starts a live loopback controller, simulated worker and
optimizer with temporary stores. It exercises:

- planning with cached inventory and `PREFLIGHT_REQUIRED`;
- experiment creation and idempotent request replay;
- Optuna study creation, ask/tell and replay safety;
- simulated `CLAIM_TRIAL` execution and observation persistence;
- experiment completion and simulated-recipe rejection (`409`);
- conflicting idempotency (`409`) and event pages;
- SSE initial snapshot and stale-gap replay;
- command lease/ack/completion resilience;
- controller migrations and generated-contract drift.

## 4. What is not proven

These are intentional boundaries, not hidden gaps:

- No engine process was started and no GPU work was performed by this code.
- Simulated throughput, VRAM/telemetry and OOM values are deterministic test
  data, not measurements.
- No accepted deployment recipe can exist from simulated evidence.
- No 4K/32K full-context feasibility, quality, or second-GPU comparison exists.
- No load test at 1,000 concurrent polling workers is claimed.
- No systemd service, TLS listener, remote authentication, UI or release
  intelligence exists yet.
- Optuna and controller writes are not atomic; recovery is deterministic and
  conservative rather than a two-phase commit.

## 5. Generated artifacts

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

## 6. Quick start status

The documented quick start is in `README.md` and `AGENTS.md`:

```bash
cp .env.example .env
# replace every CHANGE_ME secret with a 16+ character random value
uv run --env-file .env alembic upgrade head
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
uv run --env-file .env lab-worker-sim
```

`/health` is public. Operator, enrollment, worker and optimizer routes require
the corresponding bearer token. All three components run without a desktop UI
or GPU in Phase 1.

## 7. Next gate

Close the Phase 0 evidence gaps first, then implement the Phase 2 worker runner.
See `docs/PHASE_1_COMPLETION.md` for the phase boundary and
`docs/PHASE_2_BACKLOG.md` for sequenced work.
