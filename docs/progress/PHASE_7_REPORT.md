# Phase 7 report — offline release intelligence and paired regression records

Date: 2026-10-21

Status: **implemented and verified offline. This report is part of the Phase 7
local commit. No upstream release was fetched, no candidate artifact was
downloaded, no engine was installed and no real A/B benchmark was executed.**
No result in this phase approves an upgrade.

This report records only work actually performed. Imported metadata, demo
fixtures, unit tests and an `IMPROVED` classification are not evidence that a
candidate build is faster or safe to install.

## 1. Delivered

### Pure release domain (`python/lab_updates`)

- Added frozen `ReleaseMetadata`, `ReleaseAsset`, `ChangedArea`,
  `ReleaseSource`, `ReleaseDecision`, `RecommendedAction`, `ImpactAssessment`
  and `CapabilityDiff` contracts. Assessments carry an explicit
  `model_identity_complete` flag derived from verified file hashes.
- Added deterministic path classification:
  - CUDA kernels, backend selection, MoE, KV cache, context, model loader:
    **P0**;
  - scheduling, threading, batching, server API, unknown paths: **P1**;
  - documentation, tests, unrelated GPU architecture, other: **P2**.
- Unknown or missing changed-path evidence requires smoke testing; it is never
  silently compatible.
- Capability-schema diffs compare typed descriptors and can only raise impact,
  not lower it.
- Added frozen `ComparisonPlan`, `ComparisonSample`, `ComparisonEvidence`,
  `ComparisonResult` and `ContextComparisonResult` records. Plans freeze both
  engine identities, model digest, worker, workload, contexts, margin and
  confidence level.
- Added deterministic evidence evaluation:
  - `IMPROVED` requires every selected context to pass the declared margin with
    a confidence interval strictly above baseline;
  - `REGRESSED` on a significant drop or candidate guardrail failure;
  - `INCOMPATIBLE` for simulation, non-measured status, identity/workload
    mismatch, missing/extra contexts or baseline guardrail failure;
  - `upgrade_approved` is a literal `False` in every result.
- Added immutable evidence digest/replay rules.

### Controller persistence and API

- Added migration `9f2a7c1e4b6d` after `b151f9870480` creating:
  - `release_notices` (metadata digest, source, decision, timestamps);
  - `release_assessments` (worker/model/inventory/current-hash-bound immutable
    assessment payload);
  - `engine_comparisons` (frozen plan, status, evidence digest, evaluation time).
- Controller schema is now 23 tables; the migration test was updated and passes.
- Added operator-only endpoints:

```text
POST /api/v1/releases/check
GET  /api/v1/releases
GET  /api/v1/releases/{notice_id}
POST /api/v1/releases/{notice_id}/decision
POST /api/v1/comparisons
GET  /api/v1/comparisons
GET  /api/v1/comparisons/{comparison_id}
POST /api/v1/comparisons/{comparison_id}/evidence
```

- Import is offline: the service makes no outbound call, opens no engine/model
  file and starts no process.
- Repeated metadata digest returns the existing notice; assessments are
  idempotent by notice, worker/model digest, installed hash, inventory revision
  and policy version.
- Decision actions persist `pinned`/`deferred` and append an audit event.
- Comparison creation requires an applicable P0/P1 assessment, a complete
  verified model identity digest and candidate executable SHA-256. Missing
  hashes or incomplete model hashes return `409`.
- Evidence submission is replay-safe for identical terminal evidence and returns
  `409` for different terminal evidence. It does not overwrite prior evidence.
- The API test workflow creates a P0 assessment, pins the notice, freezes an A/B
  proposal, submits a controlled regression, replays the same evidence, rejects
  conflicting evidence, rejects simulated evidence as `INCOMPATIBLE`, blocks a
  missing artifact hash, and verifies the installed snapshot is unchanged.

### Desktop Updates screen

- Replaced the Phase 6 placeholder with a functional read-only review surface:
  - worker/model selection and cached installed build/SHA display;
  - offline release JSON import with a template;
  - notice list and durable decision badges;
  - P0/P1/P2 impact, applicability, stale inventory, reasons and
    capability-diff summary;
  - pin/defer controls with a decision note;
  - an incomplete model identity badge and blocker alongside a missing
    candidate hash;
  - fixed-workload A/B proposal with explicit context selection;
  - comparison status, per-context score/improvement/interval, recommendation
    and reasons;
  - `upgrade_approved=false` and "never installs automatically" messaging.
- Added demo fixtures for a P0 CUDA/KV release, a docs-only P2 release and a
  measured regression. Demo imports and comparisons remain visibly offline and
  cannot install anything.
