# Next steps

Last updated: 2026-10-21.

## Current state

Phases 0/1/2/3/4/5/6/7 and the Phase 8 offline-hardening increment are
committed locally. Phase 7 adds offline release intelligence. Phase 8 adds
credential-scope tests, verified two-store SQLite backup/restore, an operations
runbook and an honest AC-01…AC-44 acceptance matrix. It is verified
offline/unit/typecheck/build only. The Phase 8 exit gate — target-host
acceptance with pinned manifests — is **not met**.

No real preflight or trial has been run, no model has been fully hashed, and no
validated real recipe exists. No real A/B comparison has been executed against
an installed candidate. Simulated and demo evidence remain non-promotable.

Read `docs/progress/PHASE_2_REPORT.md` through
`docs/progress/PHASE_8_REPORT.md` for evidence, `docs/ACCEPTANCE_MATRIX.md` for
AC status and `docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Completed — Phase 7

- Added `python/lab_updates`, a pure package for release metadata, deterministic
  path/area classification, capability diffs, frozen A/B plans and evidence
  evaluation. It performs no network, process, filesystem or hardware I/O.
- Added an Alembic revision creating `release_notices`, `release_assessments`
  and `engine_comparisons` (controller schema now 23 tables).
- Added operator-only endpoints:
  `POST /api/v1/releases/check`, `GET /api/v1/releases`,
  `GET /api/v1/releases/{id}`, `POST /api/v1/releases/{id}/decision`,
  `POST /api/v1/comparisons`, `GET /api/v1/comparisons`,
  `GET /api/v1/comparisons/{id}` and
  `POST /api/v1/comparisons/{id}/evidence`.
- Classification is deterministic and conservative: CUDA/backend/MoE/KV/
  context/model-loader are P0; scheduling/threading/batching/server API are P1;
  docs/tests are P2. Unknown paths are P1 and require smoke testing. Capability
  diffs can raise impact. Stale inventory can raise P2 to P1. Missing installed
  engine identity makes a release non-applicable.
- Import is offline. Repeated metadata reuses the durable notice; assessment IDs
  bind notice, worker/model digest, installed executable hash, inventory
  revision and policy version. No upstream call, artifact download or installed
  file mutation occurs.
- A/B creation requires an applicable P0/P1 assessment, complete verified model
  identity hashes and candidate executable SHA-256. It freezes baseline/candidate
  identities, model digest, worker, workload, contexts, margin and confidence
  level. Missing hashes return `409`.
- Evidence is immutable: identical terminal evidence replays; different terminal
  evidence returns `409`. Simulated/non-measured evidence is `INCOMPATIBLE`.
  Missing contexts, identity mismatch, baseline guardrail failure and candidate
  guardrail failure are handled explicitly. `upgrade_approved` is always `false`.
- Replaced the Updates placeholder with a functional read-only review screen:
  installed inventory, offline JSON import, assessment reasons, pin/defer,
  A/B proposal and comparison intervals/results. It never downloads, launches,
  installs or approves an update.
- Added ADR 0017 documenting the offline, non-approving release boundary.
- Regenerated OpenAPI/JSON-Schema/manifest/TypeScript contracts and added
  `ImpactAssessment`, `ReleaseMetadata`, `ComparisonPlan` and
  `ComparisonEvidence` schemas.

Verification run:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
npm --prefix apps/desktop run package:linux
systemd-analyze verify packaging/systemd/lab-*.service
```

`uv run pytest -q` includes the release core/API/migration tests. The A/B test
asserts that the installed snapshot engine hashes and model records are
unchanged by the full import/assessment/comparison workflow.

## Completed — Phase 8 offline hardening

- Added `tests/test_security_hardening.py`: public health only, credential
  scoping, separate enrollment and disabled-worker rejection.
- Added `lab_api.backup` and `scripts/backup_databases.py`: online two-store
  backup, manifest SHA-256/size/integrity verification and offline restore with
  a pre-restore snapshot. Tests cover tamper detection, existing-target
  preservation, unsafe labels and WAL/shm refusal.
- Fixed a flaky synthetic measured-recipe fixture so candidate samples derive
  from the paired baseline rather than assuming a simulated candidate was
  already near baseline.
- Added `docs/RUNBOOK.md`, `docs/ACCEPTANCE_MATRIX.md`, ADR 0018 and the Phase 8
  report.
- Rebuilt and inspected the `.deb`; no installation or privileged action was
  performed.

## Remaining — Phase 8 live acceptance

The following remain operator/approval-gated and must be recorded before the
Phase 8 exit gate can be claimed:

- install/enable systemd units and verify boot/logout survival;
- install/upgrade/rollback the `.deb`, verify uninstall data retention, and
  decide whether AppImage packaging is required;
- run the full ~270 GiB model/source-shard hash scan, a real preflight and a
  low-impact paired trial on the RTX 3060;
- run representative long-context/full-context proof, including Strata, and
  close the `INCONCLUSIVE` status;
- run a full GUI session against a live controller/worker;
- run a real hardware matrix if L40S access is available;
- measure AC-31 concurrency, AC-33 event-loop/SSE latency, AC-42 24-hour
  telemetry retention, AC-15 quality failure, AC-28 future adapter and AC-40
  locked-keyring fallback;
- execute and record a real release A/B if an approved candidate binary exists.

Remote release polling and artifact download remain deferred even after Phase 8
unless separately reviewed and explicitly enabled.

## Pending operator approvals

These actions need explicit approval and are not started:

1. A full SHA-256 scan of `/home/pouya/ai-lab/models` (~270 GiB first run).
2. One real llama.cpp preflight on the RTX 3060.
3. One paired baseline plus low-impact real candidate trial (4K context, short
   repetition) on an idle GPU.
4. A full GUI run against a live controller/worker, and a packaged `.deb`
   installation/upgrade/uninstall test.
5. Any intensive multi-context benchmark campaign.
6. Installing or enabling any systemd unit.
7. Restoring a production controller or optimizer database.
8. Any download, engine replacement or model mutation (normally forbidden).
9. AppImage tooling acquisition, signing or release publication.

## Real validation entry evidence

Before any real recipe is claimed, collect:

- complete engine and source-shard hashes, including every Strata source shard;
- a real preflight result with effective context and resource outcome;
- one eligible measured baseline and candidate at the same context and workload,
  with at least two retained primary samples each;
- TTFT, decode throughput, telemetry, quality/stability evidence and a passing
  near-capacity context check;
- the qualification decision and any failed contexts for an honest
  `NO_VALIDATED_WINNER` result;
- a second GPU run if hardware becomes available.

## Do not

- Do not promote simulated, demo, `screening_only`, character-fallback or
  hash-incomplete evidence.
- Do not let the Electron renderer receive the operator token, launch engines or
  own durable jobs.
- Do not enable hardware acceleration silently or treat a UI build as evidence.
- Do not run Optuna inside FastAPI or share controller/optimizer databases.
- Do not add subprocess/network/filesystem/hardware access to adapters.
- Do not terminate unowned processes or write under model/engine roots.
- Do not hand-edit generated contracts.
