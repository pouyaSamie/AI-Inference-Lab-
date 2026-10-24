# AI Inference Optimization Lab

AI Inference Optimization Lab is a local-first toolkit for exploring inference
configurations for `llama.cpp` and Strata. It combines a controller, an
independent Optuna optimizer, Linux workers, statistical benchmark evaluation,
and an Electron desktop app.

> **Development release:** the current desktop source is in the 0.6.x release
> candidate line. It is not production-ready or certified for general use.
> A clean-host installation, supported-hardware matrix, and complete live
> acceptance are still outstanding. See [production readiness](docs/PRODUCTION_READINESS.md)
> and the [acceptance matrix](docs/ACCEPTANCE_MATRIX.md) for evidence and open
> gates. No benchmark result or recipe should be treated as general performance
> advice; results apply only to the recorded hardware, model, engine, and test
> conditions.

## What it does

- Plans repeatable inference experiments across selected contexts and engine
  settings.
- Runs optimization through a separately supervised Optuna process.
- Collects worker observations and compares candidates with a same-context
  default baseline.
- Uses retained samples and paired statistical checks to decide whether
  measured results qualify a recipe.
- Provides a local desktop interface for setup, experiment review, recipe
  management, and guarded local recipe sessions.
- Includes an explicit simulated worker for offline development and testing.

The project is designed for Linux hosts with locally installed engines and
models. It does not provide model weights or engine binaries.

## Evidence and safety boundaries

- **Simulation is not measurement.** `lab-worker-sim` never launches an engine;
  simulated observations cannot qualify a recipe.
- **Real execution is explicit.** `lab-worker` runs configured local engine
  binaries and records measured observations. Review engine and model paths
  before starting it.
- **Qualification requires evidence.** A candidate is not a winner just
  because it has the highest throughput. It must meet the paired-baseline,
  confidence-interval, coverage, and guardrail requirements. Screening-only or
  incomplete evidence cannot qualify a recipe.
- **The desktop app is still a release candidate.** Offline UI tests and
  package builds do not constitute hardware or production acceptance.
- **Release workflows have limits.** Controller release assessments import
  operator-supplied metadata and do not approve upgrades. The desktop engine
  manager is a separate, explicitly confirmed workflow.

## Requirements

- Python 3.12–3.14 and [`uv`](https://docs.astral.sh/uv/)
- Node.js 20 or newer and pnpm 10 or newer for desktop development
- Linux for the real worker and Linux desktop package
- Installed supported engine builds and local model files for real inference

The simulated worker does not require a GPU, model download, or live inference
server.

## Get started

These steps set up the source workspace. The checked-in `.env.example` is a
development template: review every path and setting for your machine before
using it. In particular, configure the allowed model roots and installed engine
locations, and replace every `CHANGE_ME` credential with a unique random value.
Never commit your `.env` file.

```bash
uv sync --all-packages
cp .env.example .env
# Edit .env for your machine and generate fresh credentials.
uv run --env-file .env alembic upgrade head
```

Run the controller and optimizer in separate terminals:

```bash
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
```

For offline development, start the explicitly simulated worker:

```bash
uv run --env-file .env lab-worker-sim
```

To use real hardware, first configure and review the worker's model roots and
engine paths, then start the real worker:

```bash
uv run --env-file .env lab-worker
```

The controller listens on `http://127.0.0.1:8787` by default. Health is
available at `/health`; other operator endpoints require a bearer token. Keep
the controller on loopback unless you have separately designed and secured a
network deployment. The controller and optimizer must use different SQLite
database files.

## Desktop development

The Electron/React application is in `apps/desktop` and uses a separate npm
dependency lockfile from the pnpm workspace.

```bash
npm --prefix apps/desktop ci
npm --prefix apps/desktop run dev
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
```

The Linux package build uses the locally installed Electron distribution and
`dpkg-deb`:

```bash
npm --prefix apps/desktop run package:linux
```

Building a package does not install it. Installation, systemd deployment,
signing, and upgrade or rollback procedures are documented but have not passed
the project's live acceptance gate. See the [runbook](docs/RUNBOOK.md) before
attempting an installation.

## Development checks

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm install --frozen-lockfile
pnpm typecheck
npm --prefix apps/desktop ci
npm --prefix apps/desktop test
```

Contract generation is deterministic and offline:

```bash
pnpm generate:contracts
```

Generated contract files are checked in. Do not edit them by hand; the drift
check verifies them against the Python/FastAPI source.

## Project documentation

- [Product specification](docs/prd.md)
- [Architecture](docs/ARCHITECTURE.md) and [architecture decisions](docs/ADR/)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Production-readiness evidence and gates](docs/PRODUCTION_READINESS.md)
- [Operations runbook](docs/RUNBOOK.md)
- [Acceptance matrix](docs/ACCEPTANCE_MATRIX.md)
- [Desktop application notes](apps/desktop/README.md)

The implementation status and acceptance documents distinguish implemented
behavior from work that has only been authored, built, or tested offline.

## Security and data

The controller and optimizer keep separate local SQLite stores. Workers access
only configured model and engine locations; they do not download models or
replace engine binaries. The desktop renderer is sandboxed and routes
controller access through validated Electron IPC. Backups and restores are
offline operations; follow the [runbook](docs/RUNBOOK.md) and stop services
before restoring a database.

Do not use this development release as a remotely exposed service or a
production deployment without completing the documented security and
acceptance work.

## License

There is currently no `LICENSE` file in this repository. Until the project
maintainers add one, do not assume that public availability grants permission
to reuse, modify, or redistribute the code.
