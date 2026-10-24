# Implementation status

Last updated: 2026-10-21.

This document records what is actually implemented and what was actually run.
It is not a roadmap and does not upgrade reconnaissance into benchmark evidence.

## 1. Scope status

| Area | Status | Evidence / boundary |
|---|---|---|
| Phase 0 engine reconnaissance | Partial | llama.cpp and Strata version/help are captured as sanitized fixtures. The installed builds were also probed live in Phase 2. No 4K/32K benchmark or second-GPU comparison exists. See `docs/PHASE_0_FINDINGS.md`. |
| Python `uv` workspace | Implemented | Seven workspace packages resolve with `uv sync --all-packages`. |
| Frozen contracts | Implemented | Pydantic v2 frozen models in `lab_core`; canonical JSON/SHA-256 in `lab_core.ids`. Execution plans include `generated_files`. |
| Controller persistence | Implemented | FastAPI + SQLAlchemy 2.x + SQLite WAL + Alembic; revision head `9f2a7c1e4b6d` creates 23 tables, including durable release notices, assessments and comparisons. |
| Separate optimizer process | Implemented | `lab_optimizer` owns Optuna and a distinct SQLite URL. FastAPI imports no Optuna. |
| Durable worker protocol | Implemented | Poll, lease, ack, renewal, complete, idempotent replay, conflict `409`, lease expiry/requeue. |
| Engine adapters | Implemented, pure | llama.cpp and Strata help/JSON parsers, typed validation and plan builders, productionized against the installed builds. No subprocess/network/filesystem I/O; a test enforces imports. |
| Adapter conformance | Implemented, offline | Golden server/bench/status fixtures, option-line capability parsing, strict candidate types, split llama.cpp help checks, Strata profile de-duplication and generated-file digest tests. |
| Planning | Implemented, snapshot-only | Cached snapshots; stale/missing inventory returns `202 PREFLIGHT_REQUIRED` plus a queued `SCAN`. |
| Real Linux worker | Implemented | Observed engine/model discovery, hardware/GPU telemetry, SHA-256 cache, sandboxes, journal, GPU UUID `flock` leases, argv-only runner, crash recovery, cancellation. |
| Real command handlers | Implemented | `SCAN`, `PREFLIGHT`, `CLAIM_TRIAL`, `PAUSE`, `CANCEL`, `VERIFY_RECIPE`; `PROMOTE` is dry-run/idempotent only. |
| Phase 1 execution lane | Explicitly simulated | `lab-worker-sim` emits `simulated=true` and `measurement_status=simulated` only. |
| Real execution lane | Implemented, not fully exercised | `lab-worker` emits only `simulated=false`. Live inventory/scan smoke passed; no real preflight or trial was run yet. Trials run a tokenizer-backed workload ladder, retain primary-level samples and perform a near-capacity context check when a server is available. |
| Statistical finalization | Implemented, verified offline | A fixed-default baseline is asked once per selected context before TPE candidates. Primary-level repeats are retained as `BenchSample`s. Finalization computes the PRD objective ratio, paired percentile bootstrap interval and the >=5% / 95% qualification gate, with per-context and complete-coverage cross-context rankings. |
| Recipe qualification | Implemented, rejects simulation and inconclusive evidence | Simulated or screening-only evidence returns `409`. Measured evidence must also have an eligible paired baseline, retained samples and a qualification decision before a recipe is built; accepted recipes are marked `validated`. No real recipe exists yet. |
| SSE | Implemented | Initial `snapshot`, sequenced events, `event.gap` for stale `Last-Event-ID`, bounded page endpoint. |
| Generated contracts | Implemented, checked in | OpenAPI, JSON Schema/manifest and strict TypeScript declarations; offline generation and drift gate. |
| systemd packaging | Authored, not installed | Three service units plus an environment template and security notes under `packaging/systemd/`; installation/boot acceptance is blocked and documented in `docs/RUNBOOK.md`. |
| Electron/React UI | Implemented, verified offline | Ten primary screens, generated TypeScript contracts, offline demo fixtures, SSE replay, secure Electron main/preload, validated IPC API/SSE proxy and native report save. Updates now imports offline release metadata, shows impact/decisions and displays non-approving A/B results. Unit tests, typecheck, production build and a local `.deb` build pass. No full GUI live-controller run yet. |
| Desktop packaging | Built, not installed | `apps/desktop/scripts/package-linux.mjs` builds a `.deb` from the installed Electron distribution using `dpkg-deb`; `chrome-sandbox` is root-owned mode 4755 in the archive. Installation, signing, upgrade/rollback and AppImage remain approval-gated; see `docs/RUNBOOK.md`. |
| Tokenizer-backed workloads | Implemented, offline | Frozen `lab-synthetic-v1` corpus, engine tokenizer fitting, prompt-level ladder, repeated-primary medians and near-capacity truncation checks. No live serving run yet. |
| Release intelligence | Implemented, offline only | Pure `lab_updates` metadata/classification/evaluation; durable notices, assessments and A/B comparisons; deterministic P0/P1/P2 and capability diffs; pin/defer decisions; immutable evidence with `409` conflicts; non-approving results. No remote polling, artifact download, installation or real A/B execution. |
| Security hardening | Implemented, verified offline | New tests prove public health only, operator/worker/optimizer credential scoping, separate enrollment and disabled-worker rejection. Existing Electron IPC/navigation tests remain. No live network/egress audit. |
| SQLite backup/restore | Implemented, verified offline | Online two-store backup, versioned SHA-256/size manifest, integrity check, offline restore with pre-restore snapshot and WAL/shm refusal. CLI exercised on temporary files only; no production database touched. |
| Operations runbook | Authored, not executed | `docs/RUNBOOK.md` covers install, systemd, enrollment, desktop package, upgrade/rollback, backup/restore, uninstall/data retention and live acceptance. Privileged steps remain approval-gated. |
| Phase 8 live acceptance | Blocked | No systemd unit, `.deb` or production database was installed/restored; no target-host pinned-manifest acceptance, live GUI, hardware matrix or real release A/B. See `docs/ACCEPTANCE_MATRIX.md`. |

## 2. Runtime components

- **`lab-api`** — controller entry point on `127.0.0.1:8787` by default.
  Persistent sessions, auth, planning, experiment lifecycle, command queue,
  optimizer outbox/inbox, SSE and runtime lease reconciliation.
- **`lab-optimizer`** — independent poller/worker for Optuna `ask/tell` work.
  It owns the Optuna database and never touches controller tables.
- **`lab-worker`** — real Linux worker. It enrolls, discovers configured engines
  and model roots, uploads snapshots, heartbeats, polls commands, leases GPU
  UUIDs, runs verified argv-only processes and completes typed evidence.
- **`lab-worker-sim`** — explicit simulated worker with deterministic inventory
  and observations; it never launches an engine or leases a GPU.
- **`apps/desktop`** — local Electron/React operator console. It is a view and
  control surface only: the sandboxed renderer reaches the controller through a
  validated main-process IPC proxy, never owns durable jobs and never receives
  the bearer token.

## 3. Desktop UI behavior

- Ten primary screens: Overview, Models, Engines, Workers, Optimize, Live Runs,
  Compare, Recipes, Updates and Settings. They use generated contract aliases
  rather than hand-written duplicate payload interfaces.
- The Optimize flow renders fresh/stale inventory, worker/GPU/model/engine
  selection, six explicit steps, preflight blockers and an immutable plan
  submission. It does not run a worker call from planning.
- Compare renders controller finalization, paired intervals, per-context
  winners, incomplete coverage, `VALIDATED_WINNER`, `NO_VALIDATED_WINNER` and
  `SIMULATED` without inferring a winner from throughput.
- Live Runs consumes sequenced SSE with replay floors, reconnect/backoff and
  stale-sequence resets. It does not poll an engine or process.
- A system tray can reopen the window or quit the UI. Closing the window hides
  it only when a tray exists; controller-owned jobs are never tied to window
  lifetime. Minimal desktops without a tray fall back to normal exit.
- Offline demo mode is explicit (`?demo=1` or Settings) and visibly labelled on
  every screen. Its fixtures cannot create/cancel experiments or qualify a
  recipe.
- The renderer has `contextIsolation`, `sandbox`, no Node integration, no
  webviews, denied permissions and blocked foreign navigation. Packaged assets
  use `lab://app` with strict CSP; development uses only loopback Vite.
- Hardware acceleration is disabled before ready. `LAB_DESKTOP_ENABLE_GPU=1` is
  an explicit restart-requiring override; shared-GPU qualification then needs
  contamination verification.
- Updates imports approved release metadata offline, displays P0/P1/P2 impact,
  reasons, stale-inventory and candidate-hash blockers, supports pin/defer
  decisions and requests a frozen A/B proposal. It renders per-context intervals
  and explicitly shows that `upgrade_approved` is false. It never checks an
  upstream feed, downloads, replaces, launches or installs an engine/model.

## 4. Release intelligence behavior

- `python/lab_updates` is pure: it imports no network, process, filesystem or
  hardware modules. It defines frozen release metadata, deterministic path/area
  classification, capability diffs, frozen A/B plans and evidence evaluation.
- `POST /api/v1/releases/check` imports operator-supplied metadata and never
  contacts an upstream service or artifact host. A repeated metadata digest
  returns the existing notice; assessments bind notice, worker/model digest,
  installed executable hash, inventory revision and policy version.
- CUDA/backend/MoE/KV/context/model-loader paths are P0;
  scheduling/threading/batching/server API are P1; docs/tests are P2. Unknown
  paths are P1 and require smoke testing. Stale inventory can raise P2 to P1.
  Missing installed-engine identity makes the release non-applicable.
- Notices can be pinned or deferred with an audit event. `GET
  /api/v1/releases` and `GET /api/v1/releases/{id}` expose stored notices,
  assessments and comparisons; no endpoint mutates an installed artifact.
- `POST /api/v1/comparisons` requires an applicable P0/P1 assessment, a
  complete verified model identity digest (`model_identity_complete=true`), the
  candidate executable SHA-256 and the selected worker/model. It freezes both
  engine identities, workload, contexts and thresholds. Missing hashes or
  incomplete model hashes return `409`.
- `POST /api/v1/comparisons/{id}/evidence` accepts paired measured samples.
  Identical terminal evidence is replay-safe; different terminal evidence is
  `409`. Simulated or non-measured evidence is `INCOMPATIBLE`; missing contexts,
  identity mismatches and baseline guardrail failure are also incompatible.
  Candidate guardrail failure and significant regression retain the current
  engine. `upgrade_approved` is always `false`.
