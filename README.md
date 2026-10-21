# AI Inference Optimization Lab

Phase 7 foundation plus a Phase 8 offline-hardening increment for a local-first
inference optimization controller, supervised Optuna process, durable Linux
worker protocol, conformance-tested llama.cpp/Strata adapters,
tokenizer-backed benchmark workloads, paired statistical finalization, offline
release intelligence, secure Electron/React operator console and verified
offline backup/restore tooling.

> **The execution lanes are separate.** `lab-worker-sim` produces deterministic
> simulated observations marked `simulated=true`; those can never qualify a
> recipe. `lab-worker` is the real Linux lane: it probes configured installed
> engines and models, launches argv-only subprocesses, leases GPU UUIDs and
> records measured evidence. Missing evidence stays missing. Prompts are fitted
> with the target engine tokenizer when available; a character-estimated prompt
> is labelled `screening_only`. Finalization compares retained candidate
> samples with a fixed-default baseline at the same context using a deterministic
> paired bootstrap. Results are classified `VALIDATED_WINNER`,
> `NO_VALIDATED_WINNER` or `SIMULATED`; only eligible measured evidence can
> produce a validated recipe. The Electron UI is a view/control surface: it
> never owns jobs or engines, and its offline demo mode is always labelled and
> cannot create or qualify evidence.
>
> **Release checks are offline and read-only.** The controller imports
> operator-supplied release metadata, classifies impact deterministically and
> can freeze a paired old/new A/B record. It never queries upstream, downloads
> or installs an engine, or changes an installed artifact. Comparison results
> never approve an upgrade (`upgrade_approved` is always `false`). A comparison
> also requires a complete verified model identity and candidate executable
> hash; simulated, non-measured, context-incomplete or guardrail-failing
> evidence is incompatible or ineligible.

The authoritative specification is [`docs/prd.md`](docs/prd.md). Architecture
and decisions are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/ADR/`](docs/ADR/). Implementation status is recorded in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md). Operations,
upgrade/rollback, restore and live acceptance are in
[`docs/RUNBOOK.md`](docs/RUNBOOK.md). The AC-01…AC-44 evidence and blocked
gates are recorded in [`docs/ACCEPTANCE_MATRIX.md`](docs/ACCEPTANCE_MATRIX.md).

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

### Desktop operator console

The Electron/React UI is in `apps/desktop`. It is intentionally outside the
pnpm workspace so the Python and desktop dependency graphs stay separate.
Install its dependencies and run it while the controller/optimizer are up:

```bash
npm --prefix apps/desktop install
npm --prefix apps/desktop run dev       # loopback Vite + Electron, devtools enabled
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
npm --prefix apps/desktop run package:linux
```

`package:linux` builds
`apps/desktop/release/ai-inference-lab-desktop_<version>_amd64.deb` from the
locally installed Electron distribution using `dpkg-deb`; it performs no
network download. The package is **built and inspected but not installed** in
this workspace. Installation, signing, upgrade/rollback and AppImage packaging
require operator approval; `docs/RUNBOOK.md` records the reviewed procedure but
the Phase 8 live gate remains unmet.

The packaged renderer is served only through the privileged `lab://app`
protocol with a strict CSP. The renderer has `contextIsolation` and `sandbox`,
no Node integration, no direct network access and no bearer token. All API
requests and SSE streams pass through validated IPC handlers in the Electron
main process. A system tray can hide/reopen the window; closing the UI never
stops a controller-owned job. Hardware acceleration is disabled before the app is ready;
`LAB_DESKTOP_ENABLE_GPU=1` is an explicit operator override that requires a
restart and later contamination verification.

`?demo=1` or the Settings toggle selects offline fixtures. Demo data is visibly
labelled and can never create a real experiment or recipe.

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

## Backup and restore

The controller and optimizer stores are backed up with SQLite's online backup
API. The helper writes a verified manifest and refuses to overwrite an existing
target without an explicit pre-restore snapshot:

```bash
uv run python scripts/backup_databases.py backup \
  --controller /var/lib/ai-inference-lab/controller.sqlite3 \
  --optimizer /var/lib/ai-inference-lab/optuna.sqlite3 \
  --output /var/backups/ai-inference-lab/$(date -u +%Y%m%dT%H%M%SZ)

uv run python scripts/backup_databases.py verify --backup /var/backups/...
```

Restore is an offline operation: stop controller, optimizer and worker first,
then use `restore --backup ... --label controller --target ... --replace`.
Never run it against a live database. See `docs/RUNBOOK.md` for the complete
procedure, including retention and explicit deletion rules.

## Contract generation

Pydantic/FastAPI are the contract source. Generation is offline and deterministic:

```bash
pnpm generate:contracts          # Python export scripts, no HTTP listener
pnpm contracts:check             # fails on stale artifacts
pnpm typecheck                   # generated contracts + desktop typecheck
pnpm ui:test                     # desktop Vitest suite
pnpm ui:build                    # renderer + Electron main/preload build
pnpm ui:package:linux            # local .deb package (no download)
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
pnpm ui:test
pnpm ui:build
```

The desktop tests render every primary screen against offline fixtures, exercise
the finalization labels and validate IPC path/method/report/proxy boundaries.
They do not start Electron or require a display. The tests start a live loopback
controller, simulated worker and optimizer using
temporary SQLite databases. They do not require GPU access or live engines. Real
worker unit tests use a synthetic GGUF file and the trusted Python interpreter.
Adapter conformance tests parse committed installed-build help/version and
evidence fixtures; they verify that emitted flags are observed, candidate types
are strict, Strata profiles do not duplicate managed flags and generated-file
digests match.

The installed Strata `0.1.44.1` build exposes no `models list`, `doctor`,
`engine calibrate` or `bench run` command. Those forms are refused rather than
synthesized; full-context proof remains `INCONCLUSIVE` until a real approved
serving run.

## Repository map

- `python/lab_core` — frozen contracts, canonical hashes, scoring primitives.
- `python/lab_bench` — deterministic workload/context planning.
- `python/lab_adapters` — pure llama.cpp and Strata translators/parsers.
- `python/lab_updates` — pure release metadata, impact classification and
  paired A/B evaluation.
- `python/lab_api` — FastAPI controller, persistence, queues, SSE, Alembic.
- `python/lab_optimizer` — independent Optuna process.
- `python/lab_worker` — real worker discovery/execution plus explicit simulator.
- `apps/desktop` — Electron/React/Vite operator UI, secure IPC bridge and local
  Debian packaging script.
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
- The Electron renderer never receives the operator token or unrestricted
  network/filesystem access; all controller traffic uses validated IPC.
- Release import is offline; no endpoint fetches, downloads, replaces or installs
  an engine/model. A/B evidence is explicit and immutable, and no result
  automatically approves or installs an upgrade.
- A packaged desktop build, a simulated run and an offline fixture are never
  evidence of real performance or a validated recipe.
- `docs/prd.md` remains the product source of truth.
