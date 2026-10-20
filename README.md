# AI Inference Optimization Lab

Phase 0/1 foundation for a local-first inference optimization controller,
supervised Optuna process, and durable Linux worker protocol.

> **Phase 1 is simulation-only.** The worker never launches llama.cpp or Strata,
> allocates a GPU, or produces validated evidence. Simulated observations are
> marked `simulated=true`; recipe creation rejects them with HTTP `409`.
> Real engine execution is Phase 2 work.

The authoritative specification is [`docs/prd.md`](docs/prd.md). Architecture
and decisions are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/ADR/`](docs/ADR/). Implementation status is recorded in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Quick start

Prerequisites: Python 3.12–3.14, [`uv`](https://docs.astral.sh/uv/), Node 20+,
pnpm 10+.

```bash
uv sync --all-packages
cp .env.example .env
# edit .env: replace every CHANGE_ME secret with 16+ character random values
uv run --env-file .env alembic upgrade head

# Terminal 1: controller
uv run --env-file .env lab-api

# Terminal 2: supervised optimizer
uv run --env-file .env lab-optimizer

# Terminal 3: explicit simulated worker
uv run --env-file .env lab-worker-sim
```

The controller listens on `http://127.0.0.1:8787` by default. Health is public:
`curl http://127.0.0.1:8787/health`. All other operator endpoints require
`Authorization: Bearer <operator token>`.

No GPU, model download, or live inference server is needed for any of the above.

## Contract generation

Pydantic/FastAPI are the contract source. Generation is offline and deterministic:

```bash
pnpm generate:contracts          # Python export scripts, no HTTP listener
pnpm contracts:check             # fails on stale artifacts
pnpm typecheck                   # tsc --noEmit on generated contracts
```

Generated files are committed:

- `contracts/openapi.json`
- `contracts/contracts.schema.json`
- `contracts/manifest.json`
- `packages/client-contracts/src/openapi-types.ts`
- `packages/client-contracts/src/index.ts`

## Verification

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
```

The tests start a live loopback controller, simulated worker and optimizer using
temporary SQLite databases. They do not require GPU access or live engines.

## Repository map

- `python/lab_core` — frozen contracts, canonical hashes, scoring primitives.
- `python/lab_bench` — deterministic workload/context planning.
- `python/lab_adapters` — pure llama.cpp and Strata translators/parsers.
- `python/lab_api` — FastAPI controller, persistence, queues, SSE, Alembic.
- `python/lab_optimizer` — independent Optuna process.
- `python/lab_worker` — worker protocol client and explicit simulator.
- `tests/` — unit, integration, migration, resilience and contract checks.
- `fixtures/` — sanitized Phase 0 CLI evidence.
- `attic/` — archived abandoned draft; never imported or modified.

## Safety and scope

- Controller and Optuna databases must be separate SQLite files.
- FastAPI never imports Optuna or runs engine work on its event loop.
- Adapters perform no subprocess, network, filesystem or hardware I/O.
- Planning reads cached snapshots only; stale inventory returns typed
  `PREFLIGHT_REQUIRED`.
- Worker commands use durable IDs, leases, acks, idempotent completions and
  explicit conflict handling.
- `docs/prd.md` remains the product source of truth.