- A regression test asserts that the installed snapshot engine hashes and model
  records are unchanged by the complete import/assessment/comparison workflow.
- No real A/B evidence exists yet. No comparison has been executed against an
  installed candidate, and no update has been downloaded or installed.

## 5. Real worker behavior

### Discovery

- Executes only configured `--version`/`--help` probes. Every binary is
  SHA-256 hashed and registered under a trusted ID. A changed engine digest fails
  closed and requires a fresh scan.
- Parses GGUF headers and shards, plus Strata pack manifests, under
  operator-approved roots. Discovery never writes to a model root.
- Hashes files into a persistent `(size, mtime_ns)` cache. The first full scan
  of the ~270 GiB model root is expensive; later scans reuse cached digests.
- Resolves Strata `conversions.json` source shards read-only. Every shard must
  match an exact basename and byte size; all resolved shards enter the model
  files and are hashed when enabled. Missing, ambiguous or changed shards
  produce no `--native` argument.
- A snapshot with missing hashes is still plannable but carries warnings. The
  real executor rejects preflight/trials until all model hashes are complete.

### Execution and ownership

- Commands run in per-command sandboxes beneath `LAB_WORKER_STATE_ROOT`.
- Processes use argv arrays (never a shell), a sanitized environment, a new
  process group/session and verified executable hashes.
- Cancellation and timeout terminate only the recorded process group. The
  worker never terminates an unowned GPU process.
- The append-only journal records command, lease, process group, start ticks and
  log paths. Recovery kills only a still-matching recorded group; interrupted
  commands are not invented as successful.
- GPU access uses per-UUID advisory `flock` files plus a JSON owner record.
  `CUDA_VISIBLE_DEVICES` is scoped to the lease. CPU-only llama candidates
  (`gpu_layers=0`) do not acquire a GPU lease.
- Long trials renew the same lease token/generation. A lease timeout alone does
  not authorize another worker to take over a live engine.

### Evidence boundaries

- llama.cpp trials collect native `llama-bench` metrics where present and a
  streaming `/v1/chat/completions` serving lane. Missing metrics stay missing;
  native-only evidence is `screening_only`.
- The serving lane fits the frozen corpus with the target engine tokenizer:
  llama.cpp uses `/apply-template` + `/tokenize`; Strata uses
  `/v1/messages/count_tokens`. Every prompt level runs once, the primary level
  is repeated and medianed, and the near-capacity level is a separate probe.
- Character-estimated prompts are labelled `character-fallback` and cannot
  produce measured evidence. Silent truncation, context overflow or a measured
  prompt load outside tolerance produces `CONTEXT_MISMATCH`.
- The engine adapter parses server `/props` or `/v1/status` for context identity
  and engine fields. Client-observed TTFT/usage keep precedence; a status
  document is not treated as measured peak VRAM or throughput.
- Preflight starts a CPU-offload (`--n-gpu-layers 0`) server at the highest
  supported requested context and records the effective context. This proves
  allocation at that context, **not** GPU residency. Lower requested contexts
  inherit that proof explicitly; GPU fit is measured by trials.
- The Phase 4 serving harness performs the near-capacity context check with
  tokenizer-fitted prompts and actual usage. Strata full-context proof remains
  `INCONCLUSIVE` until that harness runs against a real approved process; the
  installed build's missing calibration commands are not replaced with a
  guessed command.
- Real observations always have `simulated=false`; simulation can never produce
  a validated recipe.

### Statistical finalization

- The scheduler asks one fixed-default `BASELINE` candidate for every selected
  context before normal TPE candidates. Baseline asks use the adapter's
  documented defaults; they are not TPE proposals and do not consume the
  distinct-candidate search budget.
- The worker retains every completed primary-level repeat as a `BenchSample`.
  Simulation emits deterministic labelled samples but remains non-promotable.
- Candidate `tell` values are objective scores relative to the paired baseline
  rather than raw throughput at different contexts.
- `lab_core.finalization` recomputes evidence from stored observations. It uses
  paired sample ratios, a deterministic percentile bootstrap and the declared
  gate (default >=5% improvement and a 95% interval strictly above baseline).
- Results expose per-context evaluations, `VALIDATED_WINNER`,
  `NO_VALIDATED_WINNER` or `SIMULATED`, and cross-context rankings that require
  the complete selected context set.
- `POST /api/v1/recipes` recomputes finalization and returns `409` unless the
  candidate is measured, baseline-paired, sample-complete and qualified.
  Candidate recipes are stored with `status=validated`; promotion remains a
  separate guarded action.
- Simulated, character-fallback, screening-only, native-only and
  hash-incomplete evidence remain ineligible.

## 6. Verification actually performed

The following commands were run in this workspace on 2026-10-21 and produced the
results shown. They must be re-run after any change.

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 122 files already formatted

uv run mypy python
# Success: no issues found in 98 source files

uv run pytest -q
# 73 passed in 11.72s (repeated three times)

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# generated contracts tsc pass; desktop renderer/Electron tsc pass

npm --prefix apps/desktop test
# 9 test files, 29 tests passed

npm --prefix apps/desktop run build
# Vite production renderer + Electron main/preload build passed
# dist/assets/index-CQZMYOhX.js 336.50 kB (gzip 97.12 kB)
# dist/assets/index-DRtlQKTH.css 22.81 kB (gzip 5.15 kB)

npm --prefix apps/desktop run package:linux
# built ai-inference-lab-desktop_0.1.0_amd64.deb (84.0 MiB)
# 88,126,518 bytes
# sha256 7778d186170beb4ed978726fc15900ea0bb669b9b9515f00ffa72084a8ba7d1f
```

The Phase 8 backup CLI was exercised on temporary SQLite files: `backup`
created controller/optimizer copies and `manifest.json`, `verify` matched both
digests, and `restore` produced a database containing the original row. The
production stores were not opened.

The `.deb` was inspected with `dpkg-deb --info` and `dpkg-deb --contents`:
the control metadata, launcher, desktop entry, icon and packaged app resources
are present with normal modes, and `chrome-sandbox` is archived as root-owned
mode `4755`. The
package was extracted and the packaged Electron binary launched with
`--no-sandbox` for a short smoke test with no preload or CSP console errors.
That is a UI packaging smoke test, not an installation or a live controller run.

`systemd-analyze verify packaging/systemd/lab-*.service` parsed all three units
and reported only that the deployment paths
(`/opt/ai-inference-lab/.venv/bin/lab-*`) do not exist on this host. The units
were **not** installed, enabled or started.

### Live discovery probe

The installed engines were probed through the real worker discovery code:

```text
ENGINE llamacpp 0.7.0-dev build 701 commit dd002b91f sha256 f0f8a33ee87c...
  26 descriptors; server and bench help hashes recorded separately; no warnings
ENGINE strata   0.1.44.1  build 0.1.44.1 sha256 fa29349e3eaa...
  19 descriptors; version/help read from stderr; no warnings
```

The adapter conformance suite parses the committed installed-build fixtures and
checks that every emitted server flag appears in server help, every emitted
native flag appears in `llama-bench` help, invalid candidate types fail, Strata
profiles contain no duplicated managed flags and generated-file digests match.
It does not launch an engine.

The configured model root produced 8 artifacts without hashing: 6 GGUF models
(GLM-4.7-Flash-Q4_K_M, Qwen3.8-27B-UD-IQ4_XS,
Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp, gemma-4-12B-it-QAT-Q4_0,
Qwen3.6-35B-A3B-UD-Q4_K_M, Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M)
and 2 Strata packs. All were correctly reported `verified=false` because
hashing was disabled for the probe. No weights were modified.

A Phase 4 read-only discovery pass resolved both Strata packs with no warnings:

```text
Strata-Qwen3.8-Flash-Next-Q2_0-coder-iq1_m
  native_shard .../IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
Strata-Qwen3.8-Flash-Next-Q2_0-q2_0
  native_shard .../models/Q2_0/Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf
