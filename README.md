# AI Inference Optimization Lab

A local-first desktop lab for benchmarking and tuning **llama.cpp** and **Strata**.
Choose an installed model and engine, plan an experiment, follow its progress,
and compare measured configurations against a paired baseline.

The project combines an Electron/React desktop app, a FastAPI controller,
a separate Optuna optimizer, and Linux workers. Model files and benchmark
records stay on your machine.

**Status:** desktop version **0.6.2**, under active development. Local builds,
offline tests, and packaged startup have been verified; clean-target installation,
upgrade acceptance, signing, and the full hardware acceptance matrix remain
incomplete. See [implementation status](docs/IMPLEMENTATION_STATUS.md) and
[acceptance criteria](docs/ACCEPTANCE_MATRIX.md) for the evidence and limitations.

## What you can do

- Discover local model files and installed engine builds.
- Verify model identities and review configuration and preflight checks.
- Search engine settings across selected context lengths and objectives.
- Follow experiments, inspect retained samples, and compare results.
- Create recipes only from evidence that passes the qualification requirements.
- Use an explicit offline demo or simulated worker to explore the workflow.
- Back up and verify the controller and optimizer databases with offline tools.

The desktop also provides guarded local recipe sessions and a separate engine
maintenance workflow. Engine downloads require explicit confirmation. The
controller's release-intelligence workflow imports offline metadata and never
installs or approves an upgrade. Model downloads are not supported.

## How to use the lab

1. **Prepare:** add model folders and select an installed engine build in Settings.
   Review model verification; large files can take time to hash.
2. **Optimize:** choose a worker, model, engine, objective, contexts, and search
   budget. Review preflight and the immutable plan before submitting.
3. **Review:** follow Live Runs, compare the candidate with its same-context
   baseline, and save a recipe if the evidence qualifies.

A finite search finds the best configurations it tested, not a guaranteed global
optimum. Manual benchmarks can use different settings, workloads, cache states,
or timing methods. The current Strata search does not explore resident-expert
and asynchronous adaptation profiles; a manually tuned profile can be faster.
See [performance comparison findings](docs/PERFORMANCE_COMPARISON_2026-10-24.md).

## Build the desktop app

There is no installer committed to this repository. The Linux package can be
built from source with:

- Linux, `dpkg-deb`, and the system libraries required by Electron
- [uv](https://docs.astral.sh/uv/) and **CPython 3.13.16** for the bundled runtime
- **Node.js 22.12 or newer** and **pnpm 10.18.3**
- Registry access or populated caches for the initial dependency installation

From the repository root:

```bash
uv python install 3.13.16
uv sync --all-packages --frozen --python 3.13.16
pnpm install --frozen-lockfile
npm --prefix apps/desktop ci
npm --prefix apps/desktop run package:linux
```

The builder uses the installed Electron distribution and stages a private Python
runtime. It does not download models or inference engines. Output is written to
`apps/desktop/release/`; the architecture follows the Linux build host.

For an amd64 build of the current version:

```bash
sudo apt install ./apps/desktop/release/ai-inference-lab-desktop_0.6.2_amd64.deb
ai-inference-lab
```

The packaged app manages its local services and does not require developer tools
on the target host. Follow the [operations runbook](docs/RUNBOOK.md) before
installing or upgrading. Building or starting the package is not clean-host
acceptance.

## Develop from source

The Python workspace supports Python 3.12–3.14; desktop packaging requires the
exact runtime pin above. The desktop has its own committed npm lockfile and is
outside the pnpm workspace.

After installing dependencies, build and start the development desktop:

```bash
npm --prefix apps/desktop run build
npm --prefix apps/desktop run dev
```

Source development uses an independently started backend by default. Configure
its connection in Settings, or enable offline demo mode there to inspect fixture
data. Demo mode does not benchmark hardware or produce deployable evidence.

### Start independent backend services

Copy the development template, review the paths, and replace every `CHANGE_ME`
credential with a fresh value. Keep matching enrollment and optimizer credentials
consistent between their respective settings. Never commit `.env`.

```bash
cp .env.example .env
# Edit .env for your machine before continuing.
uv run --env-file .env alembic upgrade head
```

Run each component in its own terminal:

```bash
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
uv run --env-file .env lab-worker-sim
```

The simulation lane needs no GPU, weights, or live inference server. To measure
real hardware, configure the allowed model roots and engine paths, then run
`lab-worker` instead of `lab-worker-sim`.

The controller defaults to `http://127.0.0.1:8787`; `/health` is available for
health checks. Operator APIs require a bearer token. Keep development services
on loopback. Controller and optimizer databases must be separate files.

## Verify changes

With both dependency graphs installed:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
```

Generate contracts with `pnpm generate:contracts`. Python/FastAPI models are the
source of truth; generated OpenAPI, JSON Schema, and TypeScript files are checked
in and must not be edited by hand. Generation and drift checking work offline.

## Architecture and data boundaries

| Area | Responsibility |
| --- | --- |
| `apps/desktop` | Sandboxed renderer, validated Electron IPC, local service supervision, Linux packaging |
| `python/lab_api` | Controller, durable jobs, worker queue, persistence, and event streams |
| `python/lab_optimizer` | Independently supervised Optuna process and separate study database |
| `python/lab_worker` | Authorized discovery and real execution; separate explicit simulation lane |
| `python/lab_core`, `lab_bench`, `lab_adapters`, `lab_updates` | Frozen contracts, workload planning, pure engine translation, and offline release analysis |
| `contracts`, `packages/client-contracts` | Generated API schemas and TypeScript contracts |

- **Simulation stays separate.** Simulated observations cannot qualify a recipe.
- **Fastest is not automatically qualified.** Recipes require eligible retained
  samples, paired baselines, complete required coverage, confidence checks, and
  passing guardrails.
- **The renderer does not execute inference.** Controller traffic crosses
  validated main-process IPC; workers own engine execution.
- **Service lifetimes are explicit.** Minimize the packaged app to keep its local
  work running. Quitting stops desktop-managed services; independently deployed
  services have their own lifecycle.
- **Data removal is deliberate.** Settings → Start fresh moves supported local
  lab records to recoverable Trash while protecting configured model and engine
  assets. It is not secure erasure. Follow the runbook for backup and restore.

## Documentation

- [Product specification](docs/prd.md)
- [Architecture](docs/ARCHITECTURE.md) and [decision records](docs/ADR/)
- [Desktop application guide](apps/desktop/README.md)
- [Design system](docs/DESIGN_SYSTEM.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Operations runbook](docs/RUNBOOK.md)
- [Acceptance matrix](docs/ACCEPTANCE_MATRIX.md)
- [Production-readiness assessment](docs/PRODUCTION_READINESS.md)

## License

A license has not yet been added. See the repository's licensing status before
reusing or redistributing its code.
