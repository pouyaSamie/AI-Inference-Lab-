# AGENTS.md — working rules for this repository

This repository is the Phase 0/1 foundation of **AI Inference Optimization Lab**.
The authoritative product contract is [`docs/prd.md`](docs/prd.md) (PRD v2.1).
When code and prose disagree, the PRD and the frozen `lab_core` models win.

## Current scope

Implemented now:

- local Python 3.12+ `uv` workspace with six packages;
- persistent FastAPI controller, SQLAlchemy 2.x, Alembic, SQLite WAL;
- frozen Pydantic v2 contracts in `lab_core`;
- independently supervised Optuna process (`lab_optimizer`) using its own SQLite store;
- durable worker command queue with outbound polling, leases, acks and idempotent completions;
- pure `llamacpp` and `strata` adapter translators/parsers;
- deterministic OpenAPI/JSON-Schema/TypeScript contract generation;
- explicit **simulated** worker executor and end-to-end tests.

Intentionally deferred: real engine execution, GPU leases, process supervision,
tokenizer-backed benchmark corpora, statistical finalization, recipes from real
evidence, Electron/React UI, release intelligence and systemd packaging.

## Non-negotiable invariants

1. **Phase 1 never executes a real engine.** `lab-worker` and `lab-worker-sim`
   run the simulation lane. Every simulated observation has `simulated=true`
   and `measurement_status=simulated`. Simulated evidence can never produce a
   validated recipe; `POST /api/v1/recipes` must return `409`.
2. **Never run Optuna in FastAPI.** `lab_api` writes durable optimizer requests
   to the controller store. `lab_optimizer` owns `study.ask/tell`, Optuna
   `RDBStorage` and its own database. No controller module may import Optuna.
3. **Separate databases.** Controller and optimizer URLs must be different;
   startup validation rejects sharing one SQLite file.
4. **Adapters are pure.** `python/lab_adapters` may parse supplied facts and
   build typed command plans. It must never import `subprocess`, `socket`,
   `httpx`, `requests`, `urllib`, `pathlib` or `os`, and must never open a file,
   start a process, bind a port or probe hardware. A test enforces this.
5. **Planning is snapshot-only.** `/api/v1/experiments/plan` reads cached
   snapshots. Stale/missing inventory returns a typed `202 PREFLIGHT_REQUIRED`
   response plus a queued `SCAN` command; it never performs a live worker call.
6. **Durable IDs and idempotency.** Commands, requests, experiments and events
   use stable IDs and idempotency keys. Lease completion must be replay-safe;
   a conflicting terminal result must fail explicitly.
7. **Dual-store truth.** Controller commit and Optuna `tell` are separate
   transactions. Recovery must reconcile, never invent a result or issue two
   trials for one candidate.
8. **Frozen models.** Boundary models are Pydantic frozen models with explicit
   validation. Canonical JSON/SHA-256 helpers are in `lab_core.ids`.
9. **Generated contracts are checked in.** Pydantic/FastAPI are the only
   contract source. `scripts/check_contracts.py` is the CI drift gate; do not
   hand-edit `contracts/` or `packages/client-contracts/src/openapi-types.ts`.
10. **`attic/` is archival.** Do not import, format, modify or activate anything
    under `attic/`. It records an abandoned parallel draft only.

## Required commands

```bash
# install / resolve the workspace
uv sync --all-packages

# controller schema
uv run --env-file .env alembic upgrade head

# run components (three terminals; no desktop/GPU required)
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
uv run --env-file .env lab-worker-sim

# verification
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q

# contracts and TypeScript
uv run python scripts/check_contracts.py
pnpm install --frozen-lockfile
pnpm typecheck
```

`pnpm generate:contracts` (or the three Python export scripts directly) must
work offline and must not start an HTTP listener. CI must fail on drift.

## Layout

- `python/lab_core` — frozen contracts, canonical hashing, scoring, protocol.
- `python/lab_bench` — deterministic workload planning and normalization.
- `python/lab_adapters` — pure engine adapters and conformance fixtures.
- `python/lab_api` — FastAPI app, auth, persistence, queues, SSE, Alembic.
- `python/lab_optimizer` — supervised Optuna process and internal client.
- `python/lab_worker` — worker protocol client and explicit simulation.
- `contracts/` — committed generated OpenAPI/JSON Schema/manifest.
- `packages/client-contracts` — generated TypeScript declarations.
- `tests/` — offline unit/integration/resilience/contract tests.
- `fixtures/engines` — sanitized Phase 0 CLI/version evidence (never private data).
- `docs/ADR` — architecture decision records.

## Working style

- Keep changes inside the current phase. Do not implement later-phase engine
  execution, UI or release workflows “while here”.
- Read the existing implementation before replacing it. Preserve user changes.
- Prefer small, typed services and explicit state transitions over hidden
  side effects in routes.
- Tests must not require a GPU, downloaded weights or a live inference server.
  Integration tests may start the controller, simulated worker and optimizer on
  loopback ports.
- Record commands and observed results in `docs/IMPLEMENTATION_STATUS.md`.
  Never claim a command passed unless it was actually run.
- Do not modify `docs/prd.md`, model/engine files, or `attic/` unless the user
  explicitly asks.

## Security notes

- Bearer tokens only; worker enrollment uses a separate enrollment credential.
- Worker tokens are stored as a peppered SHA-256 hash; plaintext is returned
  once at registration.
- SSE uses a stateless operator check because the stream is long-lived.
- Do not log secrets, model prompts or full environment dumps.