```

A read-only Strata profile check emitted `--native <resolved shard>` and no
duplicate managed arguments. The source shards were not opened for writing.

### Live controller/worker smoke

A temporary controller (loopback port 8790, temporary SQLite stores under
`/tmp/opencode/lab-phase2`) was migrated and started in `LAB_EXECUTION_MODE=real`.
A real `lab-worker` with a separate state root:

- registered with the enrollment credential;
- uploaded a real hardware/engine/model snapshot;
- sent heartbeats;
- polled, acked and completed a durable `SCAN` command
  (`cmd_3e8f46b022ff472a9d6a7c8ea97b7772`) in about 1.5 s with hashing disabled;
- returned snapshot revision 5 to the controller.

This proves the outbound command path, lease/ack/complete flow and real
inventory upload. It does **not** prove a real preflight, trial or recipe.

### Automated suite

The suite starts a live loopback controller, simulated worker and optimizer with
temporary stores. It covers planning and `PREFLIGHT_REQUIRED`, experiment and
Optuna lifecycle, simulated trials, recipe rejection for simulation, idempotency
conflicts, SSE gap replay, and command lease/ack/completion resilience. Phase 2
unit coverage uses a synthetic GGUF file, the trusted Python interpreter, fake
probe scripts, GPU lease exclusivity, runner success/timeout/cancel and journal
crash recovery. Phase 3 adds offline golden conformance tests for installed
llama.cpp server/bench output, Strata stderr help/status output, typed candidate
rejection, profile de-duplication and generated-file digest checks. Phase 4
adds offline corpus/tokenizer tests, workload-suite median and context-rejection
coverage, and two-shard Strata source resolution tests. Phase 5 adds offline
paired-bootstrap, qualification/no-winner, incomplete-coverage, simulated
rejection and baseline-default tests, plus end-to-end simulated assertions for
baseline scheduling and non-promotable finalization. A synthetic measured
baseline/candidate pair is also driven through the full recipe endpoint to prove
the accepted `validated` path; it is test data, not engine evidence. No Python
test requires a GPU, downloaded weights, a live engine or external network
access.

The desktop suite uses Vitest + jsdom and renders the React shell against offline
fixtures. It verifies every primary screen and the explicit demo label, the
measured no-winner and simulated finalization presentations, generated contract
compatibility, API path/method/body restrictions, report basename/content
bounds, trusted frame origins and the main-process API proxy's bearer,
redirect, size and error behavior. It does not launch Electron or require a
display, GPU, controller or network.

## 6. What is not proven

These are intentional boundaries, not hidden gaps:

- No real `PREFLIGHT` or `CLAIM_TRIAL` has been executed end-to-end. The model
  root, including all Strata source shards, has not been fully hashed (about
  270 GiB).
- The tokenizer-backed serving harness has not run against a live server. The
  llama.cpp tokenizer routes and Strata `count_tokens` endpoint are covered
  offline, not by a real request.
- No real 4K/32K/128K latency, VRAM, quality or thermal measurement exists.
- No real baseline/candidate pair has been collected, so statistical
  finalization and recipe qualification are proven by offline tests only. There
  is no validated real recipe.
- The simulated end-to-end run classifies its finalization as `SIMULATED` and
  exposes no winner even though it now schedules a baseline and retains samples.
- No second GPU (for example L40S) comparison exists; only the RTX 3060 is
  installed.
- Strata full-context proof is `INCONCLUSIVE` until a real approved serving run.
  Its native benchmark command is not exposed by the installed build; the
  `--mtp` form is not emitted.
- `PAUSE` currently stops the active trial at the process-group boundary; it is
  not a resumable checkpoint. Safe-boundary pause remains a lifecycle item.
- Simulated throughput, VRAM/telemetry and OOM values are deterministic test
  data, not measurements.
- No load test at 1,000 concurrent polling workers is claimed.
- TLS termination, remote authentication, update intelligence and release
  qualification do not exist yet.
- The Electron UI has not been run against a live controller/worker through a
  full experiment. No graphical session smoke test can substitute for that.
- Normal sandboxed Electron launch from the cached development install fails on
  this host because its `chrome-sandbox` helper is user-owned mode `755`; it was
  not made root-owned `4755` without approval. The UI smoke test used
  `--no-sandbox`, and the archived `.deb` records the correct helper mode.
- The `.deb` was built and inspected but not installed, signed, upgraded or
  rolled back. AppImage packaging was not produced because `appimagetool` is not
  installed and network/tool acquisition was not authorized.
- The desktop dependency install has no committed `package-lock.json`; the
  current `node_modules` is environment-specific and was not recreated from a
  clean registry install. Reproducible dependency locking remains open.
- Optuna and controller writes are not atomic; recovery is deterministic and
  conservative rather than a two-phase commit.
- The systemd units are authored and syntax-checked only; they are not installed
  or enabled.

## 7. Generated artifacts

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

## 8. Quick start status

The documented quick start is in `README.md` and `AGENTS.md`:

```bash
cp .env.example .env
# replace every CHANGE_ME secret with a 16+ character random value
uv run --env-file .env alembic upgrade head
uv run --env-file .env lab-api
uv run --env-file .env lab-optimizer
uv run --env-file .env lab-worker        # real lane
# uv run --env-file .env lab-worker-sim # explicit simulation lane
```

`/health` is public. Operator, enrollment, worker and optimizer
routes require the corresponding bearer token. The real worker needs readable
engines/models and GPU access; the simulated lane needs neither.

## 9. Next gate

Phases 0/1 through 7 are committed locally. Phase 7 adds offline release
intelligence and frozen A/B records; it does not execute a candidate, download
an artifact or approve an upgrade. The open evidence items remain unchanged:
full model/source-shard hashing, a real preflight, one real low-impact tokenized
trial, a real near-capacity context check and a real measured A/B run must
happen before any real validated recipe or upgrade recommendation can exist. A
UI run is also still required against a live controller/worker and must be
explicitly approved. See `docs/NEXT_STEPS.md` and the phase reports under
`docs/progress/`.

## 10. Self-contained desktop 0.2.0 — 2026-10-21

Implemented the requested desktop-managed local runtime. The `.deb` now contains
relocatable uv-managed CPython 3.13.16, hash-locked dependencies, all seven
packages, migrations and the frozen simulated CLI fixtures. Electron main owns
a private supervisor; controller, optimizer and worker remain distinct processes.
The supervisor locks its per-user profile, refuses unsupported controller schemas,
snapshots existing stores before migration, binds an OS-assigned loopback socket,
generates scoped credentials, supervises bounded restarts and shuts down on
parent EOF. Keyring fallback rotates the same owned local worker's enrollment
without changing job identity or re-enabling disabled workers. Model/engine roots
and the external Strata environment are not bundled or modified.

Settings provides native path selection, startup/configuration/retry status and
no manual API/token setup in packaged mode. Optimize waits for usable discovery.
Close keeps the desktop/runtime in the tray; Quit shuts down local work safely.
The renderer stays sandboxed, isolated and without direct Node/network access.
Inherited development settings and `.env` do not configure packaged services.

Release fixes include a committed npm lockfile, clean `npm ci`, Electron 41.10.6
and Vite 8.3.5, explicit desktop CI installation/tests/build/package smoke gates,
generated contract refresh (preserving the existing candidate-ID change), and
unignoring existing renderer `src/lib` sources that the broad Python `lib/` rule
had accidentally excluded. The executable is renamed to
`ai-inference-lab-desktop`: the old generic `electron` basename caused
`app.isPackaged=false`, which the actual packaged renderer test detected.

Observed verification (commands actually executed):

| Command / scenario | Observed result |
|---|---|
| `.venv/bin/ruff check` | Passed |
| `.venv/bin/ruff format --check` | 126 files formatted |
| `.venv/bin/mypy python` | Passed, 99 source files |
| `.venv/bin/python -m pytest -q` | **81 passed**; loopback-enabled test execution, temporary databases |
| `.venv/bin/python scripts/check_contracts.py` | Contracts current after exporter regeneration |
| `npm --prefix apps/desktop ci --cache /tmp/inference-lab-npm-cache` with network/proxy options | Clean dependency install succeeded; npm reported **0 vulnerabilities** |
| `pnpm typecheck` | Generated client and desktop type checks passed |
| `npm --prefix apps/desktop test` | **36 passed** across 11 files |
| `npm --prefix apps/desktop run package:linux` | Renderer/main builds and offline Python staging passed; `.deb` built, **138.4 MiB** |
| `dpkg-deb --info` / `--extract` to `/tmp/inference-lab-0.2.0-extracted` | Package inspected and extracted; no package installation |
| `LAB_TEST_BUNDLED_BACKEND=/tmp/inference-lab-0.2.0-extracted/opt/ai-inference-lab/desktop/resources/app/backend .venv/bin/python -m pytest -q tests/test_desktop_runtime.py` | **7 passed**, including simulated completion/recipe rejection, duplicate launch, controller crash/recovery, profile restart with changed session pepper, disabled-worker protection and parent-EOF shutdown |
| `node scripts/smoke_packaged_desktop.mjs apps/desktop/release/linux-deb/opt/ai-inference-lab/desktop/ai-inference-lab-desktop /tmp/inference-lab-desktop-0.2.0.png` | Passed on the available X11 display, isolated empty profile: version 0.2.0, `packaged=true`, renderer `require=undefined`, sandbox enabled, local controller/optimizer online and `needs_configuration` |
| `git diff --check` | Passed |

The package is
`apps/desktop/release/ai-inference-lab-desktop_0.2.0_amd64.deb`.
SHA-256: `7ac31d25a2eebba24ffb72e031e293f0b10a63b3c8fab749ce0a1a6f2c1b41fd`.
The rendered startup/setup screen was visually inspected. Initial extracted
simulation failed because checkout ancestors had hidden a missing fixture
bundle; adding frozen fixtures fixed it. Headless Ozone attempts exited before
window startup; the display-backed smoke passed without disabling the sandbox.
The smoke's debugging port exists only in its isolated test invocation.

**Not claimed:** installation/upgrade of the new `.deb`, a clean target-host
acceptance run, real engine execution or GPU qualification, full tray/native
chooser interaction coverage, 24-hour retention/load gates, logout survival,
systemd installation, signing, or production database import/restore. The older
0.1.0 package was observed installed before these changes; it has not been
replaced. Existing user changes in candidate identity/tests and `attic/` were
preserved.

## 11. Desktop 0.2.1 — show the window on launch

The installed package was observed at 0.2.0. The operator reported a tray icon
without a visible startup window. Startup previously constructed a hidden
BrowserWindow and relied exclusively on `ready-to-show`, whereas the tray action
explicitly showed/focused it. The window now starts visible and startup explicitly
restores/shows/focuses it. The ready callback focuses only a still-visible window,
so an intentional early close-to-tray is respected. Close-to-tray and second-launch
restoration remain in place.

Observed commands/results:

- `npm --prefix apps/desktop run typecheck`: passed.
- `npm --prefix apps/desktop test`: 36 passed across 11 files.
- `npm --prefix apps/desktop run package:linux`: built 0.2.1, 138.4 MiB.
- `node scripts/smoke_packaged_desktop.mjs apps/desktop/release/linux-deb/opt/ai-inference-lab/desktop/ai-inference-lab-desktop`:
  passed on the available display in an isolated profile; `version=0.2.1`,
  `packaged=true`, renderer `require=undefined`, `visible=visible`, sandbox enabled,
  runtime `needs_configuration`. The smoke now explicitly checks startup visibility.
- `git diff --check`: passed.

The 0.2.1 package is built, not installed. No real worker/model configuration or
hardware evidence was created by this UI verification.


## 12. Desktop 0.3.0 — folder discovery and saved setup wizard

Replaced seven prominent path selectors with a three-step wizard: folders,
discovered engine builds, review/save. Folder configuration is persisted privately
and atomically by Electron main; step/completion state persists in local storage.
Settings provides Edit setup, add/remove folders and rescan. Advanced individual
paths remain collapsed for unusual installations. Active jobs block changes.

The real worker now publishes metadata-only model inventory when only model
folders are configured. Removed the blanket exclusion of GGUFs under Strata-named
directories; split shards are grouped, mmproj/MTP sidecars and .done files excluded.
A bounded, read-only locator discovers engine builds and adjacent bench/library,
Strata script and interpreter paths. Explicit build selection uses a validated
candidate ID across IPC. Discovery does not execute or download engines.
Real planning queues a durable hash scan for incomplete model identities; browsing
unverified metadata cannot become qualifying evidence. Runtime status refreshes
from cached worker snapshots. Fixed global sibling margins that offset grid cards,
added responsive setup spacing and wrapping top-bar actions.

Observed validation:

- Final `.venv/bin/python -m pytest -q`: 87 passed (34.19s), including
  the real-planning hash-verification regression.
- Desktop suite: 39 passed across 11 files, including saved wizard state,
  discovered-build selection and persisted folder removal.
- Desktop TypeScript checks passed.
- Bundled-runtime tests: 8 passed (21.72s), using the staged private Python runtime.
- Ruff lint/format, mypy (100 source files), contract drift and diff checks passed.
- Offline package build succeeded: 0.3.0, 138.4 MiB. The first restricted build
  could not write uv's shared cache; the approved offline-cache build succeeded.
- Display-backed packaged smoke passed in an isolated profile with sandbox on,
  renderer require undefined, packaged=true and visible startup window.
- Read-only metadata discovery of the operator's model/inference roots found
  10 models and six build locations. No engine was selected or workload launched.
- Packaged wizard navigation, Save/reload persistence and Models inventory passed;
  overview panel alignment and no horizontal overflow checked. Screenshots of
  folders, discovered builds and Models were visually inspected.

Package: apps/desktop/release/ai-inference-lab-desktop_0.3.0_amd64.deb.
SHA-256: 7798c731663805f816e3896f6d3f6f55e1f16c818045cca8347e399059ffebe8.
Built, not installed. Native chooser/tray interactions, clean-host installation,
real engine capability/benchmark qualification and hardware evidence remain
separate acceptance gates. Existing operator configuration/model files were not
modified by the isolated smoke.


## 13. Desktop 0.4.0 — explicit engine management and close lifecycle

The operator explicitly requested official update checks/suggestions on startup,
latest installed-build recommendations, confirmed installation, old-build removal,
and a close-time Quit/Minimize choice. ADR 0019 documents this desktop scope
expansion; controller release imports and evidence qualification remain offline.

Engine discovery now reads generated build metadata and labels folder-version
hints separately. The newest identifiable complete installed build per family
receives a recommendation. Official stable release checks use only the fixed
llama.cpp/Strata GitHub sources, bounded requests and checksum-verified llama.cpp
binary-release pointers. Strata native asset versions are distinguished from its
desktop application version. Same-base development versions remain a comparison
unknown, rather than asserting that installing a stable release is an upgrade.
Startup suggestions can be disabled with a persisted preference.

The desktop installer requires a backend/asset choice and native confirmation.
It verifies archive byte counts and SHA-256, uses bundled
Python's bounded safe extraction, never runs installer scripts, then atomically
publishes a private side-by-side installation. Strata requires matching verified
control/server and standalone Python files. Idle services restart to discover the published build. The new build is selected separately;
no old evidence is changed or approved. Quit cancels an active download/extraction
and waits for staging cleanup. Configuration/engine operations are serialized and
renderer mutation requests blocked while these operations run.

Remove build uses native confirmation and Trash for inactive isolated directories.
Selected/shared builds, broad source/runtime roots and model-containing directories
are protected. No existing operator engine/model directory was changed by this
implementation or its acceptance checks.

Closing now always asks Quit, Minimize to tray (taskbar fallback), or Cancel.
Quit does not show a second confirmation after the close prompt. The reported
Object-has-been-destroyed error came from reading window.webContents.id in closed;
the sender ID is now captured while alive, and late visibility callbacks guard
against destroyed windows.

Observed verification:

- `.venv/bin/python -m pytest -q`: 94 passed (36.08s).
- Ruff lint/format passed; mypy passed for 101 source files; contracts current.
- `npm --prefix apps/desktop test`: 57 passed across 14 files.
- `npm --prefix apps/desktop run typecheck`: passed.
- `npm --prefix apps/desktop run build`: passed.
- `npm --prefix apps/desktop run package:linux`: built 0.4.0, 138.4 MiB.
- `LAB_TEST_BUNDLED_BACKEND=<staged backend> .venv/bin/python -m pytest -q tests/test_desktop_runtime.py`:
  eight passed (23.70s).
- `node scripts/smoke_window_lifecycle.mjs`: real Electron minimize, cancel, quit
  and destroyed-window cleanup passed on the available display, sandbox enabled.
- Packaged desktop smoke, isolated profile with automatic checks explicitly off:
  version 0.4.0, packaged=true, require undefined, visible startup, sandbox enabled;
  wizard save/reload, aligned overview and model browsing passed (10 models,
  six build locations). The engine-step screenshot was visually inspected.
- A read-only invocation of the implemented checker against official release APIs
  passed: llama.cpp stable v0.7.0 resolved eight Linux assets; same-base local
  0.7.0-dev remains unknown. Strata native 0.1.47 offers six Linux assets and a
  matching control bundle, newer than discovered 0.1.44.1. No engine archive was
  downloaded or installed during this check.
- `node scripts/smoke_engine_install.mjs`: passed with the actual bundled
  extractor/downloader/publication path, synthetic checksum-verified llama.cpp
  and Strata archives, and matching Strata server/interpreter discovery. No
  engine was executed. The restricted spawn needed the approved sandbox override.
- `git diff --check`: passed.

The previous UI wording assertion forbidding all engine downloads was updated
for the explicitly expanded scope; demo mode still hides engine-management actions
and controller qualification remains non-approving.

Package: apps/desktop/release/ai-inference-lab-desktop_0.4.0_amd64.deb.
SHA-256: dc464b55f08e8ae4a4190a352e619c6341bb20f6587d2a658d6c37909deff7a5.
The installed package was observed at 0.3.0; the new 0.4.0 package is built, not installed.
Real official archive installation/driver compatibility,
native confirmation/Trash interaction on the target desktop, clean-host upgrade
and real inference qualification remain acceptance gates. Installer behavior is
covered with offline synthetic downloads/extraction, including corrupt archives,
escaping paths/links, cancellation and preserved current installations.


## 14. Desktop 0.5.0 — hardware recommendations and import readiness

Observed on 2026-10-22. The default engine update action now selects a published
build using a hardware profile detected once per desktop startup. Public metadata
checks reuse that profile. NVIDIA compute capability/driver thresholds, observed
AMD gfx architecture and physical Vulkan device support drive the recommendation;
unknown compatibility remains explicit. Manual archives are under Advanced. CUDA
llama.cpp builds require their matching checksum-verified runtime archive. Worker
execution checks and benchmark telemetry remain independent of this desktop cache.

First model import queues automatic SHA-256 verification after fast metadata
browsing. A private progress sidecar supplies byte/file counts and current file.
Hashes persist after each completed file and are reused only on matching size and
mtime; interrupted partial files never become verified identities. Shutdown can
cancel large-file hashing between chunks. Verification scans reuse cached hardware.
Planning remains snapshot-only and queues/reuses a durable scan rather than making
live worker calls. An optional targeted model scan is sent only to workers declaring
that capability; older workers retain full-scan payload compatibility. Contracts
were regenerated through the existing exporters.

The Optimize wizard waits for verification, refreshes the cached inventory and
rechecks readiness automatically. Failed commands stop automatic retry and show an
actionable error. Successful readiness enables review/submission but never starts
an experiment without the user's submission. Context fit stays unknown until the
real execution checks it; qualification gates are unchanged.

Observed verification:

- `uv run ruff check`, `uv run ruff format --check`: passed (131 files formatted).
- `uv run mypy python`: passed, 102 source files.
- `uv run python scripts/check_contracts.py`: contracts current.
- Full Python suite: 96 passed in 35.42s.
- Desktop `npm test`: 69 passed across 16 files; desktop typecheck passed.
- `npm --prefix apps/desktop run package:linux`: built 0.5.0 (about 138.4 MiB).
- `LAB_TEST_BUNDLED_BACKEND=... .venv/bin/python -m pytest -q tests/test_desktop_runtime.py`:
  8 passed in 23.56s using the final bundled backend and temporary profiles.
- `scripts/smoke_packaged_desktop.mjs`: sandboxed packaged Electron 0.5.0,
  visible window, renderer Node unavailable, wizard save/reload, one synthetic
  model and six read-only discovered engine build locations. Screenshot inspected
  at `/tmp/inference-lab-0.5.0.png`, including the import progress panel. No engine
  selected or executed; no real model weights hashed by this smoke.
- Bundled `bootstrap.py desktop-hardware` on this host: RTX 3060, driver 595.99.02,
  compute capability 8.6, 12 GiB VRAM, Vulkan 1.4, AVX2; no warnings. Other vendor
  combinations have fixture-based matching tests, not real-device acceptance.
- `scripts/smoke_window_lifecycle.mjs`: real Electron minimize/cancel/quit and
  destroyed-window cleanup passed with sandbox enabled.
- `scripts/smoke_engine_install.mjs`: final bundled extractor installed two
  synthetic side-by-side builds, llama.cpp CUDA runtime libraries and Strata
  server/interpreter support. No engine or installer code executed. Sandbox child
  spawn initially returned EPERM; rerun with approved execution passed.

Package: `apps/desktop/release/ai-inference-lab-desktop_0.5.0_amd64.deb`.
SHA-256: `7b76e60732dc5d7b295e7b60cb8a16c7e29c5b08d1c6032a6d67f19f8b390edd`.
Built, not installed by this work. Clean-host installation/upgrade, real upstream
archive qualification, AMD/Intel device acceptance and a real measured inference
benchmark remain open gates. No recipe or benchmark result was created.

## 2026-10-22 — installed-app blocker fixes and upgrade candidate

Implemented executable-ID indexing/conflict detection, durable blocked-preflight
recovery and replay handling, busy-worker command serialization, supported
cancellation dialog, stat-validated verification persistence/interruption,
explicit service/readiness states, visible hardware recommendations, themed
scrollable dialogs, human-readable bounded warnings and the conservative Small
setup test preset. Shutdown now stops remaining services even when worker
recovery fails. See `docs/DESKTOP_UPGRADE_ACCEPTANCE.md` for evidence and gates.

Commands actually run for this work:

- `uv sync --all-packages`: passed.
- `uv run ruff check`: passed; `uv run ruff format --check`: 132 files formatted.
- `uv run mypy python`: passed, 102 source files. An earlier targeted-file mypy
  invocation lacked workspace import context; the required workspace check passed.
- `uv run pytest -q`: final run **104 passed in 37.75s**.
- `uv run python scripts/check_contracts.py`: contracts current.
- `uv run python scripts/backup_databases.py --help`: passed.
- `pnpm install --frozen-lockfile`, `pnpm typecheck`: passed.
- `npm --prefix apps/desktop ci`: passed, 104 packages. An initial offline ci
  attempt failed ENOTCACHED for Vite; normal locked ci succeeded. npm reported
  three moderate advisories; no dependency audit upgrades were applied.
- `npm --prefix apps/desktop test`: **75 passed across 18 files**.
- `npm --prefix apps/desktop run build`: passed.
- `npm --prefix apps/desktop run package:linux`: passed; private CPython runtime
  and locked dependencies staged; final package about 138.4 MiB.
- `LAB_TEST_BUNDLED_BACKEND="$PWD/apps/desktop/release/linux-deb/opt/ai-inference-lab/desktop/resources/app/backend" uv run pytest -q tests/test_desktop_runtime.py`:
  final bundled-runtime run **10 passed in 23.02s**.
- `node scripts/smoke_packaged_desktop.mjs`: final rerun passed; packaged 0.5.0,
  visible, renderer Node unavailable, sandbox enabled, expected setup state.
  One preceding run hit a CDP startup race, “Cannot find default execution
  context”; an unchanged rerun passed. This was not a successful first attempt.
- `node scripts/smoke_window_lifecycle.mjs`: passed real BrowserWindow lifecycle
  with deterministic mocked prompt responses; this does not prove native dialogs.
- Extracted actual .deb using `dpkg-deb -x`, compared all 102 Python sources and
  all built frontend files byte-for-byte: passed. Initial inspection used the
  incorrect frontend folder name; corrected to the package's `dist` directory.
- Backup creation and `verify --backup apps/desktop/release/upgrade-backup-20261022/databases`:
  both stores passed size/hash/SQLite integrity. Original app services were stopped.
- `git diff --check`: passed.

Actual sandboxed packaged UI with isolated temporary data: discovery, synthetic
model verification, selected-engine persistence and verified inventory after
relaunch observed; supported cancellation dialog exercised in labelled demo
mode; both recommendation badges, selected assets and driver visible in Settings
and startup review. Expanded review Escape/focus behavior retested after fixing
it. No horizontal overflow. User confirmed native Cancel/Minimize/reopen/Quit.
During the earlier native session the live staging directory was rebuilt;
worker-journal import failed during shutdown, orphaning two temporary children.
Both were identified by their disposable database paths and stopped. The final
package includes the journal and shutdown-error regression coverage. Final native
folder-picker and clean-Quit checks remain operator-assisted/pending.

Final candidate SHA-256 (supersedes earlier 0.5.0 hashes):
`bf4e0f22dbd1da69190c609d48e64caefc9eb2c4d9d6de2425a22af8659063d9`.
Installed version remains 0.4.0. Installation approval and the guarded real test
remain open; no claim of successful real inference, live worker cancellation,
results acceptance, validated recipe, production restore or rollback is made.

### Follow-up: native picker diagnostics, approved installation and real attempts

The operator reported Add folder failing. Reproduced a pending parentless native
picker followed by “Another local runtime operation is in progress.” Attached
the picker to the requesting BrowserWindow and added private rotating
`desktop-events.log` diagnostics (request ID/stage/kind/elapsed; no paths,
secrets or raw exception/process arguments). A real Playwright-triggered native
call returned one operator-selected folder; UI discovery and verification began.
The callback was observed, not mocked. Large temporary-profile verification was
stopped through its owned supervisor; its children exited. Initial new log test
failed because a Node test environment conflicted with the shared window setup;
using the existing jsdom environment passed the private-log rotation test.

The operator explicitly requested the upgrade and one model with each engine.
Refreshed and verified both original stores plus 12 configuration/profile files
under `apps/desktop/release/upgrade-backup-20261022-final`. System authentication
was completed by the operator. `pkexec /usr/bin/dpkg -i ...0.5.0_amd64.deb`
succeeded over 0.4.0. Compared the actual extracted package against all 7,897
installed files: exact hash match. A preliminary comparison against the mutable
build staging tree encountered regenerated Python bytecode; comparison against
the actual immutable .deb passed. Installed app was launched via Playwright with
Chromium sandbox enabled and original saved configuration. All 10 model hashes
were retained, both selected engines persisted, and setup was saved in the UI.

Actual UI-driven, real-lane attempts (Small setup test, 4K, one candidate/finalist,
one screening and two final repetitions; safeguards retained):

- `exp_e570132a-6835-5a30-bec1-3752e54adcea`: llama.cpp/Gemma 12B Q4_0.
  Real CPU full-context allocation preflight passed. Baseline and candidate
  observations both failed EXTERNAL_GPU_CONTENTION; zero retained samples and
  no performance result. Controller processing completed; Compare displayed
  ineligible evidence, missing paired scores and no validated winner.
- `exp_e41c8a9f-57a3-54c8-932d-cb33cf361b7e`: Strata/coder IQ1_M pack.
  Preflight blocked because the old implementation returned Inconclusive
  unconditionally for Strata. Retry preflight was visible; no inference ran.

The real attempts exposed two additional issues addressed in the refreshed
candidate: completed invalid studies need an explicit unsuccessful-measurement
notice and per-trial reason; Strata needs a managed allocation probe rather than
an unconditional preflight block. The probe uses the existing serving adapter,
generated sandbox files, registered binaries, actual effective-context response,
quiet-GPU gate and GPU flock lease. Cancellation and command renewal are passed
to the runner; owned processes and leases are cleaned up. Missing/undersized
context remains inconclusive/infeasible; per-candidate serving and qualification
checks remain unchanged. New offline tests start trusted temporary Python HTTP
servers, verify reported context and generated-file use, cancel the allocation
check and confirm process/lease cleanup. Busy GPU tests assert no server launch.
These fake-server tests do not constitute live Strata acceptance.

Final checks for the refreshed candidate actually run:

- Ruff check and format check passed (132 files); mypy passed (102 sources).
- Full Python suite: **109 passed in 39.87s**; contract drift check current.
- `pnpm typecheck`: passed. Initial new UI test typecheck found an optional
  observations field; corrected before the final run.
- Desktop tests: **77 passed across 19 files**.
- `npm --prefix apps/desktop run package:linux`: passed, about 138.5 MiB.
- Final bundled-runtime tests: **10 passed in 23.29s**.
- Extracted refreshed .deb and compared all Python sources, renderer and
  Electron output: passed. `git diff --check`: passed.

Refreshed package SHA-256:
`a31aec89a938fc1ad15d504ac355541748252b2dfb3f57b2be2f686ff4c3fe4e`.
The first installed 0.5.0 package was
`a444be9726952135919cc1f04840b8de24dc6767cbc068e38caee816b716cb4d`.

Installed Close dialog was captured and confirmed focused/modal. Both native
keyboard automation methods failed to operate it; no fake dialog responses were
counted as acceptance. Operator-assisted lifecycle repeat remains pending. To
apply follow-up fixes, stopped only the installed app's own supervisor, confirmed
no controller/optimizer store users remained, then exited its window. Follow-up
two-store backup/verification passed under
`apps/desktop/release/upgrade-backup-20261022-followup/databases`, retaining the new
studies. Follow-up installation is awaiting system authentication. Other GPU
processes remain running; operator was asked to free GPU activity or retain an
honest blocked result. No safeguard was bypassed; the original cancelled
assessment study was not retried. No successful real benchmark is claimed.


## 2026-10-22 — real runtime interoperability and memory safety follow-up

The follow-up package a31aec89… was authenticated, installed and its payload
verified. Existing verification survived relaunch. Operator reported successful
Close/Cancel, Minimize, reopen and Quit; this is operator confirmation, not a
complete automated native event trace. Folder-picker acceptance remains open.

Actual llama.cpp trials reached GPU execution but were invalid: streaming did
not request usage and quantized V cache was proposed with flash attention off.
The candidate now requests stream usage, disables prompt-cache reuse for llama
measurements and activates quantized V-cache search only with flash attention on.
Strata startup required documented prefill/spec defaults, now applied to preflight;
IQ speculative windows have a minimum of two. Private sandbox engine logs retain
startup evidence without exposing full arguments in the UI.

An isolated Strata allocation attempt (exp_596b8a31…) allocated a 23.42 GiB
pinned expert arena. The engine warned about insufficient RAM but continued.
The kernel OOM-killed the owned Strata process (PID 666178); the temporary runtime
also stopped. No successful Strata measurement or UI cancellation is claimed.
That temporary store will not be restarted. Original stores remain preserved.

The new search space fixes file-backed experts, disables resident experts, and
uses direct table I/O. The worker rejects older unbounded-memory plans before
preflight/trial launch and checks available RAM for dense weights plus a 6 GiB
reserve. This is a conservative launch guard, not a hard process memory limit.
Six offline cases cover unsafe legacy modes, RAM tables and low/adequate RAM.

At the user's request, normal SIGTERM stopped both OpenCode processes. Eight
verified idle Playwright drivers owned by this assessment were also stopped.
Other apps, current ChatGPT/Codex and remote desktop were preserved. ChatGPT's
largest renderer used approximately 654 MiB PSS; no leak is established by a
single snapshot. Available host RAM was about 25.6 GiB after the OOM recovery.

Checks actually run: full Python suite 117 passed in 39.36s; targeted worker/
adapter suite 32 passed; Ruff check/format passed (132 files); mypy passed
(102 sources); contracts current; pnpm typecheck passed; desktop 77 tests passed
across 19 files; package:linux passed; git diff --check passed.
New package SHA-256: 6d1244b645c6f51079a93747ffe21e91fa3b27a1e684f891f9da7833ac967d5b.
Fresh isolated profile /tmp/lab-memory-safe-acceptance reuses only configuration
and stat-validated hashes (10 verified models), no previous jobs. Candidate UI
setup completed and a minimal Gemma/llama.cpp study was submitted through the UI.
Real measurements, cancellation and installation of this package remain pending.


Further observed interoperability fixes and checks:
- Real UI cancellation of exp_35549862… worked: dialog rendered, Cancel test
  submitted, controller reached Cancelled and owned engine stopped. Screenshots:
  /tmp/lab-real-cancel-dialog.png and /tmp/lab-real-cancelled.png.
- That llama baseline reported unavailable measurements: server emitted a
  separate reasoning_content stream without answer text inside the token cap.
  A short diagnostic request confirmed stream field names only (no output text
  logged); the study was cancelled and is not accepted as performance evidence.
- Installed build 701 native JSON omits test labels but reports unambiguous
  n_prompt/n_gen. Parser now accepts positive prompt-only/generation-only rows;
  mixed or empty unlabeled rows remain rejected. Captured source fields and
  numeric measurements informed an offline regression.
- New llama plans freeze reasoning=off, capability-check the observed --reasoning
  flag and emit it only in serving plans. Both baseline/candidate share this
  explicit answer-generation policy; no qualification gate was relaxed.
- A Q2 Strata attempt disproved the assumption that only IQ-labeled packs need
  speculative verification. Both discovered native packs require it. Existing
  selected-engine distributions contain standard/coder expert profiles. Discovery
  now reads the appropriate bounded file from the server distribution, hashes it
  into model identity, and checks it again before launch. No model/engine file
  was modified. Cache defaults are bounded to 16 GPU expert slots, search 8–32,
  speculative default/minimum 2. Offline profile tests detect replacement.
- Latest full Python run: 121 passed in 41.84s; Ruff and mypy passed. Targeted
  worker/conformance suite 36 passed. Latest package built successfully:
  13a2a2dcbc2040e64041f6ddc695004f4a27efae929269cdeba2b16e1a8a18a1.
  Extracted package matched 102 Python sources and all renderer/Electron assets.
- Isolated exp_87395d19… real Strata preflight passed and baseline started. File
  mappings can show ~23 GiB RSS while remaining reclaimable: observed VmLck=0,
  RssAnon~62 MiB, RssFile~23 GiB and host available RAM~23.8 GiB. This differs
  from the previous pinned anonymous arena. Measurements remain pending.


Final cache-corrected acceptance candidate (2026-10-22):
- Strata prefixes were observed reused (3194 of 3201 primary tokens), which made
  earlier isolated prefill figures misleading. Those runs are explicitly not
  accepted. Final worker resets only its owned Strata model through existing
  /v1/unload and /v1/load before timing each request, and rejects reported cached
  prompt tokens for either engine. Offline cases cover both engines and reuse.
- Final isolated Strata study exp_8985f400… completed through packaged UI. Baseline 82.4/36.3 and candidate 110.3/14.7
  prompt/decode tok/s; 3 retained samples each; all repeated/near logs observed
  zero reused tokens. No validated winner.
- Gemma/llama exp_ffc875c8-326e-55e3-a278-efde98d86a2e completed with measured
  baseline 1254.5/35.8 and candidate 774.8/18.2 tok/s, 3 samples each, no winner.
- Full Python suite 124 passed in 43.30s; 78 desktop tests; typecheck; Ruff and
  formatting; mypy; contracts current. Bundled private Python regression run:
  48 passed in 3.80s. A prior bundled invocation accidentally targeted older
  application3 and correctly failed the newly added Strata-policy test; rerun
  against final staging passed. No failure was represented as a pass.
- Final package SHA-256 2ff529e6d54d8fbb7ec80b6d16a8bc5c25834e706c56fd2243b3a9da6d4dc8bf.
  Extracted package matches all 102 Python sources and renderer/Electron assets.
- Live Runs trial state now follows retained observations, parameters are behind
  disclosure, and tables stack at ordinary window widths to avoid letter-by-
  letter wrapping. Screenshot of old unavailable results verifies the new notice.
- Original stores have no open file users. Offline backup/verify succeeded under
  upgrade-backup-20261022-memory-safe/databases; 5 configuration files initially
  copied/hashed. Original currently installed files (6852) copied and hashed into
  a rollback .deb (reconstructed, not the original archive):
  SHA-256 019f2dd17cd24e78785ef97137d9ffa655ac7436b1f16a631cd591cf43ae624e.
- Final candidate native folder picker emitted requested/opened diagnostics.
  Operator was asked to confirm usability and cancel; acceptance remains pending.


Final UI evidence at 21:45–21:55 Tehran: real completed Strata comparison showed
candidate objective 0.7450, -25.50%, paired interval 0.701–0.842, complete 4K
coverage but ineligible. No validated winner. Checked actual official release
metadata through Settings: both hardware badges, selected asset, RTX 3060 and
595.99.02 driver visible. llama CUDA 12.8 / Strata CUDA 13 recommended; no Install
button was clicked. Final package sandbox smoke passed (version 0.5.0, packaged,
renderer Node undefined, sandbox true). Added worker credential configuration to
private backup: 6 verified files total. Native picker request remains pending;
AT-SPI exposes only the app frame, so opened diagnostics alone are not counted
as a visible usable native chooser. Operator confirmation is still required.


Operator confirmed the final native folder picker works and reported cancellation.
Diagnostics independently show the request finished as selected (not cancelled),
so usability is operator-confirmed but native Cancel is not corroborated by that
trace. Only temporary configuration was involved; original roots remain intact.
Temporary services/window stopped cleanly. All isolated studies were backed up
and verified under acceptance-0.5.0/isolated-real-studies before installation.
System authentication was requested for installing the already-authorized final
package (SHA-256 2ff529e6…). No original store had open file users. Installation
completion and installed payload verification are still pending at this entry.


Authenticated final installation succeeded; dpkg completed successfully. All
6,852 regular payload files and all symlinks matched the extracted final .deb
before launch. Installed app reopened with original data: 10 verified models,
selected builds, roots and prior studies retained; original cancelled study was
not retried. Actual Settings hardware recommendations visible. Startup summary
dialog dismissed with Escape. New installed 4K Gemma/llama study exp_395444e0…
submitted through UI and preflight passed. Native lifecycle event recording was
attached for a later operator-assisted final check (no mocked dialog responses).


Installed final Gemma/llama study exp_395444e0… completed with valid measurements:
baseline 1281.6 prompt / 37.1 decode tok/s, candidate 1263.1 / 37.0, three retained
samples each, no validated winner. New installed Strata study
exp_aec8c368-47b5-5122-b02d-19de790634fc passed preflight and is running.
Observed prompt requests report zero reused tokens; available RAM ~20.7 GiB and
GPU ~52C. Current native Close dialog is awaiting operator Cancel/Minimize/reopen.
Actual showMessageBox calls are wrapped only to record the real returned response;
no dialog result is mocked or replaced. Existing window events are also recorded.


Final installed acceptance completed:
- Installed exp_aec8c368-47b5-5122-b02d-19de790634fc completed: measured baseline
  91.1 prompt / 37.7 decode tok/s, candidate 97.1 / 10.2; 3 samples each. All
  observed prompt logs reported zero reused tokens. No validated winner;
  objective ratio 0.5706, interval 0.501–0.715. Installed Gemma study full ID is
  exp_395444e0-bdb4-5abd-8f1e-d4474e52b2b1. Both are normal-profile saved work.
- Native operator responses recorded without mocking: Minimize=1, Cancel=2,
  Quit=0; hide/show/close/before-quit/will-quit/quit events corroborate actions.
  All 11 recorded owned child identities exited, main exited, stores had no
  open users. The separate Stop-and-quit confirmation was not recorded and is
  not claimed; the native window Quit path itself cleanly stopped services.
- Final stopped-store backup+verify passed under
  acceptance-0.5.0/installed-completed-studies. Controller SHA-256
  3d9956f0bf4170d88bbc1aab4bcea9d81b70d76ab0b5f8185dad35524deada58;
  optimizer 0d1be6bf6bcf721a7383ed05c76393fcc494392be988066cc559eb4af88a7e67.
- Relaunch retained both completed studies, all old studies, roots, selected
  builds and ten verified models. Startup Review updates showed two actual
  hardware recommendation badges after waiting for its panel to load; the
  initial immediate count of zero was a loading observation, not a defect.
  Modal clientWidth=scrollWidth=883. Escape dismissal worked. Package sandbox
  and renderer isolation remain intact. Installed app left on saved Strata
  comparison with services running normally; no engine process remains active.
- Screenshots, native traces and both isolated/installed verified study backups
  are retained under apps/desktop/release/acceptance-0.5.0/. Final assessment and
  rollback instructions updated. No code change followed the validated package.


2026-10-22 broader optimization requested by operator. Through the installed UI,
submitted exp_a9877d3a… (Gemma/llama) and exp_6a10df1b… (Strata coder), balanced
4K, Quick budget 12 distinct candidates, 2 finalists, screening 2, final 3.
Safety/qualification gates retained. llama baseline running; Strata preflight
queued behind the busy worker. GPU 69C, available RAM 22 GiB at observation.
No code/artifact/driver changes or unrelated-process interruption. No best
configuration is claimed before completion.


Broader llama study exp_a9877d3a… completed with 13 measured observations (baseline
+12 alternatives), zero failed trials and 3 retained samples each. Baseline
remains best balanced setting: 1284.1 prompt/36.9 decode tok/s, 2493.6ms TTFT,
8.20GiB peak GPU memory. Actual UI baseline parameters exported to the local
optimization-search artifact. Comparison shows NO_VALIDATED_WINNER; no recipe
was created. Initial queued Strata study was cancelled after 3 utilization-busy
rejections (one later baseline measured); a fresh strictly sequential search will
run after the GPU is quiet. No safety gate was disabled or engine file changed.


Fresh identical-plan Strata submission returned HTTP 500 before a new job was
visible. Read-only inspection confirmed its plan ID equals the cancelled study's
plan and study_id generation omits experiment identity. Likely repeated-plan
study-ID collision; no exception trace was present in the runtime summary.
Used the UI to set a distinct 13-candidate budget; submission committed as
exp_be36062f-401a-53dd-a7a8-6b598e8ab649. This fresh Strata study runs strictly
after the completed llama search. Safety and qualification unchanged. Defect is
recorded, not patched during this optimization run.

### Broader settings search finalized (2026-10-23 local)

- Installed UI: llama.cpp 12 alternatives + baseline completed; all 13 measured, three samples each. Baseline remains best: 1284.1 prompt / 36.9 generated tokens/s. No qualified alternative.
- Installed UI: fresh sequential Strata 13 alternatives + baseline completed; all 14 measured, no failures, three samples each. Trial 13 is VALIDATED_WINNER: objective 2.0617 (+106.17%), 95% paired interval [1.979, 2.145], 323 prompt / 39.4 generated tokens/s, TTFT 9910.7 ms, 8.77 GiB peak VRAM.
- Used real UI Create recipe once. Read-only SQLite confirms validated recipe recipe_da49af62-4b93-50e7-9c32-e5542f6175bd committed. Recipes UI returns HTTP 500 on list/retry. Read-only SQLAlchemy plus _recipe_view reproduces Pydantic created_at timezone_aware error (SQLite datetime tzinfo=None). No verification/promotion claimed.
- Saved UI-derived JSON, comparison text, screenshots and exact best-tested settings under apps/desktop/release/optimization-search-20261022/. Full report: docs/OPTIMIZATION_SEARCH_2026-10-22.md.
- Read AGENTS.md; monitored GPU utilization/temperature and MemAvailable with nvidia-smi and read-only /proc/engine progress. No source code changes or engine/model/driver changes; no tests/builds run during the benchmarks. Two observed application defects remain documented: identical-plan new-study HTTP 500 and recipe timestamp response HTTP 500.

### 0.6.0 production-readiness and managed serving candidate — 2026-10-23

Operator asked for production readiness, then explicitly requested engine launch
from best recipes with both built-in chat and local application access. Existing
work was preserved. No installed app, engines, drivers or model files changed.

Fixed repeated-plan study-ID collisions, SQLite recipe timestamps, recipe
loading/error recovery, persisted validation/context display and asynchronous
verification results. Added typed outbound RUN_RECIPE/STOP_RECIPE/RECIPE_CHAT
commands, authenticated operator routes, current serving health, additive
controller migration c712e4d509ab, worker-owned loopback server/GPU lease/process
journal and bounded tokenizer-checked chat. Run regenerates and checks the native
Strata profile from the retained candidate; unsafe old promotion prompts are no
longer offered. Configuration changes and benchmarks are blocked while serving.
Launches predating a worker restart are refused; expired launch/chat commands do
not automatically requeue. GPU availability is checked before large-file hashing
and again before launch. Stop during startup retains the lease until cleanup.

Observed validation commands/results (final logs under acceptance-0.6.0):
- uv run pytest -q: 141 passed. Fifteen serving cases use tiny real HTTP fixture
  processes for both families; two transport cases cover non-requeued interactive
  leases. API tests cover run/chat idempotency and active-serving conflicts.
- npm --prefix apps/desktop test: 83 passed across 21 files.
- uv run ruff check, ruff format --check (138 files), mypy python (105 files),
  pnpm typecheck, scripts/check_contracts.py: passed. Contracts regenerated
  only through pnpm generate:contracts. git diff --check passed.
- Desktop build/package passed. Final 0.6.0 SHA-256:
  d4cf46f979b4b34cc56bb39065ea87a418dfd104bb9feb63d3b6e3290b0be77a.
  Extracted backend source matches and renderer controls checked.
- Packaged startup smoke passed with visible UI, sandbox=true and renderer
  require=undefined. Fixed a narrowly bounded CDP startup-context race in the
  smoke harness. LAB_TEST_BUNDLED_BACKEND with an absolute path: 10 runtime tests
  passed. The initial relative-path invocation failed as a harness path error.
- Copied real stores migrated with nine studies intact and pre-migration
  snapshots of both stores. Read-only original snapshot backup verified. A
  temporary rollback rehearsal preserved/verified newer stores and restored old
  stores with all IDs/states intact; active WAL refusal was observed first.
- The winning saved Strata recipe opens correctly and worker identity verify
  completed in a copied 0.5.1 profile. Real 0.6.0 launch progressed through
  85,040,157,676 bytes/13 files in an early draft, then refused external GPU
  compute use. GNOME portal PID 658411 identified by name/PID only. Final build
  Run and explicit Retry both refused before hashing (0 bytes), no engine start.
- Native lifecycle while serving and real chat/endpoint acceptance remain
  blocked by GPU mode choice. No helper was stopped, safeguards were not relaxed,
  and no engine/chat success is claimed. Temporary app cleanup used Electron app.exit after a normal signal did not
  exit it; parent-EOF stopped services and all temporary profile processes were
  confirmed gone. This is not native Quit acceptance.

Full evidence/gates: docs/PRODUCTION_READINESS.md; architecture ADR 0021.
The current candidate is not labelled production ready and is not installed.

## 2026-10-23 — Nontechnical in-app help

Added a local Help & guide route in primary navigation and Getting started on
Overview. Searchable, expandable topics cover parent-folder setup, engine
selection, verification and recovery, the Small setup test, progress and
cancellation, results and no validated winner, saved recipes, chat/local serving,
update recommendations, and window lifecycle. Includes a plain-language glossary
and navigation buttons; reading help does not start jobs or change configuration.
Help renders independently of the runtime-blocking panel, including when local
services fail. The sidebar navigation can scroll at short window heights.
Existing source changes were preserved; no installed package, engine, model or
user store was changed. The earlier 0.6.0 package was not rebuilt by this change.

Observed validation:
- `npm --prefix apps/desktop test -- src/App.test.tsx`: 4 passed, including
  search/no-results recovery and Help access with local runtime in error.
- `pnpm typecheck`: passed.
- `npm --prefix apps/desktop run build`: passed.
- `npm --prefix apps/desktop test`: 85 passed, 21 files.
- `git diff --check`: passed.
- Started the built renderer preview for visual inspection, but browser access
  to localhost was rejected by the permission gate as user-declined. No alternate
  browser/CDP route was attempted. Preview was stopped. Rendered layout/native
  acceptance is unverified for this addition; no screenshot or visual-pass claim.

## 2026-10-24 — Precision workstation UI foundation

Read the UI implementation prompt, PRD v2.1, architecture, design handoff and
phase/status evidence. Current scope is Phase 8 offline hardening with a 0.6.0
working desktop candidate; later real 0.5.0 evidence supersedes the initial
simulation-only entries. Preserved the existing dirty working tree.

Added a semantic workstation CSS layer across all existing routes, persistent
system/dark/light appearance, keyboard workspace access, focus/reduced-motion
rules and a selected immutable-trial inspector in Live Runs. Kept generated
contracts, IPC/CSP/sandbox, worker ownership and qualification unchanged. Fixed
wrapping digest/headings, stretched worker badges and misleading empty history
when disconnected. No dependency, model/engine, service or database changes.

Observed verification for this work:
- `npm --prefix apps/desktop test`: 88 passed across 21 files, including new
  appearance persistence and selected-trial evidence/units tests.
- `npm --prefix apps/desktop run typecheck`, `pnpm typecheck`: passed.
- `npm --prefix apps/desktop run build`: passed after final visual fixes.
- `uv run python scripts/check_contracts.py`: contracts current.
- `uv run pytest -q tests/test_api_flow.py tests/test_desktop_runtime.py`:
  16 passed in 29.58 seconds. Full Python suite was not rerun for UI-only changes.
- `uv run ruff check`, `uv run ruff format --check`: passed, 138 files.
- `uv run mypy python`: FAILED on the existing unused `type: ignore` at
  `python/lab_api/lab_api/services/commands.py:454` (105 files checked).
  This pre-existing modified backend file was not changed for this UI task.
- `node scripts/smoke_window_lifecycle.mjs`: passed real sandboxed Electron
  minimize/cancel/quit/destroyed-window handling with deterministic prompt choices.
- `node scripts/capture_workstation_ui.mjs`: actual Linux Electron, disposable
  unmanaged profile, 66 dark/light route/viewport captures; no document overflow,
  renderer require undefined. Additional preflight/selected-inspector/disconnected
  captures retained. No real controller jobs or benchmark measurements created.
- `git diff --check`: passed.

Audit, exact changed areas, screenshot method and remaining accessibility,
performance, lifecycle and live acceptance limitations:
`docs/UI_IMPLEMENTATION_AUDIT.md`. Evidence: `docs/evidence/ui-workstation/`.
No package rebuild/install or production acceptance is claimed.

Final follow-up: added disconnected-history regression (desktop total **88**),
corrected skip-link focus to preserve the hash route, and rebuilt/typechecked.
Native dark/light frame capture passed after resolving multi-display capture
coordinates and stale first-frame output. Rejected diagnostic captures were
removed. Final inventory: 75 PNGs, explicit offline fixtures plus disconnected
IPC state, with native minimize/maximize/close controls visible. Full evidence
limitations remain in the audit; native frame visibility is not full live-job
lifecycle acceptance.

## 2026-10-24 — Workstation UI completion and operator refinements

Completed the independent UI scope after rereading the original implementation
prompt and design/phase evidence. Preserve earlier entries as history; the current
acceptance checklist is `docs/UI_COMPLETION_CHECKLIST.md` and the detailed follow-up
is in `docs/UI_IMPLEMENTATION_AUDIT.md`.

Final operator-directed chrome: **one compact light/dark toggle next to the refresh
icon in the header**. No theme dropdown or sidebar theme controls remain. System
appearance is selectable in Settings. Replaced handwritten utility icons and mixed
navigation glyphs with locally bundled, pinned Lucide React 1.61.0 (React 19 peer
compatible); npm manifest/lock updated. One header refresh now refreshes all mounted
page queries, including worker snapshots and recipe lists. Removed duplicate page
and panel refresh buttons from Workers, Recipes, Models, Engines, Overview and
Updates. Run resync and error Retry remain scoped remediation actions. Refresh
never launches a scan, preflight, engine or upstream release check.

Completed: searchable/collapsible/adjustable trial inspector, 50-record paged and
sortable evidence tables, bounded failure notices, model search, provenance/context
filter, bounded SVG plots with explicit coverage and tabular alternatives, numeric
alignment, preflight command/reason visibility, numeric budget checks and collapsed
advanced limits. Improved status semantics, pending/empty/disconnected states,
keyboard tabs, dialog isolation/focus, and theme/control contrast. Fixed a source
isolation defect so switching demo off cannot expose cached fixture numbers as
real-controller data. Demo experiment creation is refused at UI and API-facade
boundaries. No benchmark/qualification semantics changed.

Mypy initially reproduced the unused-ignore error at commands.py:454. Removing
the ignore exposed dynamic union inference; an explicit `TypeAdapter[CommandResult]`
annotation fixed both normal and nonincremental checks without changing parsing.
No generated contracts, PRD, engine/model files, production stores, installed
package or service lifecycle were modified by this follow-up.

Observed final validation:
- `npm --prefix apps/desktop test`: **101 passed, 24 files**.
- `pnpm typecheck`: passed (generated client plus renderer/Electron/test TS).
- `npm --prefix apps/desktop run build`: passed; final JS about 409.49 kB,
  gzip 119.33 kB. No desktop ESLint command exists; no ESLint pass is claimed.
- `uv run ruff check`, `uv run ruff format --check`: passed, 138 files.
- `uv run mypy python`: passed, 105 sources; `--no-incremental` also passed.
- `uv run python scripts/check_contracts.py`: contracts current.
- `uv run pytest -q`: **141 passed in 46.37 s** (final Python source).
- `node scripts/smoke_window_lifecycle.mjs`: passed actual sandboxed Electron
  minimize/cancel/quit/destroyed-window cleanup, using deterministic prompt choices.
- `node scripts/verify_workstation_ui.mjs`: actual Linux Electron on isolated
  unmanaged profiles. All eleven routes at 1024×768, 1440×900 and 1920×1080,
  both themes; explicit stale, partial, empty, error, replay-gap, large and OOM
  fixtures. No document overflow; **zero text-contrast failures in measured states**.
- `node scripts/capture_workstation_native.mjs`: native dark/light app frame
  captured and reviewed, including final theme/refresh placement. Captures are
  cropped to the app; no unrelated desktop content retained.
- `node scripts/verify_workstation_keyboard.mjs`: seven actual Electron keyboard
  checks passed (toggle/persistence, inert background, Tab/Shift-Tab, Escape/focus
  restoration, recipe Home/End tabs).
- Final screenshot inventory: **84 PNGs** in
  `docs/evidence/ui-workstation-completion/`; QA and keyboard JSON accompany them.
  Reviewed native frames, both themes, stale preflight, partial metrics, OOM,
  comparison, inventories, and large-trial workspace; original 75 images remain
  historical foundation evidence.
- 5,000-trial fixture: 100 mounted Live Runs candidate/observation rows; Compare
  plots 200 scatter points plus one paired score, with explicit limits and all
  records reachable in tables. After CDP garbage collection, two-second idle
  renderer TaskDuration deltas were 45.1 ms dark / 40.5 ms light; JS heaps about
  11.1 MB / 10.2 MB. These are renderer fixture measurements, not inference or
  GPU-contamination proof. Full values and attached DOM counts are in qa-report.json.
- `git diff --check`: passed.
- `npm --prefix apps/desktop audit --json`: reports **4 existing advisories**
  (2 high, 2 moderate) affecting Electron/undici/Vitest/mocker; none reported for
  Lucide. No unrelated major framework auto-upgrade was performed.

Historical authorization for desktop supervision is recorded in section 10 and
ADR 0019; current managed Quit still calls runtime.stop, while Minimize keeps
local work alive. UI copy now states that boundary. PRD independent-system-service
acceptance remains a separate unresolved deployment gate. No real benchmark was
started for this work. Full screen-reader/platform, clean-host, L40S, performance
contamination and release-dependency remediation remain open; no production-ready
or full PRD acceptance claim is made.

## 2026-10-24 — 0.6.1 installer, cleanup and explicit local-data reset

The operator requested cleanup, a new installer/command, and a Settings action to
start fresh. Added **Settings → Start fresh → Reset local data…** through a narrow,
validated preload/main IPC method. Main requires an idle reachable managed local
controller, serializes against other operations and rechecks after a native warning
whose default is Cancel. Demo/unmanaged/active-work states cannot invoke reset.
No reset was run on operator data.

Reset moves only known app-owned lab stores, worker/hash state, artifacts, backups,
configuration and persisted credentials to recoverable OS Trash; clears Electron
storage/cache; then relaunches. Engine/model files and unknown files are preserved.
Overlapping configured roots and symlinked records are rejected. Shutdown failure
moves nothing; Trash failure restores moved records or retains a clearly reported
reset-recovery folder. This is not secure erasure. No API/backend/worker lifecycle
or generated contract change was required. See RUNBOOK.md for scope and recovery.

Version bumped from 0.6.0 to **0.6.1** in npm manifest/lock. An initial 0.6.1 build
preceded the reset request; it was superseded by the final package containing reset.
A subsequent build correctly failed on a nullable runtime capture introduced during
workflow extraction; binding the checked manager locally fixed it before the final
successful build. Earlier failed attempts are not counted as passes.

Observed final commands/results:
- `npm --prefix apps/desktop test`: **107 passed, 26 files**. New tests cover
  native cancellation/activity recheck, paired-store move/preservation, protected
  assets, rollback on Trash failure, symlink/overlap refusal, shutdown failure,
  demo/busy UI gating and cancellation feedback.
- `pnpm typecheck`: passed.
- `npm --prefix apps/desktop run package:linux`: passed; renderer/main/preload and
  private CPython 3.13.16 plus 34 locked dependencies staged offline.
- `dpkg-deb --info` and extraction: version 0.6.1 amd64, **145,209,280 bytes**
  (~138.5 MiB); **6,859 payload files matched staging byte-for-byte**, including
  the reset main-process module. No package was installed.
- `LAB_SMOKE_RESET_UI=1 node scripts/smoke_packaged_desktop.mjs <extracted executable> <evidence PNG>`:
  passed actual packaged Electron, sandbox=true, renderer require undefined,
  visible startup, local runtime needs_configuration; Settings reset button and
  bridge present/enabled for idle temporary lab. No reset was invoked. Startup
  and Settings screenshots saved under ui-workstation-completion/package-0.6.1-*;
  Settings Start fresh panel visually inspected.
- `LAB_TEST_BUNDLED_BACKEND=<absolute extracted backend> uv run pytest -q tests/test_desktop_runtime.py`:
  **10 passed in 23.76 seconds**, isolated stores/runtime.
- `git diff --check`: passed.

Final package: `apps/desktop/release/ai-inference-lab-desktop_0.6.1_amd64.deb`.
SHA-256: `32d8ba70c0ab386acfc6bc369e4cd0c169f2290dd6e47927e900094dd05db898`.
A sibling `.deb.sha256` file records it. Package/signing/clean-host and actual native
reset/OS Trash/relaunch acceptance remain separate gates; fake dialog responses
and callback-based temporary-file tests are not claimed as native acceptance.
Existing dependency audit findings still apply; no production-ready claim.

Cleanup removed 25 known disposable UI profiles and owned scratch scripts first.
Final extraction, smoke profile and generated staging are removed only after their
processes have exited and package verification is complete. Source changes, final
installer/checksum, screenshots, older release packages and recovery backups remain.
Original installed app configuration/stores and model/engine directories were not
modified by the build, verification or cleanup.


### Git ignore hygiene — 2026-10-24

Added coverage, Vite/Vitest caches, profiling dumps and desktop-local disposable
profile/recovery directories to `.gitignore`. Kept the renderer `src/lib` source
exception. `git check-ignore` confirmed generated installer/coverage/cache/profile
paths are ignored; bridge source, runtime bootstrap, npm lockfile and QA evidence
remain visible. Unrelated source changes remain unstaged; no files were deleted.

## 0.6.2 — restored source, task guidance and actionable maintenance (2026-10-24)

The cleaned checkout contained the older 0.1.0 desktop while the operator's
screenshots came from 0.6.1. Restored application/backend/tests/contracts/design
and acceptance material from the cleanup stash at the operator's request. The
stash remains intact. Kept the current public README and supplied repository
rules; did not restore archival deletions, modify PRD, install systemd units,
install a package, run inference or change operator models/engines/databases.
Restored work is committed by worker, controller, desktop supervision, engine
manager, packaging, renderer and acceptance areas.

New journey work:
- Overview explains Prepare → Optimize → Review with working navigation actions.
- Updates separates llama.cpp and Strata with family buttons. Offline release
  classification/comparison tools are under an advanced disclosure. Existing
  explicitly confirmed desktop engine installation remains a separate boundary.
- Main-owned installation status retains observed bytes, download/unpacking
  stage, complete/failed state and installed asset identity. Completion offers
  the matching discovered build selection, with a setup fallback while discovery
  is unavailable. It never silently switches engines. Native cancellation is
  acknowledged, and the already installed asset cannot be installed again from
  the primary action.
- Model verification explains missing/unreadable/split-file checks, displays a
  two-minute progress-silence advisory without inventing a timeout failure, and
  offers guarded rescanning. A current scan that finishes with unverified models
  retains a failure indicator instead of disappearing. Stale prior-session
  completion still cannot masquerade as a current failure.
- Context proof warnings now say Context check pending and explain the next
  step. This does not change preflight, qualification or backend error states.
- Shared action controls use the same size/line-height/alignment. A local raster
  window icon, SVG/raster launcher assets and matching Linux desktop identity
  replace the generic application icon. NativeImage reads the 256×256 icon.
- Optimize discloses finite-search, Strata resident/asynchronous profile coverage
  and client-versus-engine timing limits. Read-only manual benchmark findings are
  in PERFORMANCE_COMPARISON_2026-10-24.md. No speed improvement is claimed.

Observed verification after corrections:
- `uv run pytest -q`: **142 passed in 44.41 s**.
- `npm --prefix apps/desktop test`: **111 passed, 27 files**, including observed
  progress, family isolation, exact discovered-build selection, incomplete/stalled
  verification, active-work retry refusal and installed-asset feedback.
- `uv run ruff check`, `uv run ruff format --check` (138 files),
  `uv run mypy python` (105 files), `uv run python scripts/check_contracts.py`,
  `pnpm typecheck`: passed. Contracts restored from generated baseline, not edited
  by hand. JS syntax checks for the new capture and keyboard scripts passed.
- `npm --prefix apps/desktop run build` and `run package:linux`: passed.
- `node scripts/capture_journey_qa.mjs`: **32 actual Electron screenshots**,
  dark/light, four routes at 1024×768, 1440×900, 1920×1080, plus eight maintenance
  fixtures. Main/preload remain sandboxed; no renderer Node integration. Route
  captures check document overflow. Download/unpacking/complete/failed screenshots
  use explicit fixtures, not real downloads or installation evidence. Reviewed
  overview and maintenance dark/light captures; corrected repeated install action
  and ambiguous completion labels. New report records icon size and Linux class.
- Packaged extraction matched **6,862 payload files** byte for byte to staging;
  visual QA harness is absent from the installer.
- Packaged Electron smoke: 0.6.2, visible startup, sandbox=true, renderer require
  undefined, isolated runtime needs_configuration. Settings reset bridge/UI passes;
  no reset invoked. A bundled-runtime test run passed **11 tests in 22.76 s**.

Earlier attempts exposed one stale/current verification distinction and one
no-hardware-recommendation installed-asset selection defect. Both were corrected
and the relevant suites rerun successfully. The visual harness initially needed
an explicit JSX-runtime resolution alias and corrected icon probe path; the final
report is from the successful run. A restored keyboard script whitespace issue
was also corrected. These initial failures are not counted as successful checks.

Package: `apps/desktop/release/ai-inference-lab-desktop_0.6.2_amd64.deb`, with a
sibling SHA-256 file. This is a locally built and smoke-tested artifact, not a
clean-target installation/upgrade acceptance. No actual native reset/Trash,
new engine install/selection or matched manual-versus-app performance run was
performed. Existing deferred phase gates and dependency-audit limitations remain.
