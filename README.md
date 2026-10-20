# AI Inference Optimization Lab

Phase 3 foundation for a local-first inference optimization controller,
supervised Optuna process, durable Linux worker protocol and conformance-tested
llama.cpp/Strata adapters.

> **The execution lanes are separate.** `lab-worker-sim` produces deterministic
> simulated observations marked `simulated=true`; those can never qualify a
> recipe. `lab-worker` is the real Linux lane: it probes configured installed
> engines and models, launches argv-only subprocesses, leases GPU UUIDs and
> records measured evidence. Missing evidence stays missing.

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

# Terminal 3: real Linux worker (requires installed engines/models)
uv run --env-file .env lab-worker

# Optional, explicit simulated lane
# uv run --env-file .env lab-worker-sim
```

The controller listens on `http://127.0.0.1:8787` by default. Health is public:
`curl http://127.0.0.1:8787/health`. All other operator endpoints require
`Authorization: Bearer <operator token>`.

The real worker uses the engine/model paths in `.env`; it never downloads or
changes them. The first full model scan hashes GGUF files with a persistent
`(size, mtime_ns)` cache, so later scans are cheap. The simulated lane needs no
GPU, model download or live inference server.

The controller rejects an inventory that is not fresh by returning
`202 PREFLIGHT_REQUIRED` and queueing a durable `SCAN`; it never performs a live
worker call inside planning.

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
temporary SQLite databases. They do not require GPU access or live engines. Real
worker unit tests use a synthetic GGUF file and the trusted Python interpreter.
Adapter conformance tests parse committed installed-build help/version and
evidence fixtures; they verify that emitted flags are observed, candidate types
are strict, Strata profiles do not duplicate managed flags and generated-file
digests match.

The installed Strata `0.1.44.1` build exposes no `models list`, `doctor`,
`engine calibrate` or `bench run` command. Those forms are refused rather than
synthesized; full-context proof remains `INCONCLUSIVE` until Phase 4.

## Repository map

- `python/lab_core` — frozen contracts, canonical hashes, scoring primitives.
- `python/lab_bench` — deterministic workload/context planning.
- `python/lab_adapters` — pure llama.cpp and Strata translators/parsers.
- `python/lab_api` — FastAPI controller, persistence, queues, SSE, Alembic.
- `python/lab_optimizer` — independent Optuna process.
- `python/lab_worker` — real worker discovery/execution plus explicit simulator.
- `packaging/systemd` — units and deployment notes; not installed by this repo.
- `tests/` — unit, integration, migration, resilience and contract checks.
- `fixtures/` — sanitized Phase 0 CLI evidence.
- `attic/` — archived abandoned draft; never imported or modified.

## Safety and scope

- Controller and Optuna databases must be separate SQLite files.
- FastAPI never imports Optuna or runs engine work on its event loop.
- Adapters perform no subprocess, network, filesystem or hardware I/O.
- The real worker owns processes/files/GPU leases; adapters only build plans.
- Planning reads cached snapshots only; stale inventory returns typed
  `PREFLIGHT_REQUIRED`.
- The worker terminates only process groups recorded in its own journal; it
  never kills unrelated GPU processes.
- Worker commands use durable IDs, leases, acks, idempotent completions and
  explicit conflict handling.
- `docs/prd.md` remains the product source of truth.