- Added `LabApi`/`HttpClient`/`DemoClient`/`MockApi` methods for releases,
  decisions, comparison proposals and evidence.

### Contracts

- Exported `ImpactAssessment`, `ReleaseMetadata`, `ComparisonPlan`,
  `ComparisonResult` and `ComparisonEvidence` to JSON Schema and TypeScript.
- Regenerated OpenAPI, JSON Schema/manifest and TypeScript declarations.
  `scripts/check_contracts.py` reports `contracts are current`.
- Added generated aliases for release/comparison types to the desktop UI.

## 2. Verification actually performed

Python gate:

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 118 files already formatted

uv run mypy python
# Success: no issues found in 97 source files

uv run pytest -q
# 66 passed in 10.92s

uv run python scripts/check_contracts.py
# contracts are current
```

Desktop/root gate:

```bash
pnpm typecheck
# @lab/client-contracts tsc pass
# desktop renderer, Electron main/preload and test-type tsc pass

npm --prefix apps/desktop test
# 9 test files, 29 tests passed

npm --prefix apps/desktop run build
# Vite production renderer + Electron build passed
# dist/assets/index-CQZMYOhX.js 336.50 kB (gzip 97.12 kB)
# dist/assets/index-DRtlQKTH.css 22.81 kB (gzip 5.15 kB)
```

Packaging and deployment authoring:

```bash
npm --prefix apps/desktop run package:linux
# built ai-inference-lab-desktop_0.1.0_amd64.deb (84.0 MiB)
# 88,126,426 bytes
# sha256 8eb33620715678312a4a3908101d5a545a0f500b6282c07c25e3202714c50c38

systemd-analyze verify packaging/systemd/lab-*.service
# parsed all three units; only expected missing deployment executables
# /opt/ai-inference-lab/.venv/bin/lab-* were reported
```

The `.deb` was built but **not installed**. No unit was installed or enabled.

`uv run --env-file .env alembic upgrade head` was not run because `.env` is not
present in this workspace. The migration was exercised by
`tests/test_migrations.py`, which upgrades a temporary SQLite database to head
and asserts all 23 tables and the recorded revision.

## 3. Tests added or updated

- `tests/test_updates.py` (16 tests): purity/import boundary, P0/P1/P2 paths,
  docs-only ignore, unknown path smoke escalation, model-family applicability,
  capability diffs, already-installed releases, complete/incomplete model
  identity, improved/regressed/inconclusive outcomes, candidate guardrail
  failure, simulated evidence, missing contexts, model mismatch, immutable
  completed evidence and workload/GPU-bound comparison identity.
- `tests/test_api_releases.py`: offline import/reuse, pin, A/B freeze, measured
  >5% regression, evidence replay, conflicting evidence `409`, simulated
  evidence `INCOMPATIBLE`, missing artifact hash `409`, and unchanged installed
  snapshot.
- `tests/test_migrations.py`: expects the three release tables and 23 total.
- `apps/desktop/src/pages/UpdatesPage.test.tsx`: import/control/result flow.
- `apps/desktop/src/App.test.tsx`: Updates now asserts release intelligence
  instead of the Phase 6 placeholder.
- `apps/desktop/src/lib/mock.ts` and `api.ts`: Phase 7 demo/live methods.

## 4. Not performed

- No remote release poll, GitHub request or artifact download.
- No candidate engine installation, replacement or execution.
- No real measured A/B run, so no real `IMPROVED`/`REGRESSED` result exists.
- No recipe or promotion derived from release intelligence.
- No `.deb` installation, signing, upgrade, rollback or AppImage build.
- No full GUI session against a live controller/worker.
- No systemd unit installation or enablement.
- No real model hash scan, preflight or trial.

## 5. Known limitations

- Import requires an operator-supplied `artifact_sha256` and a complete verified
  model identity before a comparison can be created. Metadata without either is
  still assessed but cannot become a study.
- The UI has no evidence-entry form. Evidence is submitted through the
  controller API after a separately approved measured run; this avoids treating
  a UI action as a benchmark.
- Classification is path/area based, not a full source diff analysis. Unknown
  paths intentionally remain P1 and require smoke testing.
- The comparison endpoint accepts evidence; it does not itself schedule or
  execute old/new engine runs. Worker-mediated interleaved A/B execution is not
  implemented in this phase.
- Remote source polling and artifact provenance/download are deferred and need a
  separate security review.
- Demo fixtures are not evidence and cannot be imported into a real controller.
